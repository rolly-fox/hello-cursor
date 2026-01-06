"""
Main application window for NetBox Trust Boundary.
"""

from pathlib import Path
from typing import Optional
from datetime import datetime

from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QFileDialog,
    QMessageBox,
    QStatusBar,
    QProgressBar,
    QFrame,
    QSplitter,
    QGroupBox,
    QTextEdit,
    QDialog,
    QDialogButtonBox,
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont, QAction, QIcon, QPixmap, QPainter, QColor

from core.netbox_client import NetBoxClient, NetBoxClientError
from core.csv_loader import CSVLoader, CSVLoadError
from core.validators import Validator
from core.models import CSVRow, ValidationResult

from .results_table import ResultsTableWidget
from .config_dialog import ConfigDialog


class WatermarkWidget(QWidget):
    """Central widget with optional watermark logo in bottom-right corner."""
    
    def __init__(self, logo_pixmap: Optional[QPixmap] = None, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._logo = logo_pixmap
        # Set opacity for watermark (0.0 = invisible, 1.0 = fully visible)
        self._watermark_opacity = 0.08  # Very subtle
        self._watermark_size = 200  # Size in pixels
    
    def paintEvent(self, event):
        """Paint the background watermark."""
        super().paintEvent(event)
        
        if self._logo and not self._logo.isNull():
            painter = QPainter(self)
            painter.setRenderHint(QPainter.SmoothPixmapTransform)
            
            # Set opacity
            painter.setOpacity(self._watermark_opacity)
            
            # Scale logo to desired size while keeping aspect ratio
            scaled = self._logo.scaled(
                self._watermark_size, self._watermark_size,
                Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            
            # Position in bottom-right corner with padding
            x = self.width() - scaled.width() - 20
            y = self.height() - scaled.height() - 20
            
            painter.drawPixmap(x, y, scaled)
            painter.end()


class CacheRefreshWorker(QThread):
    """Background worker for refreshing NetBox cache."""
    finished = Signal(bool, str)  # success, message
    progress = Signal(str, int, int)  # status message, current, total (0,0 = indeterminate)

    def __init__(self, client: NetBoxClient):
        super().__init__()
        self.client = client

    def run(self):
        try:
            self.progress.emit("Testing connection to NetBox...", 0, 0)
            print("[CacheRefresh] Testing connection...")
            success, message = self.client.test_connection()
            if not success:
                self.finished.emit(False, message)
                return

            self.progress.emit("Fetching site information...", 0, 0)
            print("[CacheRefresh] Connection OK. Fetching site info...")
            
            # Custom refresh with progress callbacks
            rack_count, device_count = self._refresh_with_progress()
            
            print(f"[CacheRefresh] Complete: {rack_count} racks, {device_count} devices")
            self.finished.emit(
                True,
                f"Cached {rack_count} racks, {device_count} devices",
            )
        except NetBoxClientError as e:
            print(f"[CacheRefresh] NetBox error: {e}")
            self.finished.emit(False, str(e))
        except Exception as e:
            import traceback
            print(f"[CacheRefresh] Unexpected error: {e}\n{traceback.format_exc()}")
            self.finished.emit(False, f"Unexpected error: {e}")

    def _refresh_with_progress(self) -> tuple[int, int]:
        """Refresh cache with progress updates."""
        client = self.client
        
        # Get site
        site_id = client.site_identifier
        if not site_id:
            raise NetBoxClientError("No site specified")
        
        client.cache.clear()
        
        # Fetch site info
        if site_id.isdigit():
            site = client._get(f"dcim/sites/{site_id}/")
        else:
            sites = client._get("dcim/sites/", {"slug": site_id})
            site_results = sites.get("results", [])
            if not site_results:
                raise NetBoxClientError(f"Site not found: {site_id}")
            site = site_results[0]
        
        client.cache.site_id = site["id"]
        client.cache.site_name = site["name"]
        
        self.progress.emit(f"Found site: {site['name']}. Fetching racks...", 0, 0)
        print(f"[CacheRefresh] Site: {site['name']} (ID: {site['id']})")
        
        # Fetch racks
        racks = client._get_all("dcim/racks/", {"site_id": client.cache.site_id})
        total_racks = len(racks)
        print(f"[CacheRefresh] Found {total_racks} racks")
        
        for i, rack_data in enumerate(racks):
            if i % 50 == 0:  # Update every 50 racks
                self.progress.emit(f"Processing rack {i+1}/{total_racks}...", i, total_racks)
            
            from core.models import CachedRack
            rack = CachedRack(
                id=rack_data["id"],
                name=rack_data["name"],
                site_id=client.cache.site_id,
                site_name=client.cache.site_name,
                location_id=rack_data.get("location", {}).get("id") if rack_data.get("location") else None,
                location_name=rack_data.get("location", {}).get("name") if rack_data.get("location") else None,
                u_height=rack_data.get("u_height", 42),
            )
            client.cache.add_rack(rack)
        
        self.progress.emit(f"Loaded {total_racks} racks. Fetching devices...", 0, 0)
        print(f"[CacheRefresh] Loaded {total_racks} racks. Fetching devices...")
        
        # Fetch devices
        devices = client._get_all("dcim/devices/", {"site_id": client.cache.site_id})
        total_devices = len(devices)
        print(f"[CacheRefresh] Found {total_devices} devices")
        
        for i, dev_data in enumerate(devices):
            if i % 100 == 0:  # Update every 100 devices
                self.progress.emit(f"Processing device {i+1}/{total_devices}...", i, total_devices)
            
            from core.models import CachedDevice
            # Get face - NetBox returns {"value": "front", "label": "Front"} or None
            face_data = dev_data.get("face")
            face = face_data.get("value") if isinstance(face_data, dict) else None
            
            device = CachedDevice(
                id=dev_data["id"],
                name=dev_data["name"],
                rack_id=dev_data.get("rack", {}).get("id") if dev_data.get("rack") else None,
                rack_name=dev_data.get("rack", {}).get("name") if dev_data.get("rack") else None,
                position=dev_data.get("position"),
                u_height=dev_data.get("device_type", {}).get("u_height", 1) if dev_data.get("device_type") else 1,
                device_type=dev_data.get("device_type", {}).get("model") if dev_data.get("device_type") else None,
                manufacturer=dev_data.get("device_type", {}).get("manufacturer", {}).get("name") if dev_data.get("device_type") else None,
                face=face,
            )
            client.cache.add_device(device)
        
        client.cache_timestamp = datetime.now()
        return total_racks, total_devices


class ValidationWorker(QThread):
    """Background worker for validation."""
    finished = Signal(list)  # list of ValidationResult
    progress = Signal(int, int, str)  # current, total, message
    error = Signal(str)  # error message

    def __init__(self, rows: list[CSVRow], validator: Validator):
        super().__init__()
        self.rows = rows
        self.validator = validator

    def run(self):
        try:
            print(f"[ValidationWorker] Starting validation of {len(self.rows)} rows...")
            results = []
            total = len(self.rows)
            
            for i, row in enumerate(self.rows):
                self.progress.emit(i + 1, total, f"Validating row {i + 1}: {row.rack} RU{row.ru_position}")
                print(f"[ValidationWorker] Row {i + 1}/{total}: {row.rack} RU{row.ru_position}")
                
                result = self.validator.validate_row(row)
                results.append(result)
            
            # Check for CSV-internal duplicates
            self._check_csv_duplicates(results)
            
            print(f"[ValidationWorker] Validation complete. {len(results)} results.")
            self.finished.emit(results)
            
        except Exception as e:
            import traceback
            error_msg = f"Validation error: {e}\n{traceback.format_exc()}"
            print(f"[ValidationWorker] ERROR: {error_msg}")
            self.error.emit(error_msg)

    def _check_csv_duplicates(self, results: list):
        """Check for duplicate positions within the CSV."""
        from core.models import ValidationStatus, RowClassification
        
        # Build position map
        positions: dict[str, list[int]] = {}
        for result in results:
            row = result.row
            if row.rack and row.ru_position is not None:
                key = f"{row.rack.lower()}:{row.ru_position}"
                if key not in positions:
                    positions[key] = []
                positions[key].append(row.row_number)
        
        # Mark duplicates
        duplicates = {k: v for k, v in positions.items() if len(v) > 1}
        for result in results:
            row = result.row
            if row.rack and row.ru_position is not None:
                key = f"{row.rack.lower()}:{row.ru_position}"
                if key in duplicates:
                    other_rows = [r for r in duplicates[key] if r != row.row_number]
                    result.add_issue(
                        code="CSV_COLLISION",
                        message=f"Same rack/RU as row(s): {', '.join(map(str, other_rows))}",
                        status=ValidationStatus.FAIL,
                    )
                    if result.classification != RowClassification.INVALID:
                        result.classification = RowClassification.REVIEW_REQUIRED


class MainWindow(QMainWindow):
    """Main application window."""

    def __init__(self):
        super().__init__()
        self.client = NetBoxClient.from_config()
        self.csv_rows: list[CSVRow] = []
        self.validation_results: list[ValidationResult] = []
        self.current_file: Optional[Path] = None
        
        self._setup_ui()
        self._setup_menu()
        self._update_connection_status()
        self._update_status()
        
        # Show config dialog on first launch if not configured
        if not self.client.is_configured:
            # Use a timer to show dialog after window is visible
            from PySide6.QtCore import QTimer
            QTimer.singleShot(100, self._prompt_initial_config)

    def _setup_ui(self):
        """Set up the main UI layout."""
        self.setWindowTitle("NetBox Trust Boundary")
        self.setMinimumSize(1200, 700)
        
        # Set window icon
        icon_path = Path(__file__).parent.parent / "assets" / "logo.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
            self._logo_pixmap = QPixmap(str(icon_path))
        else:
            self._logo_pixmap = None
        
        # Toggle for background watermark (set to False to disable)
        self._show_watermark = True

        # Central widget with watermark
        central = WatermarkWidget(self._logo_pixmap if self._show_watermark else None)
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        # Top toolbar area
        toolbar_frame = QFrame()
        toolbar_frame.setFrameShape(QFrame.StyledPanel)
        toolbar_layout = QHBoxLayout(toolbar_frame)
        toolbar_layout.setContentsMargins(8, 8, 8, 8)

        # Connection group
        conn_group = QGroupBox("NetBox Connection")
        conn_layout = QHBoxLayout(conn_group)
        
        self.connection_status = QLabel("Not configured")
        self.connection_status.setStyleSheet("color: #888;")
        self.connection_status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        conn_layout.addWidget(self.connection_status)
        
        self.btn_settings = QPushButton("Settings")
        self.btn_settings.clicked.connect(self._on_open_config)
        self.btn_settings.setStyleSheet("""
            QPushButton {
                background-color: #3c3c3c;
            }
            QPushButton:hover {
                background-color: #505050;
            }
        """)
        conn_layout.addWidget(self.btn_settings)
        
        self.btn_connect = QPushButton("Connect")
        self.btn_connect.clicked.connect(self._on_connect)
        conn_layout.addWidget(self.btn_connect)
        
        self.btn_refresh = QPushButton("Refresh Cache")
        self.btn_refresh.setEnabled(False)
        self.btn_refresh.clicked.connect(self._on_refresh_cache)
        conn_layout.addWidget(self.btn_refresh)
        
        toolbar_layout.addWidget(conn_group)

        # CSV group
        csv_group = QGroupBox("CSV Validation")
        csv_layout = QHBoxLayout(csv_group)
        
        self.file_label = QLabel("No file loaded")
        self.file_label.setStyleSheet("color: #888;")
        csv_layout.addWidget(self.file_label)
        
        self.btn_load = QPushButton("Load CSV")
        self.btn_load.clicked.connect(self._on_load_csv)
        csv_layout.addWidget(self.btn_load)
        
        self.btn_validate = QPushButton("Validate")
        self.btn_validate.setEnabled(False)
        self.btn_validate.clicked.connect(self._on_validate)
        csv_layout.addWidget(self.btn_validate)
        
        self.btn_export = QPushButton("Export Results")
        self.btn_export.setEnabled(False)
        self.btn_export.clicked.connect(self._on_export)
        csv_layout.addWidget(self.btn_export)
        
        toolbar_layout.addWidget(csv_group)
        toolbar_layout.addStretch()

        layout.addWidget(toolbar_frame)

        # Main content area with splitter (results table + activity log)
        content_splitter = QSplitter(Qt.Vertical)
        
        # Results table
        self.results_table = ResultsTableWidget()
        content_splitter.addWidget(self.results_table)
        
        # Activity Log panel
        log_frame = QFrame()
        log_frame.setFrameShape(QFrame.StyledPanel)
        log_layout = QVBoxLayout(log_frame)
        log_layout.setContentsMargins(8, 4, 8, 4)
        
        log_header = QHBoxLayout()
        log_label = QLabel("Activity Log")
        log_label.setStyleSheet("font-weight: bold; color: #cccccc;")
        log_header.addWidget(log_label)
        log_header.addStretch()
        
        clear_log_btn = QPushButton("Clear Log")
        clear_log_btn.setStyleSheet("padding: 2px 8px; font-size: 11px;")
        clear_log_btn.clicked.connect(self._clear_activity_log)
        log_header.addWidget(clear_log_btn)
        log_layout.addLayout(log_header)
        
        self.activity_log = QTextEdit()
        self.activity_log.setReadOnly(True)
        self.activity_log.setMaximumHeight(120)
        self.activity_log.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                color: #cccccc;
                border: 1px solid #3c3c3c;
                font-family: Consolas, monospace;
                font-size: 11px;
            }
        """)
        log_layout.addWidget(self.activity_log)
        
        content_splitter.addWidget(log_frame)
        
        # Set splitter sizes (results table gets more space)
        content_splitter.setSizes([500, 120])
        content_splitter.setCollapsible(0, False)
        content_splitter.setCollapsible(1, True)
        
        layout.addWidget(content_splitter, 1)

        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximumWidth(200)
        self.progress_bar.setVisible(False)
        self.status_bar.addPermanentWidget(self.progress_bar)

        # Apply stylesheet
        self._apply_styles()

    def _setup_menu(self):
        """Set up menu bar."""
        menubar = self.menuBar()
        
        # File menu
        file_menu = menubar.addMenu("&File")
        
        load_action = QAction("&Load CSV...", self)
        load_action.setShortcut("Ctrl+O")
        load_action.triggered.connect(self._on_load_csv)
        file_menu.addAction(load_action)
        
        export_action = QAction("&Export Results...", self)
        export_action.setShortcut("Ctrl+S")
        export_action.triggered.connect(self._on_export)
        file_menu.addAction(export_action)
        
        file_menu.addSeparator()
        
        exit_action = QAction("E&xit", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # Settings menu
        settings_menu = menubar.addMenu("&Settings")
        
        config_action = QAction("&Connection Settings...", self)
        config_action.triggered.connect(self._on_open_config)
        settings_menu.addAction(config_action)
        
        # Add Clear Data action
        file_menu.insertSeparator(exit_action)
        clear_action = QAction("&Clear Data", self)
        clear_action.setShortcut("Ctrl+Shift+C")
        clear_action.triggered.connect(self._on_clear_data)
        file_menu.insertAction(exit_action, clear_action)
        
        # Help menu
        help_menu = menubar.addMenu("&Help")
        
        about_action = QAction("&About NetBox Trust Boundary", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _apply_styles(self):
        """Apply visual styles."""
        self.setStyleSheet("""
            QMainWindow {
                background-color: #1e1e1e;
            }
            QGroupBox {
                font-weight: bold;
                border: 1px solid #3c3c3c;
                border-radius: 4px;
                margin-top: 8px;
                padding-top: 8px;
                background-color: #252526;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 4px;
                color: #cccccc;
            }
            QPushButton {
                background-color: #0e639c;
                color: white;
                border: none;
                padding: 6px 16px;
                border-radius: 2px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #1177bb;
            }
            QPushButton:pressed {
                background-color: #0d5a8c;
            }
            QPushButton:disabled {
                background-color: #3c3c3c;
                color: #888888;
            }
            QLabel {
                color: #cccccc;
            }
            QFrame {
                background-color: #252526;
                border-radius: 4px;
            }
            QStatusBar {
                background-color: #007acc;
                color: white;
            }
            QToolTip {
                background-color: #2d2d30;
                color: #cccccc;
                border: 1px solid #3c3c3c;
                padding: 8px;
                border-radius: 4px;
                font-size: 12px;
            }
            QMenuBar {
                background-color: #3c3c3c;
                color: #cccccc;
            }
            QMenuBar::item:selected {
                background-color: #505050;
            }
            QMenu {
                background-color: #252526;
                color: #cccccc;
                border: 1px solid #3c3c3c;
            }
            QMenu::item:selected {
                background-color: #094771;
            }
        """)

    def _update_status(self):
        """Update status bar with current state."""
        parts = []
        
        if self.client.cache_timestamp:
            age = self.client.cache_age_seconds
            if age < 60:
                age_str = f"{int(age)}s ago"
            elif age < 3600:
                age_str = f"{int(age/60)}m ago"
            else:
                age_str = f"{int(age/3600)}h ago"
            parts.append(f"Cache: {age_str}")
            parts.append(f"Racks: {len(self.client.cache.racks)}")
            parts.append(f"Devices: {len(self.client.cache.devices)}")
        
        if self.csv_rows:
            parts.append(f"CSV Rows: {len(self.csv_rows)}")
        
        if self.validation_results:
            pass_count = sum(1 for r in self.validation_results 
                           if r.status.value == "PASS")
            fail_count = sum(1 for r in self.validation_results 
                           if r.status.value in ("FAIL", "INVALID"))
            parts.append(f"Pass: {pass_count} | Fail: {fail_count}")
        
        self.status_bar.showMessage(" | ".join(parts) if parts else "Ready")

    def _on_connect(self):
        """Handle connect button click."""
        if not self.client.is_configured:
            QMessageBox.warning(
                self,
                "Not Configured",
                "NetBox connection not configured.\n\n"
                "Click 'Settings' to enter your NetBox URL, API token, and site.",
            )
            self._on_open_config()
            return

        self._set_busy(True, "Connecting to NetBox...")
        self._cache_start_time = datetime.now()
        
        self.worker = CacheRefreshWorker(self.client)
        self.worker.progress.connect(self._on_cache_progress)
        self.worker.finished.connect(self._on_cache_refresh_done)
        self.worker.start()

    def _on_refresh_cache(self):
        """Handle refresh cache button click."""
        self._set_busy(True, "Refreshing cache...")
        self._cache_start_time = datetime.now()
        
        self.worker = CacheRefreshWorker(self.client)
        self.worker.progress.connect(self._on_cache_progress)
        self.worker.finished.connect(self._on_cache_refresh_done)
        self.worker.start()

    def _on_cache_progress(self, message: str, current: int, total: int):
        """Handle cache refresh progress update."""
        elapsed = (datetime.now() - self._cache_start_time).total_seconds()
        
        if total > 0:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(current)
            rate = current / elapsed if elapsed > 0 else 0
            remaining = (total - current) / rate if rate > 0 else 0
            self.status_bar.showMessage(f"{message} | {elapsed:.1f}s elapsed | ~{remaining:.1f}s remaining")
        else:
            self.progress_bar.setRange(0, 0)  # Indeterminate
            self.status_bar.showMessage(f"{message} | {elapsed:.1f}s elapsed")

    def _on_cache_refresh_done(self, success: bool, message: str):
        """Handle cache refresh completion."""
        self._set_busy(False)
        
        if success:
            self._update_connection_status()
            self.btn_refresh.setEnabled(True)
            self.btn_validate.setEnabled(bool(self.csv_rows))
            self._log_activity(f"✅ Connected to NetBox: {self.client.cache.site_name}")
            self._log_activity(f"   Cached {len(self.client.cache.racks)} racks, {len(self.client.cache.devices)} devices")
            QMessageBox.information(self, "Connected", message)
        else:
            self.connection_status.setText("✗ Connection failed")
            self.connection_status.setStyleSheet("color: #f14c4c;")
            self._log_activity(f"❌ Connection failed")
            self._show_copyable_error("Connection Failed", message)
        
        self._update_status()

    def _show_copyable_error(self, title: str, message: str):
        """Show an error dialog with copyable text."""
        from PySide6.QtWidgets import QDialog, QTextEdit, QDialogButtonBox
        
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.setMinimumSize(500, 200)
        
        layout = QVBoxLayout(dialog)
        
        label = QLabel("An error occurred. You can copy the details below:")
        label.setStyleSheet("color: #f14c4c; font-weight: bold;")
        layout.addWidget(label)
        
        text_edit = QTextEdit()
        text_edit.setPlainText(message)
        text_edit.setReadOnly(True)
        text_edit.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                color: #cccccc;
                border: 1px solid #3c3c3c;
                font-family: Consolas, monospace;
                padding: 8px;
            }
        """)
        layout.addWidget(text_edit)
        
        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons)
        
        dialog.setStyleSheet("""
            QDialog {
                background-color: #252526;
            }
            QLabel {
                color: #cccccc;
            }
            QPushButton {
                background-color: #0e639c;
                color: white;
                border: none;
                padding: 6px 16px;
                border-radius: 2px;
            }
        """)
        
        dialog.exec()

    def _on_load_csv(self):
        """Handle load CSV button click."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Open CSV File",
            "",
            "CSV Files (*.csv);;All Files (*)",
        )
        
        if not file_path:
            return
        
        # Validate file type
        file_path = Path(file_path)
        valid_extensions = {'.csv', '.txt'}
        if file_path.suffix.lower() not in valid_extensions:
            QMessageBox.critical(
                self,
                "Invalid File Type",
                f"Cannot load '{file_path.name}'.\n\n"
                f"Expected: CSV file (.csv)\n"
                f"Got: {file_path.suffix or 'no extension'}\n\n"
                "Please select a valid CSV file.",
            )
            self._log_activity(f"❌ Rejected file: {file_path.name} (invalid type: {file_path.suffix})")
            return

        try:
            self._log_activity(f"📂 Loading: {file_path.name}...")
            
            loader = CSVLoader()
            self.csv_rows = loader.load(str(file_path))
            self.current_file = file_path
            self.validation_results = []
            
            self.file_label.setText(f"✓ {self.current_file.name} ({len(self.csv_rows)} rows)")
            self.file_label.setStyleSheet("color: #4ec9b0;")
            
            # Enable validate if cache is loaded
            self.btn_validate.setEnabled(bool(self.client.cache.racks))
            self.btn_export.setEnabled(False)
            
            # Clear previous results
            self.results_table.clear()
            
            # Log success
            self._log_activity(f"✅ Loaded: {file_path.name} ({len(self.csv_rows)} rows)")
            
            if loader.warnings:
                self._log_activity(f"⚠️ {len(loader.warnings)} warning(s) during parse")
            
            if loader.errors:
                QMessageBox.warning(
                    self,
                    "Parse Warnings",
                    f"Loaded with {len(loader.errors)} warning(s):\n\n" +
                    "\n".join(loader.errors[:10]),
                )
                self._log_activity(f"⚠️ {len(loader.errors)} parse error(s)")
            
            self._update_status()
            
        except CSVLoadError as e:
            QMessageBox.critical(self, "Load Error", str(e))
            self.file_label.setText("✗ Load failed")
            self.file_label.setStyleSheet("color: #f14c4c;")
            self._log_activity(f"❌ Load failed: {str(e)[:50]}")

    def _on_validate(self):
        """Handle validate button click."""
        if not self.csv_rows:
            QMessageBox.warning(self, "No Data", "Please load a CSV file first.")
            return
        
        if not self.client.cache.racks:
            QMessageBox.warning(self, "No Cache", "Please connect to NetBox first.")
            return

        self._set_busy(True, f"Validating {len(self.csv_rows)} rows...")
        self._validation_start_time = datetime.now()
        
        # Set progress bar to determinate mode
        self.progress_bar.setRange(0, len(self.csv_rows))
        self.progress_bar.setValue(0)
        
        validator = Validator(self.client.cache)
        
        self.validation_worker = ValidationWorker(self.csv_rows, validator)
        self.validation_worker.progress.connect(self._on_validation_progress)
        self.validation_worker.finished.connect(self._on_validation_done)
        self.validation_worker.error.connect(self._on_validation_error)
        self.validation_worker.start()

    def _on_validation_progress(self, current: int, total: int, message: str):
        """Handle validation progress update."""
        self.progress_bar.setValue(current)
        elapsed = (datetime.now() - self._validation_start_time).total_seconds()
        if current > 0:
            rate = current / elapsed
            remaining = (total - current) / rate if rate > 0 else 0
            self.status_bar.showMessage(f"{message} | {current}/{total} | {elapsed:.1f}s elapsed | ~{remaining:.1f}s remaining")
        else:
            self.status_bar.showMessage(message)

    def _on_validation_error(self, error_msg: str):
        """Handle validation error."""
        self._set_busy(False)
        self._show_copyable_error("Validation Error", error_msg)

    def _on_validation_done(self, results: list[ValidationResult]):
        """Handle validation completion."""
        self._set_busy(False)
        
        self.validation_results = results
        self.results_table.set_results(results)
        self.btn_export.setEnabled(True)
        
        # Summary
        pass_count = sum(1 for r in results if r.status.value == "PASS")
        warn_count = sum(1 for r in results if r.status.value == "WARN")
        fail_count = sum(1 for r in results if r.status.value in ("FAIL", "INVALID"))
        
        # Log validation summary
        from core.models import ImportReadiness
        ready_count = sum(1 for r in results if r.import_readiness == ImportReadiness.READY)
        self._log_activity(f"✅ Validation complete: {len(results)} rows")
        self._log_activity(f"   Position: {pass_count} available, {warn_count} review, {fail_count} blocked")
        self._log_activity(f"   Import: {ready_count} ready, {len(results) - ready_count} incomplete")
        
        self._update_status()
        
        # Show copyable summary dialog
        summary_text = (
            f"Validated {len(results)} rows:\n\n"
            f"  ✓ Pass: {pass_count}\n"
            f"  ⚠ Warnings: {warn_count}\n"
            f"  ✗ Fail/Invalid: {fail_count}\n\n"
            "--- Details ---\n"
        )
        for r in results:
            status_icon = {"PASS": "✓", "WARN": "⚠", "FAIL": "✗", "INVALID": "○"}.get(r.status.value, "?")
            issues_str = "; ".join(f"[{i.code}] {i.message}" for i in r.issues) if r.issues else "OK"
            summary_text += f"{status_icon} Row {r.row.row_number}: {r.row.rack} RU{r.row.ru_position} - {issues_str}\n"
        
        self._show_copyable_info("Validation Complete", summary_text)

    def _show_copyable_info(self, title: str, message: str):
        """Show an info dialog with copyable text."""
        from PySide6.QtWidgets import QDialog, QTextEdit, QDialogButtonBox
        
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.setMinimumSize(600, 400)
        
        layout = QVBoxLayout(dialog)
        
        text_edit = QTextEdit()
        text_edit.setPlainText(message)
        text_edit.setReadOnly(True)
        text_edit.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                color: #cccccc;
                border: 1px solid #3c3c3c;
                font-family: Consolas, monospace;
                padding: 8px;
            }
        """)
        layout.addWidget(text_edit)
        
        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons)
        
        dialog.setStyleSheet("""
            QDialog {
                background-color: #252526;
            }
            QPushButton {
                background-color: #0e639c;
                color: white;
                border: none;
                padding: 6px 16px;
                border-radius: 2px;
            }
        """)
        
        dialog.exec()

    def _on_export(self):
        """Handle export button click - show export options dialog."""
        if not self.validation_results:
            QMessageBox.warning(self, "No Results", "No validation results to export.")
            return

        from PySide6.QtWidgets import QDialog, QRadioButton, QButtonGroup
        from core.models import RowClassification
        
        dialog = QDialog(self)
        dialog.setWindowTitle("Export Results")
        dialog.setMinimumWidth(400)
        
        layout = QVBoxLayout(dialog)
        
        # Classification filter
        filter_group = QGroupBox("Filter by Classification")
        filter_layout = QVBoxLayout(filter_group)
        
        self.export_filter_group = QButtonGroup(dialog)
        
        rb_all = QRadioButton(f"All Results ({len(self.validation_results)})")
        rb_all.setChecked(True)
        self.export_filter_group.addButton(rb_all, 0)
        filter_layout.addWidget(rb_all)
        
        no_action_count = sum(1 for r in self.validation_results if r.classification == RowClassification.NO_ACTION)
        rb_no_action = QRadioButton(f"No Action ({no_action_count})")
        self.export_filter_group.addButton(rb_no_action, 1)
        filter_layout.addWidget(rb_no_action)
        
        update_count = sum(1 for r in self.validation_results if r.classification == RowClassification.NETBOX_UPDATE)
        rb_update = QRadioButton(f"NetBox Update ({update_count})")
        self.export_filter_group.addButton(rb_update, 2)
        filter_layout.addWidget(rb_update)
        
        review_count = sum(1 for r in self.validation_results if r.classification == RowClassification.REVIEW_REQUIRED)
        rb_review = QRadioButton(f"Review Required ({review_count})")
        self.export_filter_group.addButton(rb_review, 3)
        filter_layout.addWidget(rb_review)
        
        invalid_count = sum(1 for r in self.validation_results if r.classification == RowClassification.INVALID)
        rb_invalid = QRadioButton(f"Invalid ({invalid_count})")
        self.export_filter_group.addButton(rb_invalid, 4)
        filter_layout.addWidget(rb_invalid)
        
        layout.addWidget(filter_group)
        
        # Format selection
        format_group = QGroupBox("Export Format")
        format_layout = QVBoxLayout(format_group)
        
        self.export_format_group = QButtonGroup(dialog)
        
        rb_csv = QRadioButton("CSV (spreadsheet)")
        rb_csv.setChecked(True)
        self.export_format_group.addButton(rb_csv, 0)
        format_layout.addWidget(rb_csv)
        
        rb_json = QRadioButton("JSON (data exchange)")
        self.export_format_group.addButton(rb_json, 1)
        format_layout.addWidget(rb_json)
        
        rb_html = QRadioButton("HTML Report (print to PDF)")
        self.export_format_group.addButton(rb_html, 2)
        format_layout.addWidget(rb_html)
        
        layout.addWidget(format_group)
        
        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(dialog.reject)
        button_layout.addWidget(cancel_btn)
        
        export_btn = QPushButton("Export")
        export_btn.clicked.connect(dialog.accept)
        button_layout.addWidget(export_btn)
        
        layout.addLayout(button_layout)
        
        # Style
        dialog.setStyleSheet("""
            QDialog { background-color: #252526; }
            QGroupBox {
                font-weight: bold;
                border: 1px solid #3c3c3c;
                border-radius: 4px;
                margin-top: 8px;
                padding: 12px;
                padding-top: 24px;
                background-color: #1e1e1e;
                color: #cccccc;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 4px;
            }
            QRadioButton { color: #cccccc; }
            QPushButton {
                background-color: #0e639c;
                color: white;
                border: none;
                padding: 6px 16px;
                border-radius: 2px;
            }
            QPushButton:hover { background-color: #1177bb; }
        """)
        
        if dialog.exec() != QDialog.Accepted:
            return
        
        # Get selected options
        filter_id = self.export_filter_group.checkedId()
        classification_filter = {
            0: None,
            1: RowClassification.NO_ACTION,
            2: RowClassification.NETBOX_UPDATE,
            3: RowClassification.REVIEW_REQUIRED,
            4: RowClassification.INVALID,
        }.get(filter_id)
        
        format_id = self.export_format_group.checkedId()
        file_ext = {0: ".csv", 1: ".json", 2: ".html"}.get(format_id, ".csv")
        file_filter = {
            0: "CSV Files (*.csv)",
            1: "JSON Files (*.json)",
            2: "HTML Files (*.html)",
        }.get(format_id, "CSV Files (*.csv)")
        
        # Generate default filename
        default_name = ""
        if self.current_file:
            suffix = f"_{classification_filter.value.lower()}" if classification_filter else ""
            default_name = f"{self.current_file.stem}_validated{suffix}{file_ext}"
        
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Results",
            default_name,
            file_filter,
        )
        
        if not file_path:
            return

        try:
            from .export import export_results
            export_results(
                self.validation_results,
                file_path,
                classification_filter=classification_filter,
                site_name=self.client.cache.site_name or "",
                source_file=self.current_file.name if self.current_file else "",
            )
            QMessageBox.information(self, "Export Complete", f"Results exported to:\n{file_path}")
        except Exception as e:
            QMessageBox.critical(self, "Export Error", str(e))

    def _prompt_initial_config(self):
        """Prompt for initial configuration on first launch."""
        reply = QMessageBox.question(
            self,
            "Welcome to NetBox Trust Boundary",
            "NetBox connection is not configured.\n\n"
            "Would you like to set up your connection now?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if reply == QMessageBox.Yes:
            self._on_open_config()

    def _update_connection_status(self):
        """Update the connection status label based on client state."""
        if not self.client.is_configured:
            self.connection_status.setText("Not configured")
            self.connection_status.setStyleSheet("color: #f14c4c;")
        elif self.client.cache_timestamp:
            self.connection_status.setText(f"✓ {self.client.cache.site_name}")
            self.connection_status.setStyleSheet("color: #4ec9b0;")
        else:
            self.connection_status.setText("Ready to connect")
            self.connection_status.setStyleSheet("color: #f0c000;")

    def _on_open_config(self):
        """Open configuration dialog."""
        dialog = ConfigDialog(self.client, self)
        if dialog.exec():
            # Reload client with new config
            self.client = NetBoxClient.from_config()
            self._update_connection_status()
            self.btn_refresh.setEnabled(False)
            
            # Auto-connect if now configured
            if self.client.is_configured:
                reply = QMessageBox.question(
                    self,
                    "Connect Now?",
                    "Configuration saved. Connect to NetBox now?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes,
                )
                if reply == QMessageBox.Yes:
                    self._on_connect()

    def _set_busy(self, busy: bool, message: str = ""):
        """Set busy state (disable UI, show progress)."""
        self.btn_connect.setEnabled(not busy)
        self.btn_refresh.setEnabled(not busy and bool(self.client.cache.racks))
        self.btn_load.setEnabled(not busy)
        self.btn_validate.setEnabled(not busy and bool(self.csv_rows) and bool(self.client.cache.racks))
        self.btn_export.setEnabled(not busy and bool(self.validation_results))
        
        self.progress_bar.setVisible(busy)
        if busy:
            self.progress_bar.setRange(0, 0)  # Indeterminate
            self.status_bar.showMessage(message)

    def _log_activity(self, message: str):
        """Add a timestamped entry to the activity log."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.activity_log.append(f"[{timestamp}] {message}")
        # Auto-scroll to bottom
        self.activity_log.verticalScrollBar().setValue(
            self.activity_log.verticalScrollBar().maximum()
        )

    def _clear_activity_log(self):
        """Clear the activity log."""
        self.activity_log.clear()
        self._log_activity("Log cleared")

    def _on_clear_data(self):
        """Clear all loaded data and results."""
        if self.csv_rows or self.validation_results:
            reply = QMessageBox.question(
                self,
                "Clear Data",
                "Clear all loaded CSV data and validation results?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return
        
        self.csv_rows = []
        self.validation_results = []
        self.current_file = None
        
        self.file_label.setText("No file loaded")
        self.file_label.setStyleSheet("color: #888;")
        self.results_table.clear()
        
        self.btn_validate.setEnabled(False)
        self.btn_export.setEnabled(False)
        
        self._log_activity("🗑️ Data cleared")
        self._update_status()

    def _show_about(self):
        """Show the About dialog."""
        about_text = """
        <div style="text-align: center;">
        <h2>NetBox Trust Boundary</h2>
        <p style="color: #888;">Version 1.3.0</p>
        <hr>
        <p><b>A read-only validation layer that protects NetBox<br>
        from unsafe or unnecessary changes.</b></p>
        <hr>
        <p style="font-size: 11px; color: #888;">
        <b>What it does:</b><br>
        • Validates CSV device data against NetBox<br>
        • Detects RU collisions and position conflicts<br>
        • Checks import readiness for bulk operations<br>
        • Exports validated data for NetBox import
        </p>
        <hr>
        <p style="font-size: 10px; color: #666;">
        Built with Python 3 + PySide6 (Qt)<br>
        © 2026 FOX Broadcast Engineering
        </p>
        </div>
        """
        
        dialog = QDialog(self)
        dialog.setWindowTitle("About NetBox Trust Boundary")
        dialog.setFixedSize(380, 340)
        dialog.setStyleSheet("""
            QDialog {
                background-color: #252526;
            }
            QLabel {
                color: #cccccc;
            }
        """)
        
        layout = QVBoxLayout(dialog)
        
        # Logo
        icon_path = Path(__file__).parent.parent / "assets" / "logo.png"
        if icon_path.exists():
            logo_label = QLabel()
            pixmap = QPixmap(str(icon_path)).scaled(80, 80, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            logo_label.setPixmap(pixmap)
            logo_label.setAlignment(Qt.AlignCenter)
            layout.addWidget(logo_label)
        
        # About text
        text_label = QLabel(about_text)
        text_label.setWordWrap(True)
        text_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(text_label)
        
        # OK button
        button_box = QDialogButtonBox(QDialogButtonBox.Ok)
        button_box.accepted.connect(dialog.accept)
        button_box.setStyleSheet("""
            QPushButton {
                background-color: #0e639c;
                color: white;
                padding: 6px 20px;
                border-radius: 2px;
            }
            QPushButton:hover {
                background-color: #1177bb;
            }
        """)
        layout.addWidget(button_box)
        
        dialog.exec()
