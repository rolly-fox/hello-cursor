"""
CSV loader with column validation and normalization.

Parses input CSVs into CSVRow objects, handling missing data gracefully.
"""

import csv
import re
from pathlib import Path
from typing import Optional

from .models import CSVRow


class CSVLoadError(Exception):
    """Exception raised for CSV loading errors."""
    pass


# Default column mappings (case-insensitive)
DEFAULT_COLUMN_MAPPING = {
    "rack": ["rack", "rack_location", "rack_name", "rack_id"],
    "ru_position": ["ru_position", "ru", "position", "ru_pos", "u_position"],
    "ru_height": ["ru_height", "height", "u_height", "device_height", "size"],
    "make": ["make", "manufacturer", "mfg", "vendor"],
    "model": ["model", "model_number", "device_type", "type"],
    "hostname": ["hostname", "name", "device_name", "host", "friendly_name"],
    "face": ["face", "orientation", "side", "rack_face"],
    "device_role": ["device_role", "role", "device_type_role", "function"],
    "status": ["status", "device_status", "state", "operational_status"],
    "site": ["site", "site_name", "location_site", "facility"],
}


class CSVLoader:
    """Loads and parses CSV files into CSVRow objects."""

    def __init__(self, column_mapping: Optional[dict] = None):
        """
        Initialize loader with optional custom column mapping.
        
        Args:
            column_mapping: Dict mapping field names to list of possible column headers.
        """
        self.column_mapping = column_mapping or DEFAULT_COLUMN_MAPPING
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def _find_column(self, headers: list[str], field: str) -> Optional[int]:
        """Find column index for a field using mapping."""
        possible_names = self.column_mapping.get(field, [field])
        headers_lower = [h.lower().strip() for h in headers]
        
        for name in possible_names:
            if name.lower() in headers_lower:
                return headers_lower.index(name.lower())
        return None

    def _parse_ru_value(self, value: str) -> Optional[int]:
        """Parse RU value from string, handling various formats."""
        if not value:
            return None
        
        value = value.strip()
        
        # Handle "RU 22", "RU22", "U22", "22U" formats
        match = re.search(r'(\d+)', value)
        if match:
            return int(match.group(1))
        
        return None

    def _normalize_string(self, value: Optional[str]) -> Optional[str]:
        """Normalize string value (strip whitespace, handle empty)."""
        if value is None:
            return None
        value = value.strip()
        return value if value else None

    def load(self, file_path: str | Path) -> list[CSVRow]:
        """
        Load CSV file and return list of CSVRow objects.
        
        Args:
            file_path: Path to CSV file.
            
        Returns:
            List of CSVRow objects.
            
        Raises:
            CSVLoadError: If file cannot be read or has no valid headers.
        """
        self.errors = []
        self.warnings = []
        rows = []
        
        file_path = Path(file_path)
        
        if not file_path.exists():
            raise CSVLoadError(f"File not found: {file_path}")
        
        if not file_path.suffix.lower() == ".csv":
            raise CSVLoadError(f"Not a CSV file: {file_path}")

        try:
            with open(file_path, "r", encoding="utf-8-sig") as f:
                # Detect delimiter
                sample = f.read(4096)
                f.seek(0)
                
                try:
                    dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
                except csv.Error:
                    dialect = csv.excel  # Default to comma-separated
                
                reader = csv.DictReader(f, dialect=dialect)
                
                if not reader.fieldnames:
                    raise CSVLoadError("CSV file has no headers")
                
                headers = list(reader.fieldnames)
                
                # Build column index map
                column_indices = {}
                for field in ["rack", "ru_position", "ru_height", "make", "model", "hostname", "face", "device_role", "status", "site"]:
                    idx = self._find_column(headers, field)
                    column_indices[field] = idx
                
                # Check required columns
                missing_required = []
                for required in ["rack", "ru_position", "ru_height"]:
                    if column_indices[required] is None:
                        missing_required.append(required)
                
                if missing_required:
                    raise CSVLoadError(
                        f"Missing required columns: {', '.join(missing_required)}. "
                        f"Found columns: {', '.join(headers)}"
                    )

                # Parse rows
                for row_num, row_data in enumerate(reader, start=2):  # Start at 2 (header is row 1)
                    try:
                        csv_row = self._parse_row(row_num, row_data, headers, column_indices)
                        rows.append(csv_row)
                    except Exception as e:
                        self.errors.append(f"Row {row_num}: {str(e)}")

        except UnicodeDecodeError:
            # Try with different encoding
            try:
                with open(file_path, "r", encoding="latin-1") as f:
                    return self._load_from_file(f, file_path)
            except Exception as e:
                raise CSVLoadError(f"Unable to read file: {e}")
        except csv.Error as e:
            raise CSVLoadError(f"CSV parsing error: {e}")

        return rows

    def _parse_row(
        self,
        row_num: int,
        row_data: dict,
        headers: list[str],
        column_indices: dict,
    ) -> CSVRow:
        """Parse a single CSV row into CSVRow object."""
        
        def get_value(field: str) -> Optional[str]:
            idx = column_indices.get(field)
            if idx is not None and idx < len(headers):
                header = headers[idx]
                return row_data.get(header)
            return None

        rack = self._normalize_string(get_value("rack"))
        ru_position = self._parse_ru_value(get_value("ru_position") or "")
        ru_height = self._parse_ru_value(get_value("ru_height") or "")
        make = self._normalize_string(get_value("make"))
        model = self._normalize_string(get_value("model"))
        hostname = self._normalize_string(get_value("hostname"))
        face = self._normalize_face(get_value("face"))
        device_role = self._normalize_string(get_value("device_role"))
        status = self._normalize_status(get_value("status"))
        site = self._normalize_string(get_value("site"))

        # Create row with raw data preserved
        return CSVRow(
            row_number=row_num,
            rack=rack or "",
            ru_position=ru_position,
            ru_height=ru_height,
            make=make,
            model=model,
            hostname=hostname,
            face=face,
            device_role=device_role,
            status=status,
            site=site,
            raw_data=dict(row_data),
        )

    def _normalize_status(self, value: Optional[str]) -> Optional[str]:
        """Normalize device status value to NetBox format."""
        if not value:
            return None
        value = value.strip().lower()
        # Map common variations to NetBox status values
        status_map = {
            "active": "active",
            "online": "active",
            "live": "active",
            "planned": "planned",
            "pending": "planned",
            "staged": "staged",
            "staging": "staged",
            "failed": "failed",
            "offline": "offline",
            "decommissioned": "decommissioning",
            "decommissioning": "decommissioning",
            "inventory": "inventory",
        }
        return status_map.get(value, value)

    def _normalize_face(self, value: Optional[str]) -> Optional[str]:
        """Normalize face/orientation value."""
        if not value:
            return None
        value = value.strip().lower()
        if value in ("front", "f", "fnt"):
            return "front"
        elif value in ("rear", "r", "back", "bck"):
            return "rear"
        elif value in ("full", "both", "full-depth"):
            return None  # Full-depth = None in NetBox
        return None

    def _load_from_file(self, f, file_path: Path) -> list[CSVRow]:
        """Internal method to load from already-opened file."""
        rows = []
        
        sample = f.read(4096)
        f.seek(0)
        
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        
        reader = csv.DictReader(f, dialect=dialect)
        
        if not reader.fieldnames:
            raise CSVLoadError("CSV file has no headers")
        
        headers = list(reader.fieldnames)
        
        column_indices = {}
        for field in ["rack", "ru_position", "ru_height", "make", "model", "hostname", "face", "device_role", "status", "site"]:
            idx = self._find_column(headers, field)
            column_indices[field] = idx
        
        missing_required = []
        for required in ["rack", "ru_position", "ru_height"]:
            if column_indices[required] is None:
                missing_required.append(required)
        
        if missing_required:
            raise CSVLoadError(
                f"Missing required columns: {', '.join(missing_required)}. "
                f"Found columns: {', '.join(headers)}"
            )

        for row_num, row_data in enumerate(reader, start=2):
            try:
                csv_row = self._parse_row(row_num, row_data, headers, column_indices)
                rows.append(csv_row)
            except Exception as e:
                self.errors.append(f"Row {row_num}: {str(e)}")

        return rows


def load_csv(file_path: str | Path) -> tuple[list[CSVRow], list[str]]:
    """
    Convenience function to load a CSV file.
    
    Returns:
        Tuple of (rows, errors).
    """
    loader = CSVLoader()
    rows = loader.load(file_path)
    return rows, loader.errors
