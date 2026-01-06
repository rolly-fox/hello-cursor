"""
Validation engine for NetBox Trust Boundary.

Implements all validation checks and classification logic.
"""

import re
from typing import Optional

from .models import (
    CSVRow,
    ValidationResult,
    ValidationStatus,
    RowClassification,
    NetBoxCache,
    CachedDevice,
)


class Validator:
    """
    Validates CSV rows against NetBox cache.
    
    Runs a series of checks and produces a ValidationResult for each row.
    """

    def __init__(self, cache: NetBoxCache, naming_pattern: Optional[str] = None):
        """
        Initialize validator.
        
        Args:
            cache: NetBoxCache containing rack/device data.
            naming_pattern: Optional regex pattern for device naming validation.
        """
        self.cache = cache
        self.naming_pattern = naming_pattern
        self._naming_regex = re.compile(naming_pattern) if naming_pattern else None

    def validate_row(self, row: CSVRow) -> ValidationResult:
        """
        Run all validation checks on a single row.
        
        Args:
            row: CSVRow to validate.
            
        Returns:
            ValidationResult with all issues found.
        """
        result = ValidationResult(row=row)
        
        # Check 1: Required fields
        self._check_required_fields(row, result)
        
        # If missing required data, can't continue with other checks
        if result.status == ValidationStatus.INVALID:
            result.classification = RowClassification.INVALID
            return result
        
        # Check 2: Rack exists
        rack = self._check_rack_exists(row, result)
        
        # If rack not found, can't check RU position
        if rack is None:
            result.classification = RowClassification.REVIEW_REQUIRED
            return result
        
        # Check 3: RU position in valid range
        self._check_ru_in_range(row, rack.u_height, result)
        
        # Check 4: RU position available / collision detection
        existing_device = self._check_ru_available(row, rack.id, result)
        
        # Check 5: Device already exists (by name)
        self._check_device_exists(row, rack.id, result)
        
        # Check 6: Naming convention (optional)
        if self._naming_regex:
            self._check_naming_convention(row, result)
        
        # Determine classification based on results
        result.classification = self._classify_result(row, result, existing_device)
        
        return result

    def validate_all(self, rows: list[CSVRow]) -> list[ValidationResult]:
        """
        Validate all rows and return results.
        
        Also checks for internal CSV collisions (duplicate rack+RU within CSV).
        """
        results = []
        
        # First pass: check for duplicates within CSV
        csv_positions: dict[str, list[int]] = {}  # "rack:ru" -> list of row numbers
        for row in rows:
            if row.rack and row.ru_position is not None:
                key = f"{row.rack.lower()}:{row.ru_position}"
                if key not in csv_positions:
                    csv_positions[key] = []
                csv_positions[key].append(row.row_number)
        
        # Find duplicates
        csv_duplicates = {k: v for k, v in csv_positions.items() if len(v) > 1}
        
        # Second pass: validate each row
        for row in rows:
            result = self.validate_row(row)
            
            # Add CSV-internal collision warning if applicable
            if row.rack and row.ru_position is not None:
                key = f"{row.rack.lower()}:{row.ru_position}"
                if key in csv_duplicates:
                    other_rows = [r for r in csv_duplicates[key] if r != row.row_number]
                    result.add_issue(
                        code="CSV_COLLISION",
                        message=f"Same rack/RU position as row(s): {', '.join(map(str, other_rows))}",
                        status=ValidationStatus.FAIL,
                    )
                    if result.classification != RowClassification.INVALID:
                        result.classification = RowClassification.REVIEW_REQUIRED
            
            results.append(result)
        
        return results

    def _check_required_fields(self, row: CSVRow, result: ValidationResult):
        """Check that required fields are present."""
        missing = []
        
        if not row.rack:
            missing.append("rack")
        if row.ru_position is None:
            missing.append("ru_position")
        if row.ru_height is None:
            missing.append("ru_height")
        
        if missing:
            result.add_issue(
                code="MISSING_REQUIRED",
                message=f"Missing required field(s): {', '.join(missing)}",
                status=ValidationStatus.INVALID,
            )
        
        # Check NetBox-required fields (warn, don't fail - data can still be validated)
        netbox_required_missing = []
        if not row.device_role:
            netbox_required_missing.append("device_role")
        
        if netbox_required_missing:
            result.add_issue(
                code="NETBOX_REQUIRED_MISSING",
                message=f"NetBox import requires: {', '.join(netbox_required_missing)}",
                status=ValidationStatus.WARN,
                evidence={"missing_fields": netbox_required_missing},
            )

    def _check_rack_exists(self, row: CSVRow, result: ValidationResult):
        """Check that rack exists in NetBox. Returns rack if found."""
        rack = self.cache.get_rack(row.rack)
        
        if rack is None:
            result.add_issue(
                code="RACK_NOT_FOUND",
                message=f"Rack '{row.rack}' not found in NetBox",
                status=ValidationStatus.FAIL,
                evidence={"rack": row.rack, "site": self.cache.site_name},
            )
            return None
        
        return rack

    def _check_ru_in_range(self, row: CSVRow, rack_height: int, result: ValidationResult):
        """Check that RU position is within rack bounds."""
        if row.ru_position is None or row.ru_height is None:
            return
        
        # Position is lowest RU, device extends upward
        top_ru = row.ru_position + row.ru_height - 1
        
        if row.ru_position < 1:
            result.add_issue(
                code="RU_OUT_OF_RANGE",
                message=f"RU position {row.ru_position} is below rack (min: 1)",
                status=ValidationStatus.FAIL,
                evidence={"ru_position": row.ru_position, "min_ru": 1},
            )
        elif top_ru > rack_height:
            result.add_issue(
                code="RU_OUT_OF_RANGE",
                message=f"Device extends to RU {top_ru}, exceeds rack height ({rack_height}U)",
                status=ValidationStatus.FAIL,
                evidence={"ru_position": row.ru_position, "ru_height": row.ru_height, "top_ru": top_ru, "rack_height": rack_height},
            )

    def _check_ru_available(
        self, row: CSVRow, rack_id: int, result: ValidationResult
    ) -> Optional[CachedDevice]:
        """
        Check that RU position is available, considering face orientation.
        
        Returns the existing device if one occupies this position.
        
        Face conflict rules:
        - Full-depth (None) conflicts with any device at that RU
        - Front-only conflicts with front or full-depth devices
        - Rear-only conflicts with rear or full-depth devices
        - Front and rear can coexist at same RU if neither is full-depth
        """
        if row.ru_position is None or row.ru_height is None:
            return None
        
        # Check each RU the new device would occupy (face-aware)
        conflicting_devices: dict[int, CachedDevice] = {}  # device_id -> device
        
        for ru in range(row.ru_position, row.ru_position + row.ru_height):
            existing = self.cache.find_device_at_ru(rack_id, ru, row.face)
            if existing:
                conflicting_devices[existing.id] = existing
        
        if conflicting_devices:
            devices = list(conflicting_devices.values())
            device_names = [d.name or f"Device #{d.id}" for d in devices]
            result.existing_device = devices[0].name  # Primary conflict
            
            # Build detailed evidence with make/model and face info
            conflicts_evidence = []
            for d in devices:
                conflicts_evidence.append({
                    "device_id": d.id,
                    "device_name": d.name,
                    "ru_start": d.position,
                    "ru_end": d.position + d.u_height - 1 if d.position else None,
                    "device_type": d.device_type,
                    "manufacturer": d.manufacturer,
                    "face": d.face or "full-depth",
                })
            
            csv_face = row.face or "full-depth"
            evidence = {
                "rack": row.rack,
                "csv_make": row.make,
                "csv_model": row.model,
                "csv_hostname": row.hostname,
                "csv_face": csv_face,
                "requested_ru_start": row.ru_position,
                "requested_ru_end": row.ru_position + row.ru_height - 1,
                "conflicts": conflicts_evidence,
            }
            
            if len(devices) == 1:
                device = devices[0]
                end_ru = device.position + device.u_height - 1 if device.position else "?"
                device_face = device.face.title() if device.face else "Full"
                
                # Build detailed message including make/model and face
                netbox_info = f"'{device.name or 'unnamed'}'"
                if device.manufacturer or device.device_type:
                    netbox_info += f" ({device.manufacturer or '?'} {device.device_type or '?'})"
                netbox_info += f" [{device_face}]"
                
                result.add_issue(
                    code="RU_COLLISION",
                    message=f"Position occupied by {netbox_info} (RU {device.position}-{end_ru})",
                    status=ValidationStatus.WARN,
                    evidence=evidence,
                )
                
                # Check for make/model mismatch
                self._check_make_model_mismatch(row, device, result)
            else:
                result.add_issue(
                    code="RU_COLLISION",
                    message=f"Position conflicts with {len(devices)} devices: {', '.join(device_names)}",
                    status=ValidationStatus.WARN,
                    evidence=evidence,
                )
            
            return devices[0]
        
        return None

    def _check_device_exists(self, row: CSVRow, rack_id: int, result: ValidationResult):
        """Check if device with same name already exists."""
        if not row.hostname:
            return
        
        existing = self.cache.find_device_by_name(row.hostname, rack_id)
        
        if existing:
            # Device exists - check if it's at the same position
            if existing.position == row.ru_position:
                result.add_issue(
                    code="DEVICE_EXISTS_SAME_POSITION",
                    message=f"Device '{row.hostname}' already exists at this position",
                    status=ValidationStatus.PASS,  # This is actually good - no action needed
                )
            else:
                result.add_issue(
                    code="DEVICE_EXISTS_DIFFERENT_POSITION",
                    message=f"Device '{row.hostname}' exists but at RU {existing.position}",
                    status=ValidationStatus.WARN,
                )

    def _check_make_model_mismatch(
        self,
        row: CSVRow,
        netbox_device: CachedDevice,
        result: ValidationResult,
    ):
        """Check if CSV make/model matches NetBox device type."""
        if not row.make and not row.model:
            return  # Nothing to compare
        
        mismatches = []
        matches = []
        
        # Compare manufacturer (make)
        if row.make and netbox_device.manufacturer:
            csv_make = row.make.lower().strip()
            nb_make = netbox_device.manufacturer.lower().strip()
            if csv_make != nb_make:
                mismatches.append(f"Make: CSV='{row.make}' vs NetBox='{netbox_device.manufacturer}'")
            else:
                matches.append(f"Make: '{row.make}'")
        
        # Compare model
        if row.model and netbox_device.device_type:
            csv_model = row.model.lower().strip()
            nb_model = netbox_device.device_type.lower().strip()
            if csv_model != nb_model:
                mismatches.append(f"Model: CSV='{row.model}' vs NetBox='{netbox_device.device_type}'")
            else:
                matches.append(f"Model: '{row.model}'")
        
        if mismatches:
            result.add_issue(
                code="MAKE_MODEL_MISMATCH",
                message=f"Data differs from NetBox: {'; '.join(mismatches)}",
                status=ValidationStatus.WARN,
                evidence={
                    "csv_make": row.make,
                    "csv_model": row.model,
                    "netbox_manufacturer": netbox_device.manufacturer,
                    "netbox_device_type": netbox_device.device_type,
                },
            )
        elif matches:
            # All provided fields match - confirm this
            result.add_issue(
                code="MAKE_MODEL_MATCH",
                message=f"Data matches NetBox: {'; '.join(matches)}",
                status=ValidationStatus.PASS,
                evidence={
                    "csv_make": row.make,
                    "csv_model": row.model,
                    "netbox_manufacturer": netbox_device.manufacturer,
                    "netbox_device_type": netbox_device.device_type,
                },
            )

    def _check_naming_convention(self, row: CSVRow, result: ValidationResult):
        """Check if hostname matches naming convention."""
        if not row.hostname:
            result.add_issue(
                code="NAMING_NO_HOSTNAME",
                message="No hostname to validate against naming convention",
                status=ValidationStatus.WARN,
            )
            return
        
        if not self._naming_regex.match(row.hostname):
            result.add_issue(
                code="NAMING_MISMATCH",
                message=f"Hostname '{row.hostname}' does not match naming pattern",
                status=ValidationStatus.WARN,
            )

    def _classify_result(
        self,
        row: CSVRow,
        result: ValidationResult,
        existing_device: Optional[CachedDevice],
    ) -> RowClassification:
        """Determine final classification based on validation results."""
        
        # Check for fatal issues
        has_invalid = any(i.status == ValidationStatus.INVALID for i in result.issues)
        has_fail = any(i.status == ValidationStatus.FAIL for i in result.issues)
        
        if has_invalid:
            return RowClassification.INVALID
        
        if has_fail:
            return RowClassification.REVIEW_REQUIRED
        
        # Check if device already exists at correct position
        has_exists_same = any(
            i.code == "DEVICE_EXISTS_SAME_POSITION" for i in result.issues
        )
        if has_exists_same:
            return RowClassification.NO_ACTION
        
        # Check for position conflicts
        has_collision = any(i.code == "RU_COLLISION" for i in result.issues)
        has_exists_different = any(
            i.code == "DEVICE_EXISTS_DIFFERENT_POSITION" for i in result.issues
        )
        
        if has_collision or has_exists_different:
            return RowClassification.REVIEW_REQUIRED
        
        # No issues or only warnings - safe to update
        return RowClassification.NETBOX_UPDATE


def validate_csv_rows(
    rows: list[CSVRow],
    cache: NetBoxCache,
    naming_pattern: Optional[str] = None,
) -> list[ValidationResult]:
    """
    Convenience function to validate CSV rows.
    
    Args:
        rows: List of CSVRow objects to validate.
        cache: NetBoxCache with rack/device data.
        naming_pattern: Optional naming convention regex.
        
    Returns:
        List of ValidationResult objects.
    """
    validator = Validator(cache, naming_pattern)
    return validator.validate_all(rows)
