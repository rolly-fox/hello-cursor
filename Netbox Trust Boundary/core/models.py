"""
Data models for NetBox Trust Boundary.

Defines data classes for:
- CSV row representation
- Validation results
- NetBox cache entries
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Severity(Enum):
    """Severity levels for validation findings."""
    PASS = "PASS"      # Clean, no issues
    WARN = "WARN"      # Not a blocker, but review recommended
    FAIL = "FAIL"      # Hard blocker, cannot proceed
    INVALID = "INVALID"  # Data issue, cannot process


# Keep ValidationStatus as alias for backward compatibility
ValidationStatus = Severity


class FindingType(Enum):
    """Normalized finding type codes."""
    # PASS findings
    OK = "OK"
    DEVICE_EXISTS_SAME_POSITION = "DEVICE_EXISTS_SAME_POSITION"
    
    # FAIL findings (hard blockers)
    RACK_NOT_FOUND = "RACK_NOT_FOUND"
    RU_OUT_OF_RANGE = "RU_OUT_OF_RANGE"
    RU_COLLISION = "RU_COLLISION"
    CSV_COLLISION = "CSV_COLLISION"
    MISSING_REQUIRED = "MISSING_REQUIRED"
    
    # WARN findings (review recommended)
    DEVICE_NOT_FOUND = "DEVICE_NOT_FOUND"
    DEVICE_EXISTS_DIFFERENT_POSITION = "DEVICE_EXISTS_DIFFERENT_POSITION"
    MAKE_MODEL_MISMATCH = "MAKE_MODEL_MISMATCH"
    MAKE_MODEL_MATCH = "MAKE_MODEL_MATCH"  # Confirmation
    NAMING_MISMATCH = "NAMING_MISMATCH"
    NAMING_NO_HOSTNAME = "NAMING_NO_HOSTNAME"
    NETBOX_REQUIRED_MISSING = "NETBOX_REQUIRED_MISSING"  # Missing fields for import


# Mapping of finding types to recommendations
FINDING_RECOMMENDATIONS = {
    FindingType.OK: "No action required.",
    FindingType.DEVICE_EXISTS_SAME_POSITION: "Device already exists at this position. No action needed.",
    FindingType.RACK_NOT_FOUND: "Verify rack name or create rack in NetBox before importing.",
    FindingType.RU_OUT_OF_RANGE: "Adjust RU position to fit within rack height.",
    FindingType.RU_COLLISION: "Choose a different RU position or relocate conflicting device(s).",
    FindingType.CSV_COLLISION: "Remove duplicate row from CSV or resolve position conflict.",
    FindingType.MISSING_REQUIRED: "Add missing required field(s) to CSV row.",
    FindingType.DEVICE_NOT_FOUND: "Device will be created as new. Verify this is intended.",
    FindingType.DEVICE_EXISTS_DIFFERENT_POSITION: "Device exists at different position. Verify which is correct.",
    FindingType.MAKE_MODEL_MISMATCH: "CSV make/model differs from NetBox. Check for typos or update if needed.",
    FindingType.MAKE_MODEL_MATCH: "Make/model verified against NetBox. Data is consistent.",
    FindingType.NAMING_MISMATCH: "Hostname does not match naming convention. Review and correct if needed.",
    FindingType.NAMING_NO_HOSTNAME: "Consider adding a hostname for better identification.",
    FindingType.NETBOX_REQUIRED_MISSING: "Add device_role to CSV. NetBox API requires this field for import.",
}


class RowClassification(Enum):
    """Classification of what action is needed for a row."""
    NO_ACTION = "NO_ACTION"  # Already correct in NetBox
    NETBOX_UPDATE = "NETBOX_UPDATE"  # Safe to import
    REVIEW_REQUIRED = "REVIEW_REQUIRED"  # Conflict or ambiguity
    INVALID = "INVALID"  # Cannot process, data issue


class ImportReadiness(Enum):
    """Whether the CSV row has all required fields for NetBox bulk import."""
    READY = "READY"          # All required fields present - can be imported
    INCOMPLETE = "INCOMPLETE"  # Missing required fields - needs data added


# Required fields for NetBox device bulk import
NETBOX_IMPORT_REQUIRED_FIELDS = [
    "hostname",      # device name
    "device_role",   # role (Server, Switch, etc.)
    "site",          # site name (or use config default)
    "rack",          # rack name
    "ru_position",   # position
    "ru_height",     # u_height from device_type
    "make",          # manufacturer
    "model",         # device_type model
]


@dataclass
class CSVRow:
    """Represents a single row from the input CSV."""
    row_number: int
    rack: str
    ru_position: Optional[int]
    ru_height: Optional[int]
    make: Optional[str] = None          # manufacturer.name
    model: Optional[str] = None         # device_type.model
    hostname: Optional[str] = None      # device name
    face: Optional[str] = None          # "front", "rear", or None (full-depth)
    device_role: Optional[str] = None   # device_role.name (e.g., "Server", "Switch")
    status: Optional[str] = None        # operational status (e.g., "active", "planned", "staged")
    site: Optional[str] = None          # site.name (optional - defaults to config if not provided)
    raw_data: dict = field(default_factory=dict)

    @property
    def device_identifier(self) -> str:
        """Returns the best available identifier for this device."""
        if self.hostname:
            return self.hostname
        if self.make and self.model:
            return f"{self.make} {self.model}"
        return f"Row {self.row_number}"


@dataclass
class ValidationIssue:
    """A single validation issue found during checks."""
    code: str
    message: str
    status: Severity
    finding_type: Optional[FindingType] = None
    evidence: Optional[dict] = None
    
    @property
    def recommendation(self) -> str:
        """Get recommendation for this finding."""
        if self.finding_type:
            return FINDING_RECOMMENDATIONS.get(self.finding_type, "Review and resolve manually.")
        return "Review and resolve manually."


@dataclass
class ValidationResult:
    """Complete validation result for a single CSV row."""
    row: CSVRow
    issues: list[ValidationIssue] = field(default_factory=list)
    classification: RowClassification = RowClassification.INVALID
    existing_device: Optional[str] = None  # Name of device currently at this position
    _import_readiness: Optional[ImportReadiness] = None  # Cached import readiness

    @property
    def import_readiness(self) -> ImportReadiness:
        """Check if row has all required fields for NetBox bulk import."""
        if self._import_readiness is not None:
            return self._import_readiness
        
        row = self.row
        missing = []
        
        # Check each required field
        if not row.hostname:
            missing.append("device_name")
        if not row.device_role:
            missing.append("device_role")
        if not row.rack:
            missing.append("rack")
        if row.ru_position is None:
            missing.append("ru_position")
        if row.ru_height is None:
            missing.append("ru_height")
        if not row.make:
            missing.append("manufacturer")
        if not row.model:
            missing.append("model")
        # site is optional - defaults to config
        
        return ImportReadiness.READY if not missing else ImportReadiness.INCOMPLETE
    
    @property
    def missing_import_fields(self) -> list[str]:
        """Returns list of fields missing for bulk import."""
        row = self.row
        missing = []
        if not row.hostname:
            missing.append("device_name")
        if not row.device_role:
            missing.append("device_role")
        if not row.rack:
            missing.append("rack")
        if row.ru_position is None:
            missing.append("ru_position")
        if row.ru_height is None:
            missing.append("ru_height")
        if not row.make:
            missing.append("manufacturer")
        if not row.model:
            missing.append("model")
        return missing

    @property
    def status(self) -> ValidationStatus:
        """Returns the worst status among all issues."""
        if not self.issues:
            return ValidationStatus.PASS
        
        # Priority: INVALID > FAIL > WARN > PASS
        if any(i.status == ValidationStatus.INVALID for i in self.issues):
            return ValidationStatus.INVALID
        if any(i.status == ValidationStatus.FAIL for i in self.issues):
            return ValidationStatus.FAIL
        if any(i.status == ValidationStatus.WARN for i in self.issues):
            return ValidationStatus.WARN
        return ValidationStatus.PASS

    def add_issue(
        self,
        code: str,
        message: str,
        status: Severity,
        finding_type: Optional[FindingType] = None,
        evidence: Optional[dict] = None,
    ):
        """Add a validation issue."""
        # Try to auto-detect finding_type from code if not provided
        if finding_type is None:
            try:
                finding_type = FindingType[code]
            except KeyError:
                finding_type = None
        
        self.issues.append(ValidationIssue(
            code=code,
            message=message,
            status=status,
            finding_type=finding_type,
            evidence=evidence,
        ))


# NetBox Cache Models

@dataclass
class CachedRack:
    """Cached rack data from NetBox."""
    id: int
    name: str
    site_id: int
    site_name: str
    location_id: Optional[int] = None
    location_name: Optional[str] = None
    u_height: int = 42  # Default rack height


@dataclass
class CachedDevice:
    """Cached device data from NetBox."""
    id: int
    name: str
    rack_id: Optional[int]
    rack_name: Optional[str]
    position: Optional[int]  # Lowest RU occupied
    u_height: int = 1
    device_type: Optional[str] = None
    manufacturer: Optional[str] = None
    face: Optional[str] = None  # "front", "rear", or None (full-depth)

    @property
    def ru_range(self) -> tuple[int, int]:
        """Returns (start_ru, end_ru) occupied by this device."""
        if self.position is None:
            return (0, 0)
        return (self.position, self.position + self.u_height - 1)

    def occupies_ru(self, ru: int) -> bool:
        """Check if this device occupies the given RU."""
        if self.position is None:
            return False
        start, end = self.ru_range
        return start <= ru <= end


@dataclass
class NetBoxCache:
    """In-memory cache of NetBox data for a site."""
    site_id: Optional[int] = None
    site_name: Optional[str] = None
    racks: dict[str, CachedRack] = field(default_factory=dict)  # Keyed by rack name
    devices: list[CachedDevice] = field(default_factory=list)
    devices_by_rack: dict[int, list[CachedDevice]] = field(default_factory=dict)  # Keyed by rack ID

    def get_rack(self, rack_name: str) -> Optional[CachedRack]:
        """Look up a rack by name (case-insensitive)."""
        return self.racks.get(rack_name.lower())

    def get_devices_in_rack(self, rack_id: int) -> list[CachedDevice]:
        """Get all devices in a specific rack."""
        return self.devices_by_rack.get(rack_id, [])

    def find_device_at_ru(self, rack_id: int, ru: int, face: Optional[str] = None) -> Optional[CachedDevice]:
        """
        Find device occupying a specific RU in a rack, optionally filtering by face.
        
        Face conflict logic:
        - If face is None (full-depth), conflicts with any device at that RU
        - If face is specified, conflicts only with devices on same face or full-depth
        """
        for device in self.get_devices_in_rack(rack_id):
            if device.occupies_ru(ru):
                if face is None:
                    # Full-depth device conflicts with anything at this RU
                    return device
                elif device.face is None:
                    # Existing full-depth device conflicts with any face
                    return device
                elif device.face == face:
                    # Same face = conflict
                    return device
                # Different faces = no conflict, continue checking
        return None
    
    def find_devices_at_ru(self, rack_id: int, ru: int) -> list[CachedDevice]:
        """Find ALL devices occupying a specific RU in a rack (ignoring face)."""
        return [d for d in self.get_devices_in_rack(rack_id) if d.occupies_ru(ru)]

    def find_device_by_name(self, name: str, rack_id: Optional[int] = None) -> Optional[CachedDevice]:
        """Find device by name, optionally scoped to a rack."""
        if not name:
            return None
        name_lower = name.lower()
        for device in self.devices:
            if device.name and device.name.lower() == name_lower:
                if rack_id is None or device.rack_id == rack_id:
                    return device
        return None

    def add_rack(self, rack: CachedRack):
        """Add a rack to the cache."""
        if rack.name:
            self.racks[rack.name.lower()] = rack

    def add_device(self, device: CachedDevice):
        """Add a device to the cache."""
        self.devices.append(device)
        if device.rack_id:
            if device.rack_id not in self.devices_by_rack:
                self.devices_by_rack[device.rack_id] = []
            self.devices_by_rack[device.rack_id].append(device)

    def clear(self):
        """Clear all cached data."""
        self.site_id = None
        self.site_name = None
        self.racks.clear()
        self.devices.clear()
        self.devices_by_rack.clear()
