# NetBox Trust Boundary

A read-only validation layer that protects NetBox from unsafe or unnecessary changes.

> **"Validate first. Change once."**

## Overview

NetBox Trust Boundary is a lightweight desktop tool that sits between external data sources (AutoCAD exports, technician audits, AI-generated inventories) and your NetBox instance. It validates proposed changes before they touch NetBox, preventing data corruption, duplication, and wasted engineering effort.

**This tool does not write to NetBox.** It only answers: *"Is this data safe, necessary, and actionable?"*

## Features

- **CSV Validation** — Load device/rack data and validate against NetBox
- **Collision Detection** — Identify RU conflicts, duplicate devices, missing racks
- **Smart Classification** — Each row is tagged as:
  - `NO_ACTION` — Already correct in NetBox
  - `NETBOX_UPDATE` — Safe to import
  - `REVIEW_REQUIRED` — Conflict or ambiguity
  - `INVALID` — Data issue, cannot process
- **Caching** — Fetches and caches rack/device data for fast validation
- **Export** — Save results as CSV or JSON for downstream workflows
- **Enterprise-Ready** — Supports internal CAs and SSL certificate bypass

## Screenshots

*Coming soon*

## Installation

### Prerequisites

- Python 3.10 or higher
- Access to a NetBox 3.x instance (read-only API token)

### Setup

```bash
# Clone the repository
git clone https://github.com/rolly-fox/netbox-trust-boundary.git
cd netbox-trust-boundary

# Install dependencies
pip install -r requirements.txt

# Copy and configure settings
cp config.yaml.example config.yaml
# Edit config.yaml with your NetBox URL, API token, and site
```

### Run

```bash
python main.py
```

## Configuration

Edit `config.yaml`:

```yaml
netbox:
  url: "https://netbox.example.com"
  token: "your-api-token"
  site: "los-angeles"  # Site slug or ID
  verify_ssl: true     # Set to false for internal CAs

validation:
  naming_pattern: null  # Optional regex for device naming
```

**Environment variables** override config file:
- `NETBOX_URL`
- `NETBOX_TOKEN`
- `NETBOX_SITE`

## CSV Format

Input CSVs should contain these columns:

| Column | Required | Description |
|--------|----------|-------------|
| `rack` | Yes | Rack name (e.g., `ER100-161`) |
| `ru_position` | Yes | Lowest RU occupied (1-based) |
| `ru_height` | Yes | Device height in rack units |
| `hostname` | No | Device name/hostname |
| `make` | No | Manufacturer |
| `model` | No | Model number |

Column headers are flexible — the tool recognizes common variations (e.g., `rack_location`, `position`, `height`, `manufacturer`).

## Validation Rules

| Check | Result |
|-------|--------|
| Missing required fields | `INVALID` |
| Rack not found in NetBox | `FAIL` |
| RU position out of bounds | `FAIL` |
| RU collision with existing device | `WARN` (reports occupant) |
| Device already exists at position | `NO_ACTION` |
| Duplicate rack/RU in CSV | `FAIL` |

## Use Cases

### Technician Audit Validation
1. Technician reports devices from field audit
2. Run CSV through Trust Boundary
3. Identify what's already in NetBox vs. what needs updating
4. Avoid duplicate data entry

### AutoCAD/AI Export Validation
1. Extract rack inventory from drawings
2. Validate against NetBox before import
3. Only import clean, non-conflicting data

### Pre-Import Gate
1. Run any bulk import CSV through validation first
2. Catch errors before they corrupt NetBox
3. Generate actionable task lists for engineers

## Technology Stack

- **Python 3.10+**
- **PySide6** — Cross-platform desktop UI
- **Requests** — NetBox API client
- **PyYAML** — Configuration management

## Project Structure

```
netbox-trust-boundary/
├── main.py                 # Application entry point
├── config.yaml.example     # Configuration template
├── requirements.txt        # Python dependencies
├── core/
│   ├── models.py          # Data classes
│   ├── netbox_client.py   # API client with caching
│   ├── csv_loader.py      # CSV parsing
│   └── validators.py      # Validation engine
├── ui/
│   ├── main_window.py     # Main application window
│   ├── results_table.py   # Results display
│   ├── config_dialog.py   # Settings dialog
│   └── export.py          # Export functionality
└── tests/
    ├── test_validators.py # Unit tests
    └── sample_data.csv    # Test data
```

## Roadmap

- [ ] Improved progress feedback during cache refresh
- [ ] Dark mode styling for all dialogs
- [ ] Naming convention validation (regex patterns)
- [ ] Interface/port validation
- [ ] Multi-site support
- [ ] CLI mode for scripted workflows

## Contributing

Contributions are welcome. Please open an issue to discuss proposed changes before submitting a pull request.

## License

MIT License — see [LICENSE](LICENSE) for details.

## Acknowledgments

Built for broadcast infrastructure engineers managing large-scale facility deployments with NetBox.
