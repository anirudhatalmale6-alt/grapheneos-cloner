"""
GrapheneOS Cloner - Main Application
Windows desktop GUI for cloning Pixel 3 devices running GrapheneOS.
"""
import sys
import os

from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QIcon, QFont
from PyQt5.QtCore import Qt

from gui import MainWindow
from config import APP_NAME


def main():
    # High DPI support
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")

    # Set global font
    font = QFont("Segoe UI", 10)
    app.setFont(font)

    # Apply dark theme stylesheet
    app.setStyleSheet(get_stylesheet())

    window = MainWindow()
    window.show()

    sys.exit(app.exec_())


def get_stylesheet():
    return """
    /* ===== GLOBAL ===== */
    QWidget {
        background-color: #1a1a2e;
        color: #e0e0e0;
    }

    QMainWindow {
        background-color: #1a1a2e;
    }

    /* ===== TOP BAR ===== */
    #topBar {
        background-color: #16213e;
        border-bottom: 2px solid #0f3460;
        padding: 8px;
    }

    #appTitle {
        color: #00d2ff;
        font-size: 18px;
        font-weight: bold;
    }

    #appSubtitle {
        color: #8899aa;
        font-size: 11px;
    }

    /* ===== SIDEBAR ===== */
    #sidebar {
        background-color: #16213e;
        border-right: 2px solid #0f3460;
        min-width: 200px;
        max-width: 200px;
    }

    #sidebarBtn {
        background-color: transparent;
        border: none;
        border-radius: 8px;
        color: #8899aa;
        font-size: 13px;
        font-weight: 500;
        text-align: left;
        padding: 12px 16px;
        margin: 2px 8px;
    }

    #sidebarBtn:hover {
        background-color: #0f3460;
        color: #e0e0e0;
    }

    #sidebarBtn[active="true"] {
        background-color: #0f3460;
        color: #00d2ff;
        border-left: 3px solid #00d2ff;
    }

    /* ===== CARDS ===== */
    #card {
        background-color: #16213e;
        border: 1px solid #0f3460;
        border-radius: 12px;
        padding: 20px;
    }

    #cardTitle {
        color: #00d2ff;
        font-size: 16px;
        font-weight: bold;
    }

    #cardSubtitle {
        color: #8899aa;
        font-size: 12px;
    }

    /* ===== BUTTONS ===== */
    QPushButton {
        background-color: #0f3460;
        color: #e0e0e0;
        border: 1px solid #1a4a8a;
        border-radius: 8px;
        padding: 10px 20px;
        font-size: 13px;
        font-weight: 500;
    }

    QPushButton:hover {
        background-color: #1a4a8a;
        border-color: #00d2ff;
    }

    QPushButton:pressed {
        background-color: #0a2a50;
    }

    QPushButton:disabled {
        background-color: #1a1a2e;
        color: #555;
        border-color: #333;
    }

    #primaryBtn {
        background-color: #00d2ff;
        color: #1a1a2e;
        border: none;
        font-weight: bold;
        font-size: 14px;
        padding: 12px 24px;
    }

    #primaryBtn:hover {
        background-color: #33ddff;
    }

    #primaryBtn:pressed {
        background-color: #00aacc;
    }

    #primaryBtn:disabled {
        background-color: #334455;
        color: #666;
    }

    #dangerBtn {
        background-color: #e74c3c;
        color: white;
        border: none;
    }

    #dangerBtn:hover {
        background-color: #ff6b5a;
    }

    #successBtn {
        background-color: #2ecc71;
        color: #1a1a2e;
        border: none;
        font-weight: bold;
    }

    #successBtn:hover {
        background-color: #45e088;
    }

    /* ===== PROGRESS BAR ===== */
    QProgressBar {
        border: 1px solid #0f3460;
        border-radius: 6px;
        background-color: #1a1a2e;
        text-align: center;
        color: #e0e0e0;
        font-size: 11px;
        height: 24px;
    }

    QProgressBar::chunk {
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 #00d2ff, stop:1 #0f3460);
        border-radius: 5px;
    }

    /* ===== LIST WIDGET ===== */
    QListWidget {
        background-color: #1a1a2e;
        border: 1px solid #0f3460;
        border-radius: 8px;
        padding: 4px;
        outline: none;
    }

    QListWidget::item {
        color: #e0e0e0;
        padding: 8px 12px;
        border-radius: 4px;
    }

    QListWidget::item:selected {
        background-color: #0f3460;
        color: #00d2ff;
    }

    QListWidget::item:hover {
        background-color: #0f3460;
    }

    /* ===== CHECKBOX ===== */
    QCheckBox {
        color: #e0e0e0;
        spacing: 8px;
    }

    QCheckBox::indicator {
        width: 18px;
        height: 18px;
        border-radius: 4px;
        border: 2px solid #0f3460;
        background-color: #1a1a2e;
    }

    QCheckBox::indicator:checked {
        background-color: #00d2ff;
        border-color: #00d2ff;
    }

    /* ===== COMBO BOX ===== */
    QComboBox {
        background-color: #1a1a2e;
        color: #e0e0e0;
        border: 1px solid #0f3460;
        border-radius: 6px;
        padding: 8px 12px;
        font-size: 12px;
    }

    QComboBox::drop-down {
        border: none;
        width: 30px;
    }

    QComboBox QAbstractItemView {
        background-color: #16213e;
        color: #e0e0e0;
        border: 1px solid #0f3460;
        selection-background-color: #0f3460;
    }

    /* ===== LINE EDIT ===== */
    QLineEdit {
        background-color: #1a1a2e;
        color: #e0e0e0;
        border: 1px solid #0f3460;
        border-radius: 6px;
        padding: 8px 12px;
        font-size: 12px;
    }

    QLineEdit:focus {
        border-color: #00d2ff;
    }

    /* ===== TEXT EDIT / LOG ===== */
    QTextEdit, QPlainTextEdit {
        background-color: #0d0d1a;
        color: #a0d0a0;
        border: 1px solid #0f3460;
        border-radius: 8px;
        padding: 8px;
        font-family: "Consolas", "Courier New", monospace;
        font-size: 11px;
    }

    /* ===== SCROLL BAR ===== */
    QScrollBar:vertical {
        background-color: #1a1a2e;
        width: 10px;
        border-radius: 5px;
    }

    QScrollBar::handle:vertical {
        background-color: #0f3460;
        border-radius: 5px;
        min-height: 30px;
    }

    QScrollBar::handle:vertical:hover {
        background-color: #1a4a8a;
    }

    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
        height: 0px;
    }

    /* ===== TAB WIDGET ===== */
    QTabWidget::pane {
        border: 1px solid #0f3460;
        border-radius: 8px;
        background-color: #16213e;
    }

    QTabBar::tab {
        background-color: #1a1a2e;
        color: #8899aa;
        border: 1px solid #0f3460;
        border-bottom: none;
        border-top-left-radius: 8px;
        border-top-right-radius: 8px;
        padding: 8px 16px;
        margin-right: 2px;
    }

    QTabBar::tab:selected {
        background-color: #16213e;
        color: #00d2ff;
    }

    /* ===== GROUP BOX ===== */
    QGroupBox {
        border: 1px solid #0f3460;
        border-radius: 8px;
        margin-top: 12px;
        padding-top: 16px;
        font-weight: bold;
        color: #00d2ff;
    }

    QGroupBox::title {
        subcontrol-origin: margin;
        subcontrol-position: top left;
        padding: 0 8px;
    }

    /* ===== LABEL ===== */
    #statusLabel {
        color: #8899aa;
        font-size: 12px;
    }

    #headerLabel {
        color: #e0e0e0;
        font-size: 22px;
        font-weight: bold;
    }

    /* ===== DEVICE CARD ===== */
    #deviceCard {
        background-color: #16213e;
        border: 1px solid #0f3460;
        border-radius: 10px;
        padding: 16px;
    }

    #deviceCard[connected="true"] {
        border-color: #2ecc71;
    }

    #deviceName {
        color: #e0e0e0;
        font-size: 14px;
        font-weight: bold;
    }

    #deviceSerial {
        color: #8899aa;
        font-size: 11px;
    }

    #deviceStatus {
        color: #2ecc71;
        font-size: 12px;
        font-weight: bold;
    }

    /* ===== SEPARATOR ===== */
    #separator {
        background-color: #0f3460;
        max-height: 1px;
        min-height: 1px;
    }

    /* ===== TOOLTIP ===== */
    QToolTip {
        background-color: #16213e;
        color: #e0e0e0;
        border: 1px solid #0f3460;
        padding: 6px;
        border-radius: 4px;
    }
    """


if __name__ == "__main__":
    main()
