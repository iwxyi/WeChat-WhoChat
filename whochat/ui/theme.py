from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication


def apply_app_theme(app: QApplication) -> None:
    family = _load_preferred_font()
    font = QFont(family, 10)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    app.setFont(font)
    app.setStyleSheet(STYLESHEET)


def _load_preferred_font() -> str:
    candidates = [
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/Deng.ttf"),
        Path("C:/Windows/Fonts/simhei.ttf"),
        Path("C:/Windows/Fonts/simsun.ttc"),
    ]
    for font_path in candidates:
        if not font_path.exists():
            continue
        font_id = QFontDatabase.addApplicationFont(str(font_path))
        if font_id < 0:
            continue
        families = QFontDatabase.applicationFontFamilies(font_id)
        if families:
            return families[0]
    return "Arial"


STYLESHEET = """
QWidget {
  color: #1f2933;
  background: #f6f7f9;
  font-size: 12px;
}
QMainWindow {
  background: #f6f7f9;
}
QFrame#Sidebar {
  background: #20262e;
  border: none;
}
QLabel#BrandMark {
  color: #ffffff;
  font-size: 18px;
  font-weight: 700;
  background: transparent;
}
QLabel#BrandSub {
  color: #aeb7c2;
  background: transparent;
  font-size: 11px;
}
QPushButton#NavButton {
  color: #cfd6de;
  background: transparent;
  border: none;
  border-radius: 6px;
  padding: 7px 9px;
  text-align: left;
}
QPushButton#NavButton:hover {
  background: #2b333d;
  color: #ffffff;
}
QPushButton#NavButton[active="true"] {
  background: #e7f4f1;
  color: #0d5f56;
  font-weight: 700;
}
QFrame#TopBar, QFrame#RightRail, QFrame#PagePanel, QFrame#MetricCard, QFrame#FloatingRoot {
  background: #ffffff;
  border: 1px solid #e4e7eb;
  border-radius: 8px;
}
QFrame#ActionBanner {
  background: #f8fbfa;
  border: 1px solid #d7ebe7;
  border-radius: 7px;
}
QLabel#ActionPrimary {
  color: #12312d;
  background: transparent;
  font-size: 13px;
  font-weight: 700;
}
QFrame#FloatingRoot {
  background: #fbfcfd;
  border: 1px solid #cbd5df;
  border-radius: 7px;
}
QLabel#FloatingContact {
  color: #102a43;
  background: transparent;
  font-size: 13px;
  font-weight: 700;
}
QLabel#FloatingStatus {
  color: #697586;
  background: transparent;
  font-size: 11px;
}
QLabel#FloatingBadge {
  color: #0d5f56;
  background: #e7f4f1;
  border-radius: 5px;
  padding: 3px 8px;
  font-size: 11px;
  font-weight: 700;
}
QPushButton#FloatingGhostButton {
  color: #52606d;
  background: transparent;
  border: 1px solid #d9e2ec;
  border-radius: 5px;
  padding: 5px 10px;
  font-size: 12px;
}
QPushButton#FloatingSuggestionButton {
  color: #102a43;
  background: #ffffff;
  border: 1px solid #d9e2ec;
  border-radius: 6px;
  padding: 8px 10px;
  text-align: left;
  font-size: 12px;
}
QPushButton#FloatingSuggestionButton:hover {
  border-color: #0f766e;
  background: #f1fbf8;
}
QFrame#TopBar {
  border-radius: 0;
  border-left: none;
  border-right: none;
  border-top: none;
}
QLabel#PageTitle {
  font-size: 18px;
  font-weight: 700;
  color: #121821;
  background: transparent;
}
QLabel#SectionTitle {
  font-size: 14px;
  font-weight: 700;
  color: #17212f;
  background: transparent;
}
QLabel#Muted {
  color: #697586;
  background: transparent;
}
QLabel#TinyMuted {
  color: #7b8794;
  font-size: 11px;
  background: transparent;
}
QLabel#MetricValue {
  color: #102a43;
  font-size: 18px;
  font-weight: 700;
  background: transparent;
}
QLabel#Badge {
  color: #0d5f56;
  background: #e7f4f1;
  border-radius: 6px;
  padding: 3px 7px;
  font-weight: 600;
}
QPushButton {
  background: #ffffff;
  border: 1px solid #cbd2d9;
  border-radius: 6px;
  padding: 5px 9px;
}
QPushButton:hover {
  border-color: #6fb3aa;
  background: #f7fbfa;
}
QPushButton#PrimaryButton {
  color: #ffffff;
  background: #0f766e;
  border: 1px solid #0f766e;
  font-weight: 700;
}
QPushButton#PrimaryButton:hover {
  background: #0d5f56;
}
QPushButton#DangerButton {
  color: #9f1239;
  border-color: #fecdd3;
  background: #fff1f2;
}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit, QPlainTextEdit {
  background: #ffffff;
  border: 1px solid #cbd2d9;
  border-radius: 6px;
  padding: 4px 7px;
  selection-background-color: #bde7df;
}
QTextEdit, QPlainTextEdit {
  padding: 6px;
}
QTableWidget, QListWidget {
  background: #ffffff;
  border: 1px solid #e4e7eb;
  border-radius: 8px;
  gridline-color: #edf0f2;
}
QHeaderView::section {
  background: #f4f6f8;
  color: #52606d;
  border: none;
  border-bottom: 1px solid #e4e7eb;
  padding: 4px;
  font-weight: 700;
}
QTabWidget::pane {
  border: 1px solid #e4e7eb;
  border-radius: 8px;
  background: #ffffff;
}
QTabBar::tab {
  background: transparent;
  padding: 6px 10px;
  color: #52606d;
}
QTabBar::tab:selected {
  color: #0f766e;
  font-weight: 700;
}
QScrollArea {
  border: none;
}
QSlider::groove:horizontal {
  height: 4px;
  background: #d9e2ec;
  border-radius: 2px;
}
QSlider::handle:horizontal {
  width: 16px;
  height: 16px;
  margin: -6px 0;
  border-radius: 8px;
  background: #0f766e;
}
"""
