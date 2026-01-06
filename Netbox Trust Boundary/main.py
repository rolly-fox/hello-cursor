#!/usr/bin/env python3
"""
NetBox Trust Boundary - Main Entry Point

A read-only validation layer that protects NetBox from unsafe or unnecessary changes.
Validates CSV device/rack data against NetBox before import.
"""

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont, QIcon

from ui.main_window import MainWindow


def main():
    """Run the NetBox Trust Boundary application."""
    # Windows taskbar icon fix - must be set before QApplication
    try:
        import ctypes
        # Set app user model ID so Windows uses our icon in taskbar
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "fox.netbox.trustboundary.1.3.0"
        )
    except (ImportError, AttributeError, OSError):
        pass  # Not Windows or failed - continue anyway
    
    app = QApplication(sys.argv)
    
    # Set application metadata
    app.setApplicationName("NetBox Trust Boundary")
    app.setOrganizationName("FOX Broadcast Engineering")
    app.setApplicationVersion("1.4.0")
    
    # Set application icon (appears in taskbar)
    icon_path = Path(__file__).parent / "assets" / "logo.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    
    # Set default font
    font = QFont("Segoe UI", 9)
    app.setFont(font)
    
    # Create and show main window
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
