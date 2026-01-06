"""
Export functionality for validation results.
"""

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Union, Optional

from core.models import ValidationResult, RowClassification, ImportReadiness, Severity


def export_results(
    results: list[ValidationResult],
    file_path: Union[str, Path],
    classification_filter: Optional[RowClassification] = None,
    export_filter: Optional[str] = None,  # "ready_to_import", "needs_data", "available", "blocked"
    site_name: str = "",
    source_file: str = "",
) -> None:
    """
    Export validation results to CSV, JSON, or HTML.
    
    Args:
        results: List of ValidationResult objects.
        file_path: Output file path. Format determined by extension.
        classification_filter: Optional filter to export only specific classification.
        export_filter: Quick filter - "ready_to_import", "needs_data", "available", "blocked"
        site_name: NetBox site name for reports.
        source_file: Source CSV filename for reports.
    """
    file_path = Path(file_path)
    suffix = file_path.suffix.lower()
    
    # Apply quick filter
    if export_filter == "ready_to_import":
        results = [r for r in results 
                   if r.status == Severity.PASS and r.import_readiness == ImportReadiness.READY]
    elif export_filter == "needs_data":
        results = [r for r in results 
                   if r.status == Severity.PASS and r.import_readiness == ImportReadiness.INCOMPLETE]
    elif export_filter == "available":
        results = [r for r in results if r.status == Severity.PASS]
    elif export_filter == "blocked":
        results = [r for r in results if r.status in (Severity.FAIL, Severity.INVALID)]
    
    # Apply classification filter if specified
    if classification_filter is not None:
        results = [r for r in results if r.classification == classification_filter]
    
    if suffix == ".csv":
        _export_csv(results, file_path)
    elif suffix == ".json":
        _export_json(results, file_path)
    elif suffix in (".html", ".htm"):
        _export_html(results, file_path, site_name, source_file)
    else:
        # Default to CSV
        _export_csv(results, file_path)


def _export_csv(results: list[ValidationResult], file_path: Path) -> None:
    """Export results to CSV format - ready for NetBox bulk import."""
    
    fieldnames = [
        "row_number",
        "position_status",
        "import_status",
        "site",
        "rack",
        "ru_position",
        "ru_height",
        "face",
        "device_name",
        "device_role",
        "status",
        "manufacturer",
        "model",
        "finding_type",
        "finding_message",
        "missing_fields",
        "recommendation",
    ]
    
    with open(file_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        
        for result in results:
            row = result.row
            primary_issue = result.issues[0] if result.issues else None
            
            # Position status
            if result.status == Severity.PASS:
                pos_status = "Available"
            elif result.status == Severity.WARN:
                pos_status = "Review"
            else:
                pos_status = "Blocked"
            
            writer.writerow({
                "row_number": row.row_number,
                "position_status": pos_status,
                "import_status": result.import_readiness.value,
                "site": row.site or "",
                "rack": row.rack,
                "ru_position": row.ru_position,
                "ru_height": row.ru_height,
                "face": row.face or "full",
                "device_name": row.hostname or "",
                "device_role": row.device_role or "",
                "status": row.status or "active",
                "manufacturer": row.make or "",
                "model": row.model or "",
                "finding_type": primary_issue.code if primary_issue else "OK",
                "finding_message": primary_issue.message if primary_issue else "",
                "missing_fields": ", ".join(result.missing_import_fields) if result.missing_import_fields else "",
                "recommendation": primary_issue.recommendation if primary_issue else "",
            })


def _export_json(results: list[ValidationResult], file_path: Path) -> None:
    """Export results to JSON format."""
    
    output = {
        "generated_at": datetime.now().isoformat(),
        "summary": {
            "total_rows": len(results),
            "pass_count": sum(1 for r in results if r.status.value == "PASS"),
            "warn_count": sum(1 for r in results if r.status.value == "WARN"),
            "fail_count": sum(1 for r in results if r.status.value == "FAIL"),
            "invalid_count": sum(1 for r in results if r.status.value == "INVALID"),
        },
        "classifications": {
            "no_action": sum(1 for r in results if r.classification.value == "NO_ACTION"),
            "netbox_update": sum(1 for r in results if r.classification.value == "NETBOX_UPDATE"),
            "review_required": sum(1 for r in results if r.classification.value == "REVIEW_REQUIRED"),
            "invalid": sum(1 for r in results if r.classification.value == "INVALID"),
        },
        "results": [],
    }
    
    for result in results:
        row = result.row
        output["results"].append({
            "row_number": row.row_number,
            "severity": result.status.value,
            "classification": result.classification.value,
            "data": {
                "rack": row.rack,
                "ru_position": row.ru_position,
                "ru_height": row.ru_height,
                "hostname": row.hostname,
                "make": row.make,
                "model": row.model,
            },
            "existing_device": result.existing_device,
            "issues": [
                {
                    "code": issue.code,
                    "message": issue.message,
                    "severity": issue.status.value,
                    "recommendation": issue.recommendation,
                }
                for issue in result.issues
            ],
        })
    
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)


def _export_html(
    results: list[ValidationResult],
    file_path: Path,
    site_name: str = "",
    source_file: str = "",
) -> None:
    """Export results to HTML report (can be printed to PDF)."""
    
    # Calculate statistics
    total = len(results)
    pass_count = sum(1 for r in results if r.status.value == "PASS")
    warn_count = sum(1 for r in results if r.status.value == "WARN")
    fail_count = sum(1 for r in results if r.status.value in ("FAIL", "INVALID"))
    
    no_action = sum(1 for r in results if r.classification.value == "NO_ACTION")
    netbox_update = sum(1 for r in results if r.classification.value == "NETBOX_UPDATE")
    review_required = sum(1 for r in results if r.classification.value == "REVIEW_REQUIRED")
    invalid = sum(1 for r in results if r.classification.value == "INVALID")
    
    # Group issues by type
    issue_counts = {}
    for r in results:
        for issue in r.issues:
            issue_counts[issue.code] = issue_counts.get(issue.code, 0) + 1
    
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>NetBox Trust Boundary - Validation Report</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #1e1e1e;
            color: #cccccc;
            padding: 40px;
            line-height: 1.6;
        }}
        .container {{ max-width: 1200px; margin: 0 auto; }}
        h1 {{
            color: #4ec9b0;
            font-size: 28px;
            margin-bottom: 8px;
            border-bottom: 2px solid #4ec9b0;
            padding-bottom: 10px;
        }}
        h2 {{
            color: #569cd6;
            font-size: 20px;
            margin-top: 30px;
            margin-bottom: 15px;
        }}
        .subtitle {{
            color: #888;
            font-size: 14px;
            margin-bottom: 30px;
        }}
        .meta {{
            background: #252526;
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 30px;
        }}
        .meta-row {{
            display: flex;
            margin-bottom: 8px;
        }}
        .meta-label {{
            width: 150px;
            color: #888;
        }}
        .meta-value {{
            color: #cccccc;
        }}
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 20px;
            margin-bottom: 30px;
        }}
        .stat-card {{
            background: #252526;
            padding: 20px;
            border-radius: 8px;
            text-align: center;
        }}
        .stat-value {{
            font-size: 36px;
            font-weight: bold;
        }}
        .stat-label {{
            color: #888;
            font-size: 14px;
            margin-top: 5px;
        }}
        .pass {{ color: #4ec9b0; }}
        .warn {{ color: #f0c000; }}
        .fail {{ color: #f14c4c; }}
        table {{
            width: 100%;
            border-collapse: collapse;
            background: #252526;
            border-radius: 8px;
            overflow: hidden;
        }}
        th, td {{
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #3c3c3c;
        }}
        th {{
            background: #3c3c3c;
            color: #cccccc;
            font-weight: 600;
        }}
        tr:hover {{
            background: #2d2d2d;
        }}
        .issue-list {{
            background: #252526;
            padding: 20px;
            border-radius: 8px;
        }}
        .issue-item {{
            display: flex;
            justify-content: space-between;
            padding: 8px 0;
            border-bottom: 1px solid #3c3c3c;
        }}
        .issue-item:last-child {{
            border-bottom: none;
        }}
        .footer {{
            margin-top: 40px;
            text-align: center;
            color: #666;
            font-size: 12px;
        }}
        @media print {{
            body {{ background: white; color: black; }}
            .stat-card, .meta, .issue-list, table {{ background: #f5f5f5; }}
            th {{ background: #e0e0e0; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>NetBox Trust Boundary</h1>
        <p class="subtitle">Validation Report — "Validate first. Change once."</p>
        
        <div class="meta">
            <div class="meta-row">
                <span class="meta-label">Generated:</span>
                <span class="meta-value">{timestamp}</span>
            </div>
            <div class="meta-row">
                <span class="meta-label">Source File:</span>
                <span class="meta-value">{source_file or 'N/A'}</span>
            </div>
            <div class="meta-row">
                <span class="meta-label">NetBox Site:</span>
                <span class="meta-value">{site_name or 'N/A'}</span>
            </div>
            <div class="meta-row">
                <span class="meta-label">Total Rows:</span>
                <span class="meta-value">{total}</span>
            </div>
        </div>

        <h2>Executive Summary</h2>
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-value pass">{pass_count}</div>
                <div class="stat-label">Passed</div>
            </div>
            <div class="stat-card">
                <div class="stat-value warn">{warn_count}</div>
                <div class="stat-label">Warnings</div>
            </div>
            <div class="stat-card">
                <div class="stat-value fail">{fail_count}</div>
                <div class="stat-label">Failed</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{total}</div>
                <div class="stat-label">Total</div>
            </div>
        </div>

        <h2>Classification Breakdown</h2>
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-value pass">{no_action}</div>
                <div class="stat-label">No Action Needed</div>
            </div>
            <div class="stat-card">
                <div class="stat-value" style="color: #569cd6;">{netbox_update}</div>
                <div class="stat-label">NetBox Update</div>
            </div>
            <div class="stat-card">
                <div class="stat-value warn">{review_required}</div>
                <div class="stat-label">Review Required</div>
            </div>
            <div class="stat-card">
                <div class="stat-value fail">{invalid}</div>
                <div class="stat-label">Invalid</div>
            </div>
        </div>

        <h2>Issues Found</h2>
        <div class="issue-list">
"""
    
    if issue_counts:
        for code, count in sorted(issue_counts.items(), key=lambda x: -x[1]):
            html += f'            <div class="issue-item"><span>{code}</span><span>{count}</span></div>\n'
    else:
        html += '            <div class="issue-item"><span>No issues found</span><span>✓</span></div>\n'
    
    html += """        </div>

        <h2>Detailed Results</h2>
        <table>
            <thead>
                <tr>
                    <th>Row</th>
                    <th>Severity</th>
                    <th>Classification</th>
                    <th>Rack</th>
                    <th>RU</th>
                    <th>Hostname</th>
                    <th>Finding</th>
                </tr>
            </thead>
            <tbody>
"""
    
    for result in results:
        row = result.row
        severity_class = result.status.value.lower()
        finding = result.issues[0].message if result.issues else "OK"
        classification = result.classification.value.replace("_", " ").title()
        
        html += f"""                <tr>
                    <td>{row.row_number}</td>
                    <td class="{severity_class}">{result.status.value}</td>
                    <td>{classification}</td>
                    <td>{row.rack or ''}</td>
                    <td>{row.ru_position or ''}</td>
                    <td>{row.hostname or ''}</td>
                    <td>{finding}</td>
                </tr>
"""
    
    html += f"""            </tbody>
        </table>

        <div class="footer">
            <p>Generated by NetBox Trust Boundary v1.0.0</p>
            <p>This report validates CSV data against NetBox. No changes were made to NetBox.</p>
        </div>
    </div>
</body>
</html>
"""
    
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(html)
