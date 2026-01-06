# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.4.0] - 2026-01-05

### Added - UI Polish & Usability
- **App Logo**: Custom logo in window title bar and taskbar
- **About Dialog** (Help → About): Shows version, description, and credits
- **Activity Log Panel**: Timestamped log of all operations (load, connect, validate)
- **Row Detail Panel**: Click any row to see all issues with recommendations
- **Horizontal Scrollbar**: Table now scrolls horizontally for all columns
- **Clear Data** (File → Clear Data): Reset loaded CSV and results
- **File Type Validation**: Rejects non-CSV files with clear error message

### Changed
- Finding Types column now shows ALL codes (not just first + count)
- Improved tooltips throughout the app
- Brighter warning color (#f0c000) for better visibility
- Detail panel has labeled border "Row Details" and vertical scrollbar

### Fixed
- Windows taskbar now shows app logo (not Python icon)
- Legend tooltips now work before loading CSV

## [1.3.0] - 2026-01-05

### Added - Dual-Status Validation System
This release introduces a clear separation between **Position Availability** and **Import Readiness**:

- **Position Status**: Is there physical space in the rack?
  - ✓ Available - RU position is free
  - ⚠ Review - Potential conflict, needs review
  - ✗ Blocked - Position occupied or rack not found

- **Import Status**: Does the CSV have all required fields for bulk import?
  - ✓ Ready - All NetBox-required fields present
  - ⚠ Incomplete - Missing fields (device_role, device_name, etc.)

### New Features
- **Quick Filters** in results table:
  - "🚀 Ready to Import" - Shows only rows that are Available + Ready
  - "📋 Needs Data" - Shows Available positions that need more CSV data
- **Enhanced Export** with filter options for bulk import workflows
- **Hover tooltips** on incomplete fields showing what's missing
- Missing fields shown in orange `(missing)` for easy identification

### Changed
- Redesigned results table with dual-status columns
- Updated legend to explain both Position and Import statuses
- Export CSV now includes `position_status`, `import_status`, `missing_fields` columns

## [1.2.0] - 2026-01-05

### Added - Complete NetBox Import Validation
- **device_role**: CSV column for device role (Server, Switch, PDU, etc.) - REQUIRED for NetBox import
- **status**: CSV column for operational status (active, planned, staged, failed, etc.)
- **site**: CSV column for site name (optional - defaults to configured site)
- New columns in results table: Site, Role, Status, Make, Model
- Validation warning when `device_role` is missing (NetBox API requirement)
- Improved dropdown styling with dark theme and colored items

### Changed
- Results table now shows all NetBox-required fields for import readiness
- Missing required fields highlighted in red in the table

### Test Data
- Added `tests/audit_er100-241_complete.csv` with all NetBox fields

## [1.1.0] - 2026-01-05

### Added
- **Face orientation support**: CSV can now include "face" column (front/rear/full)
- **Face-aware collision detection**: Front and rear devices can coexist at same RU
- **Severity legend** in results table explaining PASS/WARN/FAIL/INVALID
- **Face column** displayed in results table

### Changed
- Renamed "Hostname" to "Device Name" for clarity
- Collision messages now include device face orientation (e.g., "[Front]")
- Evidence includes face information for both CSV and NetBox devices

### Test Data
- Added `tests/audit_er100-241_with_face.csv` with face orientation examples

## [1.0.0] - 2026-01-05

### Added
- Initial release
- PySide6 desktop application
- NetBox API client with caching
- CSV loading with flexible column mapping
- Validation engine with collision detection
- Results table with filtering by status and classification
- Export to CSV and JSON
- Settings dialog for NetBox connection
- SSL certificate verification toggle for internal CAs
- Copyable error messages for troubleshooting

### Validation Rules
- Required field checking
- Rack existence verification
- RU position range validation
- RU collision detection with existing devices
- Duplicate detection within CSV
- Device existence checking

### Supported NetBox Versions
- NetBox 3.4.x (tested with 3.4.5)
