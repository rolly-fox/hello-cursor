"""
Configuration dialog for NetBox connection settings.
"""

import os
from pathlib import Path
from typing import Optional

import yaml
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QLineEdit,
    QPushButton,
    QLabel,
    QGroupBox,
    QMessageBox,
    QTextEdit,
    QDialogButtonBox,
    QCheckBox,
)
from PySide6.QtCore import Qt

from core.netbox_client import NetBoxClient


class ConfigDialog(QDialog):
    """Dialog for configuring NetBox connection settings."""

    def __init__(self, client: NetBoxClient, parent=None):
        super().__init__(parent)
        self.client = client
        self.config_path = Path("config.yaml")
        
        self._setup_ui()
        self._load_current_config()

    def _setup_ui(self):
        """Set up dialog UI."""
        self.setWindowTitle("Connection Settings")
        self.setMinimumWidth(500)
        self.setModal(True)
        
        layout = QVBoxLayout(self)
        
        # NetBox settings group
        netbox_group = QGroupBox("NetBox Connection")
        group_layout = QVBoxLayout(netbox_group)
        
        # URL field
        url_label = QLabel("NetBox URL:")
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("https://netbox.example.com")
        url_help = QLabel("The base URL of your NetBox instance (no trailing slash)")
        url_help.setStyleSheet("color: #888; font-size: 11px;")
        group_layout.addWidget(url_label)
        group_layout.addWidget(self.url_input)
        group_layout.addWidget(url_help)
        group_layout.addSpacing(8)
        
        # Token field
        token_label = QLabel("API Token:")
        token_row = QHBoxLayout()
        self.token_input = QLineEdit()
        self.token_input.setPlaceholderText("Enter your API token")
        self.token_input.setEchoMode(QLineEdit.Password)
        token_row.addWidget(self.token_input)
        self.show_token_btn = QPushButton("Show")
        self.show_token_btn.setFixedWidth(60)
        self.show_token_btn.clicked.connect(self._toggle_token_visibility)
        token_row.addWidget(self.show_token_btn)
        token_help = QLabel("Generate at: NetBox → Admin → API Tokens (read-only is sufficient)")
        token_help.setStyleSheet("color: #888; font-size: 11px;")
        group_layout.addWidget(token_label)
        group_layout.addLayout(token_row)
        group_layout.addWidget(token_help)
        group_layout.addSpacing(8)
        
        # Site field
        site_label = QLabel("Site (ID or Slug):")
        self.site_input = QLineEdit()
        self.site_input.setPlaceholderText("e.g., 5 or los-angeles")
        site_help = QLabel("Enter site ID (from URL like /sites/5/) or slug (from site details page)")
        site_help.setStyleSheet("color: #888; font-size: 11px;")
        group_layout.addWidget(site_label)
        group_layout.addWidget(self.site_input)
        group_layout.addWidget(site_help)
        group_layout.addSpacing(8)
        
        # SSL verification checkbox
        self.verify_ssl_checkbox = QCheckBox("Verify SSL Certificate")
        self.verify_ssl_checkbox.setChecked(True)
        ssl_help = QLabel("Uncheck for internal/corporate CAs or self-signed certificates")
        ssl_help.setStyleSheet("color: #888; font-size: 11px;")
        group_layout.addWidget(self.verify_ssl_checkbox)
        group_layout.addWidget(ssl_help)
        
        layout.addWidget(netbox_group)
        
        # Test connection button
        test_layout = QHBoxLayout()
        self.test_btn = QPushButton("Test Connection")
        self.test_btn.clicked.connect(self._test_connection)
        test_layout.addWidget(self.test_btn)
        
        self.test_status = QLabel("")
        test_layout.addWidget(self.test_status)
        test_layout.addStretch()
        
        layout.addLayout(test_layout)
        
        # Environment variable info
        env_label = QLabel(
            "<i>Tip: You can also set NETBOX_URL, NETBOX_TOKEN, and NETBOX_SITE "
            "environment variables to override these settings.</i>"
        )
        env_label.setWordWrap(True)
        env_label.setStyleSheet("color: #888;")
        layout.addWidget(env_label)
        
        layout.addStretch()
        
        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)
        
        save_btn = QPushButton("Save")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._save_config)
        button_layout.addWidget(save_btn)
        
        layout.addLayout(button_layout)
        
        # Apply styles
        self.setStyleSheet("""
            QDialog {
                background-color: #252526;
            }
            QGroupBox {
                font-weight: bold;
                border: 1px solid #3c3c3c;
                border-radius: 4px;
                margin-top: 8px;
                padding: 12px;
                padding-top: 24px;
                background-color: #1e1e1e;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 4px;
                color: #cccccc;
            }
            QLineEdit {
                background-color: #3c3c3c;
                color: #cccccc;
                border: 1px solid #3c3c3c;
                padding: 6px;
                border-radius: 2px;
            }
            QLineEdit:focus {
                border-color: #007acc;
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
            QPushButton:hover {
                background-color: #1177bb;
            }
            QPushButton:pressed {
                background-color: #0d5a8c;
            }
        """)

    def _toggle_token_visibility(self):
        """Toggle token field visibility."""
        if self.token_input.echoMode() == QLineEdit.Password:
            self.token_input.setEchoMode(QLineEdit.Normal)
            self.show_token_btn.setText("Hide")
        else:
            self.token_input.setEchoMode(QLineEdit.Password)
            self.show_token_btn.setText("Show")

    def _load_current_config(self):
        """Load current configuration into form fields."""
        verify_ssl = True  # Default
        
        # Try to load from config file
        if self.config_path.exists():
            try:
                with open(self.config_path, "r") as f:
                    config = yaml.safe_load(f) or {}
                    netbox_config = config.get("netbox", {})
                    
                    self.url_input.setText(netbox_config.get("url", ""))
                    self.token_input.setText(netbox_config.get("token", ""))
                    self.site_input.setText(netbox_config.get("site", ""))
                    verify_ssl = netbox_config.get("verify_ssl", True)
            except Exception:
                pass
        
        # Override with current client values (may include env var overrides)
        if self.client.url:
            self.url_input.setText(self.client.url)
        if self.client.token:
            self.token_input.setText(self.client.token)
        if self.client.site_slug:
            self.site_input.setText(self.client.site_slug)
        if hasattr(self.client, 'verify_ssl'):
            verify_ssl = self.client.verify_ssl
        
        self.verify_ssl_checkbox.setChecked(verify_ssl)

    def _test_connection(self):
        """Test connection with current settings."""
        url = self.url_input.text().strip()
        token = self.token_input.text().strip()
        
        if not url or not token:
            self.test_status.setText("⚠ URL and token required")
            self.test_status.setStyleSheet("color: #f0c000;")
            return
        
        self.test_status.setText("Testing...")
        self.test_status.setStyleSheet("color: #cccccc;")
        self.test_btn.setEnabled(False)
        
        # Force UI update
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()
        
        try:
            verify_ssl = self.verify_ssl_checkbox.isChecked()
            test_client = NetBoxClient(url=url, token=token, verify_ssl=verify_ssl)
            success, message = test_client.test_connection()
            
            if success:
                self.test_status.setText(f"✓ {message}")
                self.test_status.setStyleSheet("color: #4ec9b0;")
            else:
                self.test_status.setText("✗ Failed (see details)")
                self.test_status.setStyleSheet("color: #f14c4c;")
                self._show_error_details("Connection Test Failed", message)
        except Exception as e:
            error_msg = str(e)
            self.test_status.setText("✗ Error (see details)")
            self.test_status.setStyleSheet("color: #f14c4c;")
            self._show_error_details("Connection Error", error_msg)
        finally:
            self.test_btn.setEnabled(True)

    def _show_error_details(self, title: str, message: str):
        """Show error details in a copyable dialog."""
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.setMinimumSize(500, 200)
        
        layout = QVBoxLayout(dialog)
        
        label = QLabel("Error details (you can copy this text):")
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
        
        dialog.exec()

    def _save_config(self):
        """Save configuration to file."""
        url = self.url_input.text().strip()
        token = self.token_input.text().strip()
        site = self.site_input.text().strip()
        
        if not url or not token:
            QMessageBox.warning(
                self,
                "Validation Error",
                "URL and API token are required.",
            )
            return
        
        verify_ssl = self.verify_ssl_checkbox.isChecked()
        
        config = {
            "netbox": {
                "url": url,
                "token": token,
                "site": site,
                "verify_ssl": verify_ssl,
            },
            "validation": {
                "naming_pattern": None,
            },
        }
        
        try:
            with open(self.config_path, "w") as f:
                yaml.dump(config, f, default_flow_style=False)
            
            QMessageBox.information(
                self,
                "Saved",
                f"Configuration saved to {self.config_path}",
            )
            self.accept()
            
        except Exception as e:
            QMessageBox.critical(
                self,
                "Save Error",
                f"Failed to save configuration: {e}",
            )
