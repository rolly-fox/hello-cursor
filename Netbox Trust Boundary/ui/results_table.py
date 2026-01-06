"""
Results table widget for displaying validation results.
"""

from typing import Optional

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QComboBox,
    QLabel,
    QAbstractItemView,
    QFrame,
    QSplitter,
    QGroupBox,
    QScrollArea,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QBrush

from core.models import ValidationResult, Severity, RowClassification, ImportReadiness


class NumericTableWidgetItem(QTableWidgetItem):
    """Table widget item that sorts numerically instead of alphabetically."""
    
    def __lt__(self, other):
        """Compare items by their UserRole data (numeric value)."""
        try:
            self_value = self.data(Qt.UserRole)
            other_value = other.data(Qt.UserRole)
            if self_value is not None and other_value is not None:
                return float(self_value) < float(other_value)
        except (TypeError, ValueError):
            pass
        # Fall back to text comparison
        return super().__lt__(other)


# Color scheme for status indicators
STATUS_COLORS = {
    Severity.PASS: "#4ec9b0",      # Green/teal
    Severity.WARN: "#f0c000",      # Yellow
    Severity.FAIL: "#f14c4c",      # Red
    Severity.INVALID: "#808080",   # Gray
}

CLASSIFICATION_COLORS = {
    RowClassification.NO_ACTION: "#4ec9b0",
    RowClassification.NETBOX_UPDATE: "#569cd6",
    RowClassification.REVIEW_REQUIRED: "#f0c000",
    RowClassification.INVALID: "#f14c4c",
}


class ResultsTableWidget(QWidget):
    """Widget for displaying validation results in a filterable table."""

    COLUMNS = [
        ("Row", 45),
        ("Position", 75),       # Is there space? (Available/Review/Blocked)
        ("Import Ready", 90),   # Can this be bulk imported? (Ready/Incomplete)
        ("Finding Types", 200), # All finding codes (hover for details)
        ("Site", 70),
        ("Rack", 85),
        ("RU", 45),
        ("Height", 45),
        ("Face", 55),
        ("Device Name", 120),
        ("Role", 75),
        ("Status", 65),
        ("Make", 75),
        ("Model", 90),
        ("Finding", 160),
        ("Recommendation", 160),
    ]

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.results: list[ValidationResult] = []
        self.setMouseTracking(True)  # Enable mouse tracking for tooltips
        self._setup_ui()

    def _setup_ui(self):
        """Set up the widget layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Legend for dual status with hover tooltips
        legend_layout = QHBoxLayout()
        legend_layout.setSpacing(4)
        
        # Position Status legend
        pos_label = QLabel("Position:")
        pos_label.setStyleSheet("color: #888888; margin-right: 4px;")
        pos_label.setToolTip("Position status indicates if the RU slot is available in the rack")
        legend_layout.addWidget(pos_label)
        
        position_statuses = [
            ("✓ Available", "#4ec9b0", 
             "AVAILABLE: RU position is free in NetBox.\n"
             "No device currently occupies this slot.\n"
             "Safe to add a new device here."),
            ("⚠ Review", "#f0c000", 
             "REVIEW: Position may have issues.\n"
             "• Device exists but at different position\n"
             "• Make/model mismatch detected\n"
             "Check details before proceeding."),
            ("✗ Blocked", "#f14c4c", 
             "BLOCKED: Position is unavailable.\n"
             "• RU collision with existing device\n"
             "• Rack not found in NetBox\n"
             "• Position out of rack range\n"
             "Cannot add device here."),
        ]
        for label, color, tooltip in position_statuses:
            lbl = QLabel(label)
            lbl.setStyleSheet(f"color: {color}; padding: 2px 6px;")
            lbl.setToolTip(tooltip)
            lbl.setMouseTracking(True)
            legend_layout.addWidget(lbl)
        
        legend_layout.addSpacing(20)
        
        # Import Readiness legend
        import_label = QLabel("Import:")
        import_label.setStyleSheet("color: #888888; margin-right: 4px;")
        import_label.setToolTip("Import status indicates if CSV row has all required fields for NetBox bulk import")
        legend_layout.addWidget(import_label)
        
        import_statuses = [
            ("✓ Ready", "#4ec9b0", 
             "READY: All required fields present.\n"
             "• device_name ✓\n"
             "• device_role ✓\n"
             "• rack, ru_position ✓\n"
             "• manufacturer, model ✓\n"
             "Can be bulk imported to NetBox."),
            ("⚠ Incomplete", "#ce9178", 
             "INCOMPLETE: Missing required fields.\n"
             "NetBox bulk import requires:\n"
             "• device_name (name)\n"
             "• device_role (role)\n"
             "• manufacturer, model\n"
             "Hover over row for specific missing fields."),
        ]
        for label, color, tooltip in import_statuses:
            lbl = QLabel(label)
            lbl.setStyleSheet(f"color: {color}; padding: 2px 6px;")
            lbl.setToolTip(tooltip)
            lbl.setMouseTracking(True)
            legend_layout.addWidget(lbl)
        
        legend_layout.addStretch()
        layout.addLayout(legend_layout)

        # Filter bar with dual-status filters
        filter_layout = QHBoxLayout()
        
        # Position Status filter
        filter_layout.addWidget(QLabel("Position:"))
        
        self.status_filter = QComboBox()
        self.status_filter.addItem("All", None)
        self.status_filter.addItem("✓ Available", "available")
        self.status_filter.addItem("⚠ Review", "review")
        self.status_filter.addItem("✗ Blocked", "blocked")
        self.status_filter.setItemData(1, QColor("#4ec9b0"), Qt.ForegroundRole)
        self.status_filter.setItemData(2, QColor("#f0c000"), Qt.ForegroundRole)
        self.status_filter.setItemData(3, QColor("#f14c4c"), Qt.ForegroundRole)
        self.status_filter.currentIndexChanged.connect(self._apply_filter)
        filter_layout.addWidget(self.status_filter)
        
        filter_layout.addSpacing(15)
        
        # Import Readiness filter
        filter_layout.addWidget(QLabel("Import:"))
        
        self.import_filter = QComboBox()
        self.import_filter.addItem("All", None)
        self.import_filter.addItem("✓ Ready", ImportReadiness.READY)
        self.import_filter.addItem("⚠ Incomplete", ImportReadiness.INCOMPLETE)
        self.import_filter.setItemData(1, QColor("#4ec9b0"), Qt.ForegroundRole)
        self.import_filter.setItemData(2, QColor("#ce9178"), Qt.ForegroundRole)
        self.import_filter.currentIndexChanged.connect(self._apply_filter)
        filter_layout.addWidget(self.import_filter)
        
        filter_layout.addSpacing(15)
        
        # Quick filter: Ready to Import (Available + Ready)
        filter_layout.addWidget(QLabel("|"))
        self.ready_to_import_filter = QComboBox()
        self.ready_to_import_filter.addItem("Show All", None)
        self.ready_to_import_filter.addItem("🚀 Ready to Import", "ready_to_import")
        self.ready_to_import_filter.addItem("📋 Needs Data", "needs_data")
        self.ready_to_import_filter.setItemData(1, QColor("#4ec9b0"), Qt.ForegroundRole)
        self.ready_to_import_filter.setItemData(2, QColor("#ce9178"), Qt.ForegroundRole)
        self.ready_to_import_filter.currentIndexChanged.connect(self._apply_quick_filter)
        filter_layout.addWidget(self.ready_to_import_filter)
        
        filter_layout.addStretch()
        
        self.row_count_label = QLabel("")
        filter_layout.addWidget(self.row_count_label)
        
        layout.addLayout(filter_layout)

        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels([col[0] for col in self.COLUMNS])
        
        # Set column widths - fixed widths, with horizontal scrolling
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)  # Don't stretch, allow scrolling
        for i, (_, width) in enumerate(self.COLUMNS):
            self.table.setColumnWidth(i, width)
        
        # Enable horizontal scrolling
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        
        # Table settings
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setSortingEnabled(True)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        
        # Connect row selection to detail panel
        self.table.itemSelectionChanged.connect(self._on_row_selected)
        
        # Apply table styles
        self.table.setStyleSheet("""
            QTableWidget {
                background-color: #1e1e1e;
                color: #cccccc;
                gridline-color: #3c3c3c;
                border: 1px solid #3c3c3c;
            }
            QTableWidget::item {
                padding: 4px;
            }
            QTableWidget::item:selected {
                background-color: #094771;
            }
            QTableWidget::item:alternate {
                background-color: #252526;
            }
            QHeaderView::section {
                background-color: #3c3c3c;
                color: #cccccc;
                padding: 6px;
                border: none;
                border-right: 1px solid #505050;
                border-bottom: 1px solid #505050;
                font-weight: bold;
            }
            QComboBox {
                background-color: #3c3c3c;
                color: #ffffff;
                border: 1px solid #505050;
                padding: 4px 12px;
                border-radius: 2px;
                min-width: 100px;
            }
            QComboBox:hover {
                border-color: #007acc;
                background-color: #454545;
            }
            QComboBox::drop-down {
                border: none;
                padding-right: 8px;
            }
            QComboBox QAbstractItemView {
                background-color: #2d2d30;
                color: #ffffff;
                selection-background-color: #094771;
                selection-color: #ffffff;
                border: 1px solid #3c3c3c;
                padding: 4px;
                outline: none;
            }
            QComboBox QAbstractItemView::item {
                padding: 6px 8px;
                min-height: 20px;
            }
            QComboBox QAbstractItemView::item:hover {
                background-color: #3c3c3c;
            }
            QComboBox QAbstractItemView::item:selected {
                background-color: #094771;
            }
            QLabel {
                color: #cccccc;
            }
        """)
        
        # Splitter for table + detail panel
        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(self.table)
        
        # Detail panel for selected row with labeled border
        self.detail_group = QGroupBox("Row Details")
        self.detail_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                color: #569cd6;
                border: 1px solid #3c3c3c;
                border-radius: 4px;
                margin-top: 8px;
                padding-top: 8px;
                background-color: #252526;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
                background-color: #252526;
            }
        """)
        detail_layout = QVBoxLayout(self.detail_group)
        detail_layout.setContentsMargins(8, 12, 8, 8)
        
        # Header showing selected row info
        self.detail_header = QLabel("Click a row to see details")
        self.detail_header.setStyleSheet("font-weight: bold; color: #4ec9b0; border: none;")
        detail_layout.addWidget(self.detail_header)
        
        # Scroll area for content
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: transparent;
            }
            QScrollBar:vertical {
                background-color: #2d2d30;
                width: 12px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background-color: #5a5a5a;
                border-radius: 5px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #6a6a6a;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)
        
        # Content widget inside scroll area
        content_widget = QWidget()
        content_widget.setStyleSheet("background-color: transparent;")
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        
        self.detail_content = QLabel("")
        self.detail_content.setStyleSheet("color: #cccccc; border: none; padding-left: 8px;")
        self.detail_content.setWordWrap(True)
        self.detail_content.setTextFormat(Qt.RichText)
        self.detail_content.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.detail_content.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        content_layout.addWidget(self.detail_content)
        content_layout.addStretch()
        
        scroll_area.setWidget(content_widget)
        detail_layout.addWidget(scroll_area)
        
        self.detail_group.setMinimumHeight(100)
        self.detail_group.setMaximumHeight(200)
        splitter.addWidget(self.detail_group)
        
        splitter.setSizes([400, 100])
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, True)
        
        layout.addWidget(splitter)

    def set_results(self, results: list[ValidationResult]):
        """Populate table with validation results."""
        self.results = results
        self._refresh_table()

    def clear(self):
        """Clear all results."""
        self.results = []
        self.table.setRowCount(0)
        self.row_count_label.setText("")

    def _apply_filter(self):
        """Handle filter dropdown change."""
        # Reset quick filter when individual filters change
        self.ready_to_import_filter.blockSignals(True)
        self.ready_to_import_filter.setCurrentIndex(0)
        self.ready_to_import_filter.blockSignals(False)
        self._refresh_table()
    
    def _apply_quick_filter(self):
        """Handle quick filter (Ready to Import / Needs Data)."""
        quick = self.ready_to_import_filter.currentData()
        
        # Reset individual filters when quick filter is used
        self.status_filter.blockSignals(True)
        self.import_filter.blockSignals(True)
        self.status_filter.setCurrentIndex(0)
        self.import_filter.setCurrentIndex(0)
        self.status_filter.blockSignals(False)
        self.import_filter.blockSignals(False)
        
        self._refresh_table()
    
    def _refresh_table(self):
        """Refresh table display with current filters."""
        filtered = self.results
        
        # Check quick filter first
        quick_filter = self.ready_to_import_filter.currentData()
        if quick_filter == "ready_to_import":
            # Available position + Import ready
            filtered = [r for r in filtered 
                       if r.status == Severity.PASS and r.import_readiness == ImportReadiness.READY]
        elif quick_filter == "needs_data":
            # Available position but incomplete import data
            filtered = [r for r in filtered 
                       if r.status == Severity.PASS and r.import_readiness == ImportReadiness.INCOMPLETE]
        else:
            # Apply individual filters
            position_filter = self.status_filter.currentData()
            if position_filter == "available":
                filtered = [r for r in filtered if r.status == Severity.PASS]
            elif position_filter == "review":
                filtered = [r for r in filtered if r.status == Severity.WARN]
            elif position_filter == "blocked":
                filtered = [r for r in filtered if r.status in (Severity.FAIL, Severity.INVALID)]
            
            import_filter = self.import_filter.currentData()
            if import_filter is not None:
                filtered = [r for r in filtered if r.import_readiness == import_filter]
        
        # Disable sorting while populating
        self.table.setSortingEnabled(False)
        
        # Populate table
        self.table.setRowCount(len(filtered))
        
        for row_idx, result in enumerate(filtered):
            self._populate_row(row_idx, result)
        
        # Re-enable sorting
        self.table.setSortingEnabled(True)
        
        # Update count label with context
        if len(filtered) == len(self.results):
            self.row_count_label.setText(f"{len(filtered)} rows")
        else:
            self.row_count_label.setText(f"{len(filtered)} of {len(self.results)} rows")

    def _populate_row(self, row_idx: int, result: ValidationResult):
        """Populate a single table row."""
        row = result.row
        col = 0
        
        # Row number (numeric sorting)
        item = NumericTableWidgetItem(str(row.row_number))
        item.setData(Qt.UserRole, row.row_number)
        self.table.setItem(row_idx, col, item)
        col += 1
        
        # Position Status (Available/Review/Blocked) - based on validation severity
        status = result.status
        if status == Severity.PASS:
            pos_text = "✓ Available"
            pos_color = "#4ec9b0"
            pos_tooltip = "RU position is available - no collision detected"
        elif status == Severity.WARN:
            pos_text = "⚠ Review"
            pos_color = "#f0c000"
            pos_tooltip = "Position may have issues - review recommended"
        else:  # FAIL or INVALID
            pos_text = "✗ Blocked"
            pos_color = "#f14c4c"
            pos_tooltip = "Position unavailable - collision or validation error"
        item = QTableWidgetItem(pos_text)
        item.setForeground(QBrush(QColor(pos_color)))
        item.setToolTip(pos_tooltip)
        self.table.setItem(row_idx, col, item)
        col += 1
        
        # Import Readiness (Ready/Incomplete)
        import_ready = result.import_readiness
        if import_ready == ImportReadiness.READY:
            import_text = "✓ Ready"
            import_color = "#4ec9b0"
            import_tooltip = "All required fields present - ready for bulk import"
        else:
            missing = result.missing_import_fields
            import_text = "⚠ Incomplete"
            import_color = "#ce9178"
            import_tooltip = f"Missing for import: {', '.join(missing)}"
        item = QTableWidgetItem(import_text)
        item.setForeground(QBrush(QColor(import_color)))
        item.setToolTip(import_tooltip)
        self.table.setItem(row_idx, col, item)
        col += 1
        
        # Finding Type (show all issue codes)
        if result.issues:
            # Get unique codes in order
            codes = []
            for issue in result.issues:
                if issue.code not in codes:
                    codes.append(issue.code)
            
            # Display format: show all codes, comma-separated
            finding_type = ", ".join(codes)
            
            # Full tooltip with all details
            tooltip_lines = [f"• {issue.code}: {issue.message}" for issue in result.issues]
            finding_tooltip = "\n".join(tooltip_lines)
        else:
            finding_type = "OK"
            finding_tooltip = "No issues found"
        
        item = QTableWidgetItem(finding_type)
        item.setForeground(QBrush(QColor(STATUS_COLORS.get(status, "#cccccc"))))
        item.setToolTip(finding_tooltip)
        self.table.setItem(row_idx, col, item)
        col += 1
        
        # Site (from CSV or config default)
        item = QTableWidgetItem(row.site or "(config)")
        if not row.site:
            item.setForeground(QBrush(QColor("#888888")))
        self.table.setItem(row_idx, col, item)
        col += 1
        
        # Rack
        item = QTableWidgetItem(row.rack or "")
        self.table.setItem(row_idx, col, item)
        col += 1
        
        # RU Position (numeric sorting)
        item = NumericTableWidgetItem(str(row.ru_position) if row.ru_position is not None else "")
        item.setData(Qt.UserRole, row.ru_position or 0)
        self.table.setItem(row_idx, col, item)
        col += 1
        
        # RU Height (numeric sorting)
        item = NumericTableWidgetItem(str(row.ru_height) if row.ru_height is not None else "")
        item.setData(Qt.UserRole, row.ru_height or 0)
        self.table.setItem(row_idx, col, item)
        col += 1
        
        # Face (front/rear/full)
        face_display = row.face.title() if row.face else "Full"
        item = QTableWidgetItem(face_display)
        self.table.setItem(row_idx, col, item)
        col += 1
        
        # Device Name
        item = QTableWidgetItem(row.hostname or "")
        if not row.hostname:
            item.setForeground(QBrush(QColor("#ce9178")))
            item.setText("(unnamed)")
        self.table.setItem(row_idx, col, item)
        col += 1
        
        # Device Role
        item = QTableWidgetItem(row.device_role or "")
        if not row.device_role:
            item.setForeground(QBrush(QColor("#ce9178")))
            item.setText("(missing)")
        self.table.setItem(row_idx, col, item)
        col += 1
        
        # Status
        status_display = (row.status or "active").title()
        item = QTableWidgetItem(status_display)
        self.table.setItem(row_idx, col, item)
        col += 1
        
        # Make (manufacturer)
        item = QTableWidgetItem(row.make or "")
        if not row.make:
            item.setForeground(QBrush(QColor("#ce9178")))
            item.setText("(missing)")
        self.table.setItem(row_idx, col, item)
        col += 1
        
        # Model (device type)
        item = QTableWidgetItem(row.model or "")
        if not row.model:
            item.setForeground(QBrush(QColor("#ce9178")))
            item.setText("(missing)")
        self.table.setItem(row_idx, col, item)
        col += 1
        
        # Finding (messages)
        if result.issues:
            finding_text = result.issues[0].message
            if len(result.issues) > 1:
                finding_text += f" (and {len(result.issues) - 1} more)"
        else:
            finding_text = "No issues found"
        item = QTableWidgetItem(finding_text)
        if any(i.status == Severity.FAIL for i in result.issues):
            item.setForeground(QBrush(QColor(STATUS_COLORS[Severity.FAIL])))
        elif any(i.status == Severity.WARN for i in result.issues):
            item.setForeground(QBrush(QColor(STATUS_COLORS[Severity.WARN])))
        self.table.setItem(row_idx, col, item)
        col += 1
        
        # Recommendation
        if result.issues:
            recommendation = result.issues[0].recommendation
        else:
            recommendation = "No action required."
        item = QTableWidgetItem(recommendation)
        self.table.setItem(row_idx, col, item)

    def get_visible_results(self) -> list[ValidationResult]:
        """Get currently visible (filtered) results."""
        filtered = self.results
        
        # Check quick filter first
        quick_filter = self.ready_to_import_filter.currentData()
        if quick_filter == "ready_to_import":
            filtered = [r for r in filtered 
                       if r.status == Severity.PASS and r.import_readiness == ImportReadiness.READY]
        elif quick_filter == "needs_data":
            filtered = [r for r in filtered 
                       if r.status == Severity.PASS and r.import_readiness == ImportReadiness.INCOMPLETE]
        else:
            # Apply individual filters
            position_filter = self.status_filter.currentData()
            if position_filter == "available":
                filtered = [r for r in filtered if r.status == Severity.PASS]
            elif position_filter == "review":
                filtered = [r for r in filtered if r.status == Severity.WARN]
            elif position_filter == "blocked":
                filtered = [r for r in filtered if r.status in (Severity.FAIL, Severity.INVALID)]
            
            import_filter = self.import_filter.currentData()
            if import_filter is not None:
                filtered = [r for r in filtered if r.import_readiness == import_filter]
        
        return filtered

    def _on_row_selected(self):
        """Handle row selection - show details in panel below."""
        selected = self.table.selectedItems()
        if not selected:
            self.detail_header.setText("Click a row to see details")
            self.detail_content.setText("")
            return
        
        # Get the row number from first column
        row_idx = selected[0].row()
        
        # Find the matching result (need to account for filtering)
        visible = self.get_visible_results()
        if row_idx >= len(visible):
            return
        
        result = visible[row_idx]
        row = result.row
        
        # Build header
        status_icon = {"PASS": "✓", "WARN": "⚠", "FAIL": "✗", "INVALID": "○"}.get(result.status.value, "?")
        import_icon = "✓" if result.import_readiness.value == "READY" else "⚠"
        
        header = (
            f"Row {row.row_number}: {row.rack} / RU {row.ru_position} / "
            f"{row.hostname or '(unnamed)'} — "
            f"Position: {status_icon} | Import: {import_icon}"
        )
        self.detail_header.setText(header)
        
        # Build detail content with all issues
        if result.issues:
            lines = []
            for issue in result.issues:
                status_color = {
                    "PASS": "#4ec9b0",
                    "WARN": "#f0c000", 
                    "FAIL": "#f14c4c",
                    "INVALID": "#808080"
                }.get(issue.status.value, "#cccccc")
                
                lines.append(
                    f"<span style='color: {status_color};'>• [{issue.code}]</span> "
                    f"{issue.message}"
                )
                if issue.recommendation:
                    lines.append(f"   <span style='color: #888;'>→ {issue.recommendation}</span>")
            
            content = "<br>".join(lines)
        else:
            content = "<span style='color: #4ec9b0;'>✓ No issues found. Ready for import.</span>"
        
        # Add missing fields info if incomplete
        if result.import_readiness.value == "INCOMPLETE":
            missing = result.missing_import_fields
            content += f"<br><br><span style='color: #ce9178;'>Missing for import: {', '.join(missing)}</span>"
        
        self.detail_content.setText(content)
