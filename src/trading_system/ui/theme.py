from __future__ import annotations

from PySide6.QtWidgets import QApplication

APP_STYLESHEET = """
QMainWindow,
QWidget#centralShell,
QStackedWidget#pageStack {
    background: #08111f;
    color: #e8eef8;
}

QWidget {
    color: #dce5f3;
    font-family: "Segoe UI";
    font-size: 13px;
}

QToolTip {
    color: #eef4ff;
    background: #172337;
    border: 1px solid #30425e;
    padding: 6px;
}

QFrame#topStatusBar,
QFrame#bottomStatusBar {
    background: #0d1828;
    border-bottom: 1px solid #1e2d43;
}

QFrame#bottomStatusBar {
    border-top: 1px solid #1e2d43;
    border-bottom: none;
}

QFrame#sidebar {
    background: #0b1626;
    border-right: 1px solid #1e2d43;
}

QLabel#productName {
    color: #f4f7fc;
    font-size: 16px;
    font-weight: 700;
}

QLabel#productMark {
    color: #58a6ff;
    font-size: 20px;
    font-weight: 800;
}

QLabel#topProductName {
    color: #f4f7fc;
    font-size: 15px;
    font-weight: 700;
}

QLabel#topMeta,
QLabel#footerMeta,
QLabel#pageSubtitle,
QLabel#cardSubtitle,
QLabel#mutedText,
QLabel#jobMessage,
QLabel#dataJobMessage,
QLabel#dataSummary,
QLabel#tinvestTokenMessage {
    color: #8fa2bd;
}

QLabel#pageTitle {
    color: #f6f8fc;
    font-size: 28px;
    font-weight: 700;
}

QLabel#sectionTitle {
    color: #f0f4fb;
    font-size: 16px;
    font-weight: 650;
}

QLabel#metricTitle {
    color: #c8d3e4;
    font-size: 13px;
    font-weight: 600;
}

QLabel#metricValue {
    color: #f7f9fd;
    font-size: 24px;
    font-weight: 700;
}

QFrame#card,
QFrame#metricCard,
QFrame#sectionCard,
QFrame#emptyState {
    background: #101c2d;
    border: 1px solid #22334b;
    border-radius: 10px;
}

QFrame#metricCard:hover,
QFrame#sectionCard:hover {
    border-color: #314867;
}

QLabel#statusBadge,
QLabel[tone] {
    border-radius: 6px;
    padding: 3px 8px;
    font-size: 11px;
    font-weight: 700;
}

QLabel#statusBadge[tone="success"],
QLabel[tone="success"] {
    color: #52e39b;
    background: #103326;
    border: 1px solid #1d5a43;
}

QLabel#statusBadge[tone="warning"],
QLabel[tone="warning"] {
    color: #ffd166;
    background: #3a2d10;
    border: 1px solid #65501a;
}

QLabel#statusBadge[tone="danger"],
QLabel[tone="danger"] {
    color: #ff737d;
    background: #3b1820;
    border: 1px solid #672832;
}

QLabel#statusBadge[tone="info"],
QLabel[tone="info"] {
    color: #70b8ff;
    background: #102d4f;
    border: 1px solid #1f5185;
}

QLabel#statusBadge[tone="muted"],
QLabel[tone="muted"] {
    color: #9eafc5;
    background: #182437;
    border: 1px solid #2a3a51;
}

QListWidget#navigationList {
    background: transparent;
    border: none;
    outline: none;
    padding: 2px 0;
}

QListWidget#navigationList::item {
    color: #aebdd2;
    border-radius: 7px;
    margin: 2px 0;
    padding: 11px 12px;
}

QListWidget#navigationList::item:hover {
    background: #12243c;
    color: #e7eef9;
}

QListWidget#navigationList::item:selected {
    background: #173c75;
    color: #ffffff;
    border-left: 3px solid #3d8cff;
    padding-left: 9px;
}

QPushButton {
    color: #dce6f5;
    background: #152338;
    border: 1px solid #30435f;
    border-radius: 7px;
    padding: 8px 14px;
    min-height: 18px;
    font-weight: 600;
}

QPushButton:hover {
    background: #1b2d47;
    border-color: #436184;
}

QPushButton:pressed {
    background: #101c2d;
}

QPushButton:disabled {
    color: #65778f;
    background: #111b2a;
    border-color: #1b293c;
}

QPushButton[variant="primary"] {
    color: #ffffff;
    background: #2377ea;
    border-color: #3186f5;
}

QPushButton[variant="primary"]:hover {
    background: #2f86f5;
}

QPushButton[variant="danger"] {
    color: #ff7b84;
    background: #24151c;
    border-color: #a63a48;
}

QPushButton[variant="ghost"] {
    background: transparent;
    border-color: #2b3b52;
}

QComboBox,
QLineEdit {
    color: #e2e9f4;
    background: #0d1929;
    border: 1px solid #2b3d56;
    border-radius: 7px;
    padding: 7px 10px;
    min-height: 20px;
}

QComboBox:hover,
QLineEdit:hover,
QLineEdit:focus {
    border-color: #4770a3;
}

QComboBox::drop-down {
    border: none;
    width: 24px;
}

QCheckBox {
    spacing: 8px;
}

QProgressBar {
    color: transparent;
    background: #1a2940;
    border: none;
    border-radius: 5px;
    min-height: 10px;
    max-height: 10px;
}

QProgressBar::chunk {
    background: #3388ff;
    border-radius: 5px;
}

QTableWidget {
    color: #dce5f2;
    background: #0d1828;
    alternate-background-color: #101d2f;
    border: 1px solid #22334b;
    border-radius: 8px;
    gridline-color: #1c2c42;
    selection-background-color: #173c75;
    selection-color: #ffffff;
    outline: none;
}

QTableWidget::item {
    padding: 8px 7px;
    border-bottom: 1px solid #1a2a40;
}

QHeaderView::section {
    color: #94a8c3;
    background: #122035;
    border: none;
    border-bottom: 1px solid #263851;
    padding: 8px 7px;
    font-size: 11px;
    font-weight: 700;
}

QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 2px;
}

QScrollBar::handle:vertical {
    background: #31445f;
    border-radius: 4px;
    min-height: 28px;
}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0;
}

QStatusBar {
    background: #0d1828;
    color: #91a4be;
    border-top: 1px solid #1e2d43;
}
"""


def apply_theme(app: QApplication) -> None:
    """Apply the built-in dark workstation theme to the desktop application."""

    app.setStyle("Fusion")
    app.setStyleSheet(APP_STYLESHEET)
