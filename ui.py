"""ui.py - PySide6 desktop GUI for CIDM with Modern Dark-Grey & Light Themes."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from typing import Any, Dict, List, Optional

# Ensure Windows Taskbar associates process with CIDM custom icon
if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "cidm.downloadmanager.desktop.1.0"
        )
    except Exception:
        pass

from PySide6.QtCore import (  # type: ignore[import-not-found]
    QDate,
    QDateTime,
    QPoint,
    QRect,
    QRectF,
    QSettings,
    QSize,
    Qt,
    QThread,
    QTime,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import (  # type: ignore[import-not-found]
    QAction,
    QBrush,
    QColor,
    QDesktopServices,
    QIcon,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
)
from PySide6.QtWidgets import (  # type: ignore[import-not-found]
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QStyle,
    QSystemTrayIcon,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QTimeEdit,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from engine import (
    DEFAULT_USER_AGENT,
    DownloadError,
    DownloadTask,
    MediaDownloadTask,
    QualityOption,
    Status,
    apply_engine_settings,
    calculate_file_checksum,
    check_same_subnet,
    create_task,
    execute_system_action,
    filename_from_url,
    find_ffmpeg,
    format_size,
    format_speed,
    get_active_interfaces,
    get_category_for_filename,
    is_hls_url,
    is_media_url,
    probe_media,
    probe_url,
    resolve_destination_folder,
    resolve_file_conflict,
    resolve_media_format_selector,
    sanitize_filename,
    task_from_dict,
)
from grabber import GrabbedItem, PRESET_EXTENSIONS, SiteGrabber

QUEUE_PATH = os.path.join(os.path.expanduser("~"), ".cidm", "queue.json")
_LEGACY_QUEUE = os.path.join(os.path.expanduser("~"), ".pyidm", "queue.json")
if not os.path.exists(QUEUE_PATH) and os.path.exists(_LEGACY_QUEUE):
    QUEUE_PATH = _LEGACY_QUEUE

SETTINGS_PATH = os.path.join(os.path.expanduser("~"), ".cidm", "settings.json")
_LEGACY_SETTINGS = os.path.join(
    os.path.expanduser("~"), ".pyidm", "settings.json")
if not os.path.exists(SETTINGS_PATH) and os.path.exists(_LEGACY_SETTINGS):
    SETTINGS_PATH = _LEGACY_SETTINGS

# --------------------------------------------------------------------------- #
# Stylesheets (Neutral Charcoal / Slate Grey & Clean Light)
# --------------------------------------------------------------------------- #
DARK_GREY_QSS = """
* {
    font-family: "Segoe UI", "Inter", -apple-system, BlinkMacSystemFont, "Helvetica Neue", Arial, sans-serif;
    font-size: 12px;
    color: #e6e8ec;
}
QMainWindow, QDialog, QWidget#centralWrapper {
    background-color: #18191c;
    color: #e6e8ec;
}
QToolBar {
    background: #202226;
    border: none;
    border-bottom: 1px solid #33373e;
    padding: 4px 8px;
    spacing: 3px;
}
QToolBar::separator {
    background: #33373e;
    width: 1px;
    margin: 4px 4px;
}
QToolButton {
    background: transparent;
    color: #e6e8ec;
    border: 1px solid transparent;
    border-radius: 5px;
    padding: 4px 6px;
    font-size: 12px;
    font-weight: 500;
}
QToolButton:hover {
    background: #282b30;
    border-color: #3a3f47;
}
QToolButton:pressed {
    background: #4f86c6;
    color: #ffffff;
}
QToolButton:disabled {
    color: #5a606a;
}
QToolButton#primaryAddBtn {
    background-color: #4f86c6;
    color: #ffffff;
    font-weight: 600;
    font-size: 12px;
    border: 1px solid #5f96d6;
    border-radius: 5px;
    padding: 4px 9px;
}
QToolButton#primaryAddBtn:hover {
    background-color: #5f96d6;
    border-color: #70a5e5;
}
QToolButton#primaryAddBtn:pressed {
    background-color: #3b71ad;
}
QLineEdit#navSearchEdit {
    background-color: #18191c;
    color: #e6e8ec;
    border: 1px solid #33373e;
    border-radius: 12px;
    padding: 3px 9px;
    font-size: 11px;
    selection-background-color: #4f86c6;
}
QLineEdit#navSearchEdit:focus {
    border: 1px solid #4f86c6;
    background-color: #202226;
}
QPushButton#speedLimiterBtn {
    background-color: #282b30;
    color: #9aa0aa;
    border: 1px solid #33373e;
    border-radius: 11px;
    padding: 3px 9px;
    font-size: 11px;
    font-weight: 500;
}
QPushButton#speedLimiterBtn:hover {
    background-color: #32363e;
    color: #e6e8ec;
    border-color: #454a54;
}
QWidget#threadsPill {
    background-color: #282b30;
    border: 1px solid #33373e;
    border-radius: 11px;
    padding: 0px 4px;
}
QSpinBox#threadSpin {
    background: transparent;
    border: none;
    color: #e6e8ec;
    font-size: 11px;
    font-weight: 500;
    padding: 2px 1px;
}
QSpinBox#threadSpin:focus {
    border: none;
}
QStatusBar {
    background: #202226;
    color: #9aa0aa;
    border-top: 1px solid #33373e;
    padding: 2px 10px;
    font-size: 11px;
}
QStatusBar::item {
    border: none;
}
QListWidget#sidebar {
    background-color: #202226;
    border: 1px solid #33373e;
    border-radius: 6px;
    outline: 0;
    padding: 4px;
}
QListWidget#sidebar::item {
    color: #9aa0aa;
    padding: 6px 8px;
    border-radius: 5px;
    margin: 1px 0px;
    font-size: 12px;
    font-weight: 500;
}
QListWidget#sidebar::item:hover {
    background: #282b30;
    color: #e6e8ec;
}
QListWidget#sidebar::item:selected {
    background: #32363e;
    color: #ffffff;
    font-weight: 600;
}
QTableWidget {
    background-color: #18191c;
    alternate-background-color: #1e2024;
    border: 1px solid #33373e;
    border-radius: 6px;
    gridline-color: transparent;
    selection-background-color: #32363e;
    selection-color: #ffffff;
    outline: 0;
}
QTableWidget::item {
    padding: 3px 8px;
    border: none;
    color: #e6e8ec;
    font-size: 12px;
}
QTableWidget::item:hover {
    background-color: #262930;
}
QTableWidget::item:selected {
    background-color: #32363e;
    color: #ffffff;
}
QHeaderView::section {
    background-color: #202226;
    color: #9aa0aa;
    border: none;
    border-right: 1px solid #2d3138;
    border-bottom: 1px solid #33373e;
    padding: 6px 10px;
    font-size: 11px;
    font-weight: 600;
}
QLineEdit, QSpinBox, QComboBox, QTimeEdit, QTextEdit {
    background-color: #282b30;
    color: #e6e8ec;
    border: 1px solid #33373e;
    border-radius: 5px;
    padding: 5px 8px;
    font-size: 12px;
    selection-background-color: #4f86c6;
}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QTimeEdit:focus, QTextEdit:focus {
    border-color: #4f86c6;
}
QLineEdit:read-only {
    background-color: #202226;
    color: #9aa0aa;
}
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 20px;
    border-left: none;
}
QComboBox QAbstractItemView {
    background-color: #282b30;
    color: #e6e8ec;
    border: 1px solid #33373e;
    selection-background-color: #4f86c6;
    outline: 0;
}
QPushButton {
    background-color: #282b30;
    color: #e6e8ec;
    border: 1px solid #33373e;
    border-radius: 5px;
    padding: 5px 12px;
    font-size: 12px;
    font-weight: 500;
}
QPushButton:hover {
    background-color: #32363e;
    border-color: #4f86c6;
}
QPushButton:pressed {
    background-color: #4f86c6;
    color: #ffffff;
}
QPushButton:default, QPushButton#primaryBtn, QPushButton#speedLimiterBtn[active="true"] {
    background-color: #4f86c6;
    border: 1px solid #4f86c6;
    color: #ffffff;
    font-weight: 600;
}
QPushButton:default:hover, QPushButton#primaryBtn:hover, QPushButton#speedLimiterBtn[active="true"]:hover {
    background-color: #5f96d6;
    border-color: #5f96d6;
}
QProgressBar {
    background-color: #141518;
    border: 1px solid #33373e;
    border-radius: 4px;
    text-align: center;
    color: #ffffff;
    min-height: 14px;
    max-height: 16px;
    font-size: 10px;
    font-weight: 600;
}
QProgressBar::chunk {
    background-color: #4f86c6;
    border-radius: 3px;
}
QProgressBar[state="done"]::chunk {
    background-color: #4ea876;
}
QProgressBar[state="error"]::chunk {
    background-color: #cf5c5c;
}
QProgressBar[state="paused"]::chunk {
    background-color: #c99a45;
}
QGroupBox {
    background-color: #202226;
    border: 1px solid #33373e;
    border-radius: 6px;
    margin-top: 10px;
    padding: 16px 10px 8px 10px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 6px;
    color: #9aa0aa;
    font-size: 11px;
    font-weight: 600;
}
QTabWidget::pane {
    border: 1px solid #33373e;
    background: #202226;
    border-radius: 5px;
}
QTabBar::tab {
    background: #18191c;
    color: #9aa0aa;
    border: 1px solid #33373e;
    border-bottom: none;
    padding: 6px 14px;
    font-size: 12px;
    border-top-left-radius: 5px;
    border-top-right-radius: 5px;
    margin-right: 2px;
}
QTabBar::tab:selected {
    background: #202226;
    color: #4f86c6;
    font-weight: 600;
}
QTabBar::tab:hover:!selected {
    background: #282b30;
    color: #e6e8ec;
}
QWidget#threadsPill {
    background-color: #202226;
    border: 1px solid #33373e;
    border-radius: 5px;
    padding: 2px 4px;
}
QScrollArea {
    border: none;
    background: transparent;
}
QScrollBar:vertical {
    background: #18191c;
    width: 8px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #33373e;
    border-radius: 4px;
    min-height: 20px;
}
QScrollBar::handle:vertical:hover {
    background: #4f86c6;
}
QScrollBar::add-line, QScrollBar::sub-line {
    height: 0;
    width: 0;
}
QScrollBar:horizontal {
    background: #18191c;
    height: 10px;
    margin: 0;
}
QScrollBar::handle:horizontal {
    background: #33373e;
    border-radius: 5px;
    min-width: 24px;
}
QScrollBar::handle:horizontal:hover {
    background: #4f86c6;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    height: 0;
    width: 0;
}
QSplitter::handle {
    background: transparent;
}
QMenu {
    background: #282b30;
    color: #e6e8ec;
    border: 1px solid #33373e;
    border-radius: 6px;
    padding: 4px;
}
QMenu::item {
    padding: 6px 24px 6px 12px;
    border-radius: 4px;
}
QMenu::item:selected {
    background: #4f86c6;
    color: #ffffff;
}
QMenu::separator {
    height: 1px;
    background: #33373e;
    margin: 4px 8px;
}
QToolTip {
    background: #282b30;
    color: #e6e8ec;
    border: 1px solid #33373e;
    padding: 4px 8px;
}
QCheckBox {
    color: #e6e8ec;
    spacing: 7px;
}
QCheckBox::indicator {
    width: 15px;
    height: 15px;
    border: 1px solid #444952;
    border-radius: 4px;
    background: #282b30;
}
QCheckBox::indicator:hover {
    border-color: #4f86c6;
}
QCheckBox::indicator:checked {
    background: #4f86c6;
    border-color: #4f86c6;
}
"""

LIGHT_QSS = """
* {
    font-family: "Segoe UI", "Inter", -apple-system, BlinkMacSystemFont, "Helvetica Neue", Arial, sans-serif;
    font-size: 12px;
    color: #1f2937;
}
QMainWindow, QDialog, QWidget#centralWrapper {
    background-color: #f3f4f6;
    color: #1f2937;
}
QToolBar {
    background: #ffffff;
    border: none;
    border-bottom: 1px solid #e5e7eb;
    padding: 4px 8px;
    spacing: 3px;
}
QToolBar::separator {
    background: #e5e7eb;
    width: 1px;
    margin: 4px 4px;
}
QToolButton {
    background: transparent;
    color: #1f2937;
    border: 1px solid transparent;
    border-radius: 5px;
    padding: 4px 6px;
    font-size: 12px;
    font-weight: 500;
}
QToolButton:hover {
    background: #f3f4f6;
    border-color: #d1d5db;
}
QToolButton:pressed {
    background: #2563eb;
    color: #ffffff;
}
QToolButton:disabled {
    color: #9ca3af;
}
QToolButton#primaryAddBtn {
    background-color: #2563eb;
    color: #ffffff;
    font-weight: 600;
    font-size: 12px;
    border: 1px solid #1d4ed8;
    border-radius: 5px;
    padding: 4px 9px;
}
QToolButton#primaryAddBtn:hover {
    background-color: #3b82f6;
    border-color: #2563eb;
}
QToolButton#primaryAddBtn:pressed {
    background-color: #1d4ed8;
}
QLineEdit#navSearchEdit {
    background-color: #f8fafc;
    color: #1e293b;
    border: 1px solid #cbd5e1;
    border-radius: 12px;
    padding: 3px 9px;
    font-size: 11px;
    selection-background-color: #2563eb;
}
QLineEdit#navSearchEdit:focus {
    border: 1px solid #2563eb;
    background-color: #ffffff;
}
QPushButton#speedLimiterBtn {
    background-color: #f1f5f9;
    color: #64748b;
    border: 1px solid #cbd5e1;
    border-radius: 11px;
    padding: 3px 9px;
    font-size: 11px;
    font-weight: 500;
}
QPushButton#speedLimiterBtn:hover {
    background-color: #e2e8f0;
    color: #1e293b;
    border-color: #94a3b8;
}
QWidget#threadsPill {
    background-color: #f1f5f9;
    border: 1px solid #cbd5e1;
    border-radius: 11px;
    padding: 0px 4px;
}
QSpinBox#threadSpin {
    background: transparent;
    border: none;
    color: #1e293b;
    font-size: 11px;
    font-weight: 500;
    padding: 2px 1px;
}
QSpinBox#threadSpin:focus {
    border: none;
}
QStatusBar {
    background: #ffffff;
    color: #4b5563;
    border-top: 1px solid #e5e7eb;
    padding: 2px 10px;
    font-size: 11px;
}
QStatusBar::item {
    border: none;
}
QListWidget#sidebar {
    background-color: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 6px;
    outline: 0;
    padding: 4px;
}
QListWidget#sidebar::item {
    color: #4b5563;
    padding: 6px 8px;
    border-radius: 5px;
    margin: 1px 0px;
    font-size: 12px;
    font-weight: 500;
}
QListWidget#sidebar::item:hover {
    background: #f3f4f6;
    color: #111827;
}
QListWidget#sidebar::item:selected {
    background: #eff6ff;
    color: #1d4ed8;
    font-weight: 600;
}
QTableWidget {
    background-color: #ffffff;
    alternate-background-color: #f9fafb;
    border: 1px solid #e5e7eb;
    border-radius: 6px;
    gridline-color: transparent;
    selection-background-color: #eff6ff;
    selection-color: #1e3a8a;
    outline: 0;
}
QTableWidget::item {
    padding: 3px 8px;
    border: none;
    color: #1f2937;
    font-size: 12px;
}
QTableWidget::item:hover {
    background-color: #f3f4f6;
}
QTableWidget::item:selected {
    background-color: #eff6ff;
    color: #1e3a8a;
}
QHeaderView::section {
    background-color: #f9fafb;
    color: #4b5563;
    border: none;
    border-right: 1px solid #e5e7eb;
    border-bottom: 1px solid #e5e7eb;
    padding: 6px 10px;
    font-size: 11px;
    font-weight: 600;
}
QLineEdit, QSpinBox, QComboBox, QTimeEdit, QTextEdit {
    background-color: #ffffff;
    color: #1f2937;
    border: 1px solid #d1d5db;
    border-radius: 5px;
    padding: 5px 8px;
    font-size: 12px;
    selection-background-color: #2563eb;
}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QTimeEdit:focus, QTextEdit:focus {
    border-color: #2563eb;
}
QLineEdit:read-only {
    background-color: #f9fafb;
    color: #6b7280;
}
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 20px;
    border-left: none;
}
QComboBox QAbstractItemView {
    background-color: #ffffff;
    color: #1f2937;
    border: 1px solid #d1d5db;
    selection-background-color: #2563eb;
    outline: 0;
}
QPushButton {
    background-color: #ffffff;
    color: #1f2937;
    border: 1px solid #d1d5db;
    border-radius: 5px;
    padding: 5px 12px;
    font-size: 12px;
    font-weight: 500;
}
QPushButton:hover {
    background-color: #f3f4f6;
    border-color: #9ca3af;
}
QPushButton:pressed {
    background-color: #2563eb;
    color: #ffffff;
}
QPushButton:default, QPushButton#primaryBtn, QPushButton#speedLimiterBtn[active="true"] {
    background-color: #2563eb;
    border: 1px solid #2563eb;
    color: #ffffff;
    font-weight: 600;
}
QPushButton:default:hover, QPushButton#primaryBtn:hover, QPushButton#speedLimiterBtn[active="true"]:hover {
    background-color: #1d4ed8;
    border-color: #1d4ed8;
}
QProgressBar {
    background-color: #e5e7eb;
    border: 1px solid #d1d5db;
    border-radius: 4px;
    text-align: center;
    color: #111827;
    min-height: 14px;
    max-height: 16px;
    font-size: 10px;
    font-weight: 600;
}
QProgressBar::chunk {
    background-color: #2563eb;
    border-radius: 3px;
}
QProgressBar[state="done"]::chunk {
    background-color: #16a34a;
}
QProgressBar[state="error"]::chunk {
    background-color: #dc2626;
}
QProgressBar[state="paused"]::chunk {
    background-color: #d97706;
}
QWidget#threadsPill {
    background-color: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 5px;
    padding: 2px 4px;
}
QGroupBox {
    background-color: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 6px;
    margin-top: 10px;
    padding: 16px 10px 8px 10px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 6px;
    color: #4b5563;
    font-size: 11px;
    font-weight: 600;
}
QTabWidget::pane {
    border: 1px solid #e5e7eb;
    background: #ffffff;
    border-radius: 5px;
}
QTabBar::tab {
    background: #f3f4f6;
    color: #6b7280;
    border: 1px solid #e5e7eb;
    border-bottom: none;
    padding: 6px 14px;
    font-size: 12px;
    border-top-left-radius: 5px;
    border-top-right-radius: 5px;
    margin-right: 2px;
}
QTabBar::tab:selected {
    background: #ffffff;
    color: #2563eb;
    font-weight: 600;
}
QTabBar::tab:hover:!selected {
    background: #e5e7eb;
    color: #111827;
}
QScrollArea {
    border: none;
    background: transparent;
}
QScrollBar:vertical {
    background: #f9fafb;
    width: 8px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #d1d5db;
    border-radius: 4px;
    min-height: 20px;
}
QScrollBar::handle:vertical:hover {
    background: #9ca3af;
}
QScrollBar::add-line, QScrollBar::sub-line {
    height: 0;
    width: 0;
}
QSplitter::handle {
    background: transparent;
}
QMenu {
    background: #ffffff;
    color: #1f2937;
    border: 1px solid #d1d5db;
    border-radius: 6px;
    padding: 4px;
}
QMenu::item {
    padding: 6px 24px 6px 12px;
    border-radius: 4px;
}
QMenu::item:selected {
    background: #2563eb;
    color: #ffffff;
}
QMenu::separator {
    height: 1px;
    background: #e5e7eb;
    margin: 4px 8px;
}
QToolTip {
    background: #ffffff;
    color: #1f2937;
    border: 1px solid #d1d5db;
    padding: 4px 8px;
}
QCheckBox {
    color: #1f2937;
    spacing: 7px;
}
QCheckBox::indicator {
    width: 15px;
    height: 15px;
    border: 1px solid #d1d5db;
    border-radius: 4px;
    background: #ffffff;
}
QCheckBox::indicator:hover {
    border-color: #2563eb;
}
QCheckBox::indicator:checked {
    background: #2563eb;
    border-color: #2563eb;
}
"""


# --------------------------------------------------------------------------- #
# Crisp Custom Vector Icon Factory
# --------------------------------------------------------------------------- #
def make_vector_icon(kind: str, color: str = "#e6e8ec", size: int = 18) -> QIcon:
    """Render crisp, uniform anti-aliased vector icons for toolbar, sidebar, and menus."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    c = QColor(color)
    pen = QPen(
        c,
        1.75,
        Qt.PenStyle.SolidLine,
        Qt.PenCapStyle.RoundCap,
        Qt.PenJoinStyle.RoundJoin,
    )
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)

    s = float(size)
    m = 2.5
    if kind == "menu":
        p.drawLine(3, 5, int(s - 3), 5)
        p.drawLine(3, int(s / 2), int(s - 3), int(s / 2))
        p.drawLine(3, int(s - 5), int(s - 3), int(s - 5))
    elif kind == "add":
        p.drawLine(int(s / 2), int(m + 1), int(s / 2), int(s - m - 1))
        p.drawLine(int(m + 1), int(s / 2), int(s - m - 1), int(s / 2))
    elif kind == "resume":
        p.setBrush(QBrush(c))
        poly = QPolygonF([
            QPoint(5, 3),
            QPoint(int(s - 3), int(s / 2)),
            QPoint(5, int(s - 3)),
        ])
        p.drawPolygon(poly)
    elif kind == "pause":
        p.setBrush(QBrush(c))
        p.drawRoundedRect(QRectF(4.0, 3.5, 3.2, s - 7.0), 1.0, 1.0)
        p.drawRoundedRect(QRectF(s - 7.2, 3.5, 3.2, s - 7.0), 1.0, 1.0)
    elif kind == "pause_all":
        p.drawRect(QRectF(3.5, 3.5, s - 7.0, s - 7.0))
        p.drawLine(7, 6, 7, int(s - 6))
        p.drawLine(int(s - 7), 6, int(s - 7), int(s - 6))
    elif kind == "delete":
        p.drawLine(3, 5, int(s - 3), 5)
        p.drawLine(7, 3, int(s - 7), 3)
        p.drawRoundedRect(QRectF(4.5, 5.0, s - 9.0, s - 7.5), 1.5, 1.5)
        p.drawLine(7, 8, 7, int(s - 5))
        p.drawLine(int(s - 7), 8, int(s - 7), int(s - 5))
    elif kind == "batch":
        p.drawLine(6, 5, int(s - 3), 5)
        p.drawLine(6, int(s / 2), int(s - 3), int(s / 2))
        p.drawLine(6, int(s - 5), int(s - 3), int(s - 5))
        p.drawPoint(3, 5)
        p.drawPoint(3, int(s / 2))
        p.drawPoint(3, int(s - 5))
    elif kind == "grabber":
        r = s / 2.0 - 2.5
        p.drawEllipse(QRectF(2.5, 2.5, r * 2, r * 2))
        p.drawEllipse(QRectF(5.5, 2.5, (r - 3.0) * 2, r * 2))
        p.drawLine(2, int(s / 2), int(s - 2), int(s / 2))
    elif kind == "scheduler":
        p.drawEllipse(QRectF(2.5, 2.5, s - 5.0, s - 5.0))
        p.drawLine(int(s / 2), int(s / 2), int(s / 2), 5)
        p.drawLine(int(s / 2), int(s / 2), int(s - 5), int(s / 2))
    elif kind == "drop_target":
        p.drawRoundedRect(QRectF(3.0, 3.0, s - 6.0, s - 6.0), 3.0, 3.0)
        p.drawLine(int(s / 2), 5, int(s / 2), int(s - 6))
        p.drawLine(6, int(s - 8), int(s / 2), int(s - 5))
        p.drawLine(int(s - 6), int(s - 8), int(s / 2), int(s - 5))
    elif kind == "settings":
        p.drawEllipse(QRectF(5.5, 5.5, s - 11.0, s - 11.0))
        for deg in range(0, 360, 45):
            p.save()
            p.translate(s / 2.0, s / 2.0)
            p.rotate(deg)
            p.drawLine(0, int(-s / 2.0 + 2.0), 0, int(-s / 2.0 + 4.0))
            p.restore()
    elif kind == "search":
        r = s / 2.0 - 4.0
        p.drawEllipse(QRectF(3.5, 3.5, r * 2.0, r * 2.0))
        p.drawLine(int(s - 6), int(s - 6), int(s - 3), int(s - 3))
    elif kind == "all":
        p.drawRoundedRect(QRectF(2.5, 4.0, s - 5.0, s - 7.0), 2.0, 2.0)
        p.drawLine(2, 7, int(s - 2), 7)
    elif kind == "downloading":
        p.drawLine(int(s / 2), 3, int(s / 2), int(s - 5))
        p.drawLine(5, int(s - 8), int(s / 2), int(s - 4))
        p.drawLine(int(s - 5), int(s - 8), int(s / 2), int(s - 4))
        p.drawLine(4, int(s - 2.5), int(s - 4), int(s - 2.5))
    elif kind == "completed":
        p.drawEllipse(QRectF(2.5, 2.5, s - 5.0, s - 5.0))
        p.drawLine(5, int(s / 2), 8, int(s - 5))
        p.drawLine(8, int(s - 5), int(s - 5), 6)
    elif kind == "videos":
        p.drawRoundedRect(QRectF(2.5, 4.0, s - 5.0, s - 8.0), 2.0, 2.0)
        p.setBrush(QBrush(c))
        poly = QPolygonF([
            QPoint(7, 6),
            QPoint(12, int(s / 2)),
            QPoint(7, int(s - 6)),
        ])
        p.drawPolygon(poly)
    elif kind == "compressed":
        p.drawRoundedRect(QRectF(3.5, 2.5, s - 7.0, s - 5.0), 2.0, 2.0)
        p.drawLine(int(s / 2), 3, int(s / 2), int(s - 3))
        p.drawLine(7, 6, 11, 6)
        p.drawLine(7, 9, 11, 9)
        p.drawLine(7, 12, 11, 12)
    elif kind == "programs":
        p.drawRoundedRect(QRectF(2.5, 3.5, s - 5.0, s - 7.0), 2.0, 2.0)
        p.drawLine(5, 7, 8, 9)
        p.drawLine(8, 9, 5, 11)
        p.drawLine(9, 11, 13, 11)
    elif kind == "documents":
        p.drawRoundedRect(QRectF(3.5, 2.5, s - 7.0, s - 5.0), 1.5, 1.5)
        p.drawLine(6, 6, int(s - 6), 6)
        p.drawLine(6, 9, int(s - 6), 9)
        p.drawLine(6, 12, int(s - 8), 12)
    elif kind == "queue":
        p.drawLine(3, 5, int(s - 3), 5)
        p.drawLine(3, 9, int(s - 3), 9)
        p.drawLine(3, 13, int(s - 7), 13)
    elif kind == "browser":
        r = s / 2.0 - 2.5
        p.drawEllipse(QRectF(2.5, 2.5, r * 2, r * 2))
        p.drawEllipse(QRectF(5.5, 2.5, (r - 3.0) * 2, r * 2))
        p.drawLine(2, int(s / 2), int(s - 2), int(s / 2))

    p.end()
    return QIcon(pm)


def _center_widget_in_cell(widget: QWidget) -> QWidget:
    """Center a checkbox or small control cleanly inside a QTableWidget cell."""
    container = QWidget()
    lay = QHBoxLayout(container)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lay.addWidget(widget)
    return container


def default_download_dir() -> str:
    d = os.path.join(os.path.expanduser("~"), "Downloads")
    return d if os.path.isdir(d) else os.path.expanduser("~")


DEFAULT_SETTINGS = {
    "theme": "Dark Grey",
    "minimize_to_tray": True,
    "start_minimized": False,
    "notify_on_complete": True,
    "run_on_startup": False,
    "save_dir": "",
    "auto_categorize": True,
    "threads": 8,
    "max_concurrent_downloads": 3,
    "file_conflict": "Auto-rename",
    "speed_limit_enabled": False,
    "speed_limit_kbps": 1024,
    "custom_user_agent": "",
    "retry_attempts": 3,
    "clipboard_monitor": False,
    "enabled_interfaces": [],
    "proxy_pool_enabled": False,
    "proxy_pool": [],
    "proxy_pool_include_direct": True,
    "extension_installed_prompt_shown": False,
    "custom_browser_path": "",
    "queues_config": {
        "Main Download Queue": {
            "max_concurrent": 3,
            "start_time": None,
            "stop_time": None,
            "recurring": False,
            "on_complete": "Do nothing",
        },
        "Synchronization Queue": {
            "max_concurrent": 1,
            "start_time": None,
            "stop_time": None,
            "recurring": False,
            "on_complete": "Do nothing",
        },
    },
}


def get_windows_startup_enabled() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_READ,
        )
        try:
            val, _ = winreg.QueryValueEx(key, "CIDM")
            return bool(val)
        except FileNotFoundError:
            try:
                val, _ = winreg.QueryValueEx(key, "PyIDM")
                return bool(val)
            except FileNotFoundError:
                return False
        finally:
            winreg.CloseKey(key)
    except Exception:
        return False


def set_windows_startup_enabled(enabled: bool) -> None:
    if sys.platform != "win32":
        return
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_SET_VALUE,
        )
        try:
            if enabled:
                exe_path = sys.executable
                if getattr(sys, "frozen", False):
                    cmd = f'"{exe_path}" --minimized'
                else:
                    main_py = os.path.abspath(
                        os.path.join(os.path.dirname(__file__), "main.py")
                    )
                    cmd = f'"{exe_path}" "{main_py}" --minimized'
                winreg.SetValueEx(key, "CIDM", 0, winreg.REG_SZ, cmd)
            else:
                for k in ("CIDM", "PyIDM"):
                    try:
                        winreg.DeleteValue(key, k)
                    except FileNotFoundError:
                        pass
        finally:
            winreg.CloseKey(key)
    except Exception:
        pass


def load_settings() -> dict:
    settings = dict(DEFAULT_SETTINGS)
    settings["save_dir"] = default_download_dir()
    if os.path.exists(SETTINGS_PATH):
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                settings.update(data)
        except Exception:
            pass
    if sys.platform == "win32":
        settings["run_on_startup"] = get_windows_startup_enabled()
    apply_engine_settings(settings)
    return settings


def save_settings(settings: dict) -> None:
    try:
        os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
    except Exception:
        pass
    if sys.platform == "win32" and "run_on_startup" in settings:
        set_windows_startup_enabled(bool(settings["run_on_startup"]))
    apply_engine_settings(settings)


def create_app_icon() -> QIcon:
    base_dir = getattr(
        sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))
    )
    icon = QIcon()
    for fname in (
        "cidm.ico",
        "cidm.png",
        "cidm_512.png",
        "pyidm.ico",
        "pyidm.png",
        "icon.png",
        "icon.ico",
    ):
        for sub in ("assets", ""):
            cand = (
                os.path.join(base_dir, sub, fname)
                if sub
                else os.path.join(base_dir, fname)
            )
            if os.path.exists(cand) and os.path.getsize(cand) > 0:
                icon.addFile(cand)

    if not icon.isNull() and len(icon.availableSizes()) > 0:
        return icon

    pm = QPixmap(64, 64)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QBrush(QColor("#4f86c6")))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(2, 2, 60, 60, 14, 14)

    pen = QPen(
        QColor("#ffffff"),
        5,
        Qt.PenStyle.SolidLine,
        Qt.PenCapStyle.RoundCap,
        Qt.PenJoinStyle.RoundJoin,
    )
    p.setPen(pen)
    p.drawLine(32, 14, 32, 38)
    p.drawLine(21, 28, 32, 38)
    p.drawLine(43, 28, 32, 38)
    p.drawLine(18, 48, 46, 48)
    p.end()
    return QIcon(pm)


# --------------------------------------------------------------------------- #
# Browser Integration & Extension Helpers
# --------------------------------------------------------------------------- #
def get_extension_source_dir() -> str:
    """Locate the bundled chrome_extension directory."""
    base_dir = getattr(
        sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))
    )
    cand = os.path.join(base_dir, "chrome_extension")
    if os.path.isdir(cand) and os.path.exists(os.path.join(cand, "manifest.json")):
        return cand
    cand = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "chrome_extension"
    )
    if os.path.isdir(cand) and os.path.exists(os.path.join(cand, "manifest.json")):
        return cand
    return ""


def get_installed_extension_dir() -> str:
    """Persistent destination directory for the CIDM browser extension."""
    return os.path.join(os.path.expanduser("~"), ".cidm", "extension")


def sync_extension_files() -> str:
    """Copy or update extension files into ~/.cidm/extension."""
    src = get_extension_source_dir()
    dst = get_installed_extension_dir()
    if not src or not os.path.isdir(src):
        return dst if os.path.isdir(dst) else ""
    try:
        os.makedirs(dst, exist_ok=True)
        for item in os.listdir(src):
            s_item = os.path.join(src, item)
            d_item = os.path.join(dst, item)
            if os.path.isdir(s_item):
                shutil.copytree(s_item, d_item, dirs_exist_ok=True)
            else:
                shutil.copy2(s_item, d_item)
        return dst
    except Exception:
        return dst if os.path.isdir(dst) else src


def register_extension_in_registry(ext_dir: str) -> None:
    """Register extension in Windows Registry for Chromium-based browsers."""
    if sys.platform != "win32" or not ext_dir:
        return
    try:
        import winreg
        targets = [
            r"Software\Google\Chrome\Extensions\cidm_download_manager",
            r"Software\Microsoft\Edge\Extensions\cidm_download_manager",
            r"Software\BraveSoftware\Brave-Browser\Extensions\cidm_download_manager",
        ]
        manifest_path = os.path.join(ext_dir, "manifest.json")
        for subkey in targets:
            try:
                key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, subkey)
                winreg.SetValueEx(key, "path", 0, winreg.REG_SZ, manifest_path)
                winreg.SetValueEx(key, "version", 0, winreg.REG_SZ, "2.1.0")
                winreg.CloseKey(key)
            except Exception:
                pass
    except Exception:
        pass


def open_extension_folder(ext_dir: str = "") -> None:
    """Open the extension folder in File Explorer."""
    path = ext_dir or sync_extension_files() or get_installed_extension_dir()
    if not os.path.exists(path):
        try:
            os.makedirs(path, exist_ok=True)
        except Exception:
            pass
    if sys.platform == "win32" and os.path.exists(path):
        try:
            os.startfile(path)
        except Exception:
            pass
    elif os.path.exists(path):
        try:
            subprocess.Popen(["xdg-open", path])
        except Exception:
            pass


def detect_installed_browsers() -> List[Dict[str, str]]:
    """Detect popular web browsers installed on Windows."""
    browsers_spec = [
        {
            "name": "Google Chrome",
            "reg": [r"Software\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe"],
            "fs": [
                r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
                r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
                r"%LocalAppData%\Google\Chrome\Application\chrome.exe",
            ],
            "ext_url": "chrome://extensions",
        },
        {
            "name": "Microsoft Edge",
            "reg": [r"Software\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe"],
            "fs": [
                r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
                r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
            ],
            "ext_url": "edge://extensions",
        },
        {
            "name": "Brave Browser",
            "reg": [r"Software\Microsoft\Windows\CurrentVersion\App Paths\brave.exe"],
            "fs": [
                r"%ProgramFiles%\BraveSoftware\Brave-Browser\Application\brave.exe",
                r"%LocalAppData%\BraveSoftware\Brave-Browser\Application\brave.exe",
            ],
            "ext_url": "brave://extensions",
        },
        {
            "name": "Opera",
            "reg": [r"Software\Microsoft\Windows\CurrentVersion\App Paths\opera.exe"],
            "fs": [
                r"%LocalAppData%\Programs\Opera\opera.exe",
                r"%ProgramFiles%\Opera\opera.exe",
            ],
            "ext_url": "opera://extensions",
        },
        {
            "name": "Opera GX",
            "reg": [r"Software\Microsoft\Windows\CurrentVersion\App Paths\opera_gx.exe"],
            "fs": [
                r"%LocalAppData%\Programs\Opera GX\opera.exe",
            ],
            "ext_url": "opera://extensions",
        },
        {
            "name": "Vivaldi",
            "reg": [r"Software\Microsoft\Windows\CurrentVersion\App Paths\vivaldi.exe"],
            "fs": [
                r"%LocalAppData%\Vivaldi\Application\vivaldi.exe",
                r"%ProgramFiles%\Vivaldi\Application\vivaldi.exe",
            ],
            "ext_url": "vivaldi://extensions",
        },
    ]

    detected = []
    if sys.platform == "win32":
        try:
            import winreg
            for b in browsers_spec:
                exe_path = ""
                # Check registry App Paths
                for subkey in b["reg"]:
                    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                        try:
                            with winreg.OpenKey(root, subkey) as k:
                                val, _ = winreg.QueryValueEx(k, "")
                                clean = str(val).strip('" ')
                                if clean and os.path.exists(clean):
                                    exe_path = clean
                                    break
                        except Exception:
                            pass
                    if exe_path:
                        break

                # Fallback to standard filesystem locations
                if not exe_path:
                    for p in b["fs"]:
                        expanded = os.path.expandvars(p)
                        if os.path.exists(expanded):
                            exe_path = expanded
                            break

                if exe_path:
                    detected.append({
                        "name": b["name"],
                        "exe": exe_path,
                        "ext_url": b["ext_url"],
                    })
        except Exception:
            pass

    return detected


def launch_browser_for_extension_install(
    browser_exe: str,
    ext_url: str = "chrome://extensions",
    parent: Optional[QWidget] = None,
    browser_name: str = "Browser",
) -> bool:
    """Prepare extension, copy path to clipboard, launch browser, and show instructions dialog."""
    ext_dir = sync_extension_files()
    register_extension_in_registry(ext_dir)

    app = QApplication.instance()
    if app and ext_dir:
        app.clipboard().setText(ext_dir)

    launched = False
    if browser_exe and os.path.exists(browser_exe):
        try:
            args = [browser_exe]
            if ext_dir and os.path.isdir(ext_dir):
                args.append(f"--load-extension={ext_dir}")
            if ext_url:
                args.append(ext_url)
            subprocess.Popen(args)
            launched = True
        except Exception:
            pass

    dlg = ExtensionInstallGuideDialog(
        parent=parent,
        browser_name=browser_name,
        ext_dir=ext_dir,
        launched=launched,
    )
    dlg.exec()
    return launched


class ExtensionInstallGuideDialog(QDialog):
    """Clean guided 3-step walkthrough for loading unpacked CIDM extension."""

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        browser_name: str = "Browser",
        ext_dir: str = "",
        launched: bool = True,
    ):
        super().__init__(parent)
        self.setWindowTitle(f"Install CIDM Extension — {browser_name}")
        self.resize(520, 360)
        self.setModal(True)
        self.ext_dir = ext_dir or get_installed_extension_dir()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 18, 18, 18)
        lay.setSpacing(14)

        header = QHBoxLayout()
        header.setSpacing(12)
        icon_lbl = QLabel()
        icon_lbl.setPixmap(create_app_icon().pixmap(38, 38))
        header.addWidget(icon_lbl)

        title_box = QVBoxLayout()
        title_box.setSpacing(3)
        lbl_title = QLabel(f"Complete CIDM Integration with {browser_name}")
        lbl_title.setStyleSheet("font-size: 15px; font-weight: bold; color: #4f86c6;")
        lbl_sub = QLabel(
            "Browser opened! Follow these 3 quick steps to activate:"
            if launched
            else "Follow these 3 quick steps in your browser:"
        )
        lbl_sub.setStyleSheet("font-size: 12px; color: #9aa0aa;")
        title_box.addWidget(lbl_title)
        title_box.addWidget(lbl_sub)
        header.addLayout(title_box, 1)
        lay.addLayout(header)

        steps_group = QGroupBox("3-Step Quick Activation")
        steps_lay = QVBoxLayout(steps_group)
        steps_lay.setSpacing(9)

        s1 = QLabel("<b>Step 1:</b> In the browser Extensions tab, turn <b>ON</b> the <b>'Developer mode'</b> switch (usually at the top-right corner).")
        s1.setStyleSheet("font-size: 12px; line-height: 1.4;")
        s1.setWordWrap(True)
        steps_lay.addWidget(s1)

        s2 = QLabel("<b>Step 2:</b> Click the <b>'Load unpacked'</b> button (top-left).")
        s2.setStyleSheet("font-size: 12px; line-height: 1.4;")
        s2.setWordWrap(True)
        steps_lay.addWidget(s2)

        s3 = QLabel("<b>Step 3:</b> The extension path is <b>already copied to your clipboard</b>! Press <b>Ctrl+V</b> into the folder path box and click <b>'Select Folder'</b>.")
        s3.setStyleSheet("font-size: 12px; line-height: 1.4; color: #57ab5a;")
        s3.setWordWrap(True)
        steps_lay.addWidget(s3)

        lay.addWidget(steps_group)

        path_box = QHBoxLayout()
        path_box.setSpacing(8)
        self.path_edit = QLineEdit(self.ext_dir)
        self.path_edit.setReadOnly(True)
        self.path_edit.setStyleSheet("font-family: monospace; font-size: 11px;")

        btn_copy = QPushButton("Copy Path")
        btn_copy.setAutoDefault(False)
        btn_copy.clicked.connect(self._copy_path)

        btn_open = QPushButton("Open Folder")
        btn_open.setAutoDefault(False)
        btn_open.clicked.connect(lambda: open_extension_folder(self.ext_dir))

        path_box.addWidget(self.path_edit, 1)
        path_box.addWidget(btn_copy)
        path_box.addWidget(btn_open)
        lay.addLayout(path_box)

        self.lbl_status = QLabel("Path copied to clipboard automatically!")
        self.lbl_status.setStyleSheet("color: #4f86c6; font-size: 11px;")
        lay.addWidget(self.lbl_status)

        lay.addStretch(1)

        btn_box = QHBoxLayout()
        btn_box.addStretch(1)
        btn_done = QPushButton("Done / Got It")
        btn_done.setObjectName("primaryBtn")
        btn_done.setDefault(True)
        btn_done.clicked.connect(self.accept)
        btn_box.addWidget(btn_done)
        lay.addLayout(btn_box)

    def _copy_path(self):
        app = QApplication.instance()
        if app:
            app.clipboard().setText(self.ext_dir)
        self.lbl_status.setText("Path copied to clipboard again!")


class FirstRunExtensionDialog(QDialog):
    """First-run onboarding dialog guiding the user to install the browser extension."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Welcome to CIDM — Browser Extension Setup")
        self.resize(560, 430)
        self.setModal(True)
        self.ext_dir = sync_extension_files()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(14)

        header = QHBoxLayout()
        header.setSpacing(14)
        icon_lbl = QLabel()
        icon_lbl.setPixmap(create_app_icon().pixmap(48, 48))
        header.addWidget(icon_lbl)

        title_box = QVBoxLayout()
        title_box.setSpacing(4)
        lbl_title = QLabel("Welcome to CIDM!")
        lbl_title.setStyleSheet("font-size: 17px; font-weight: bold; color: #4f86c6;")
        lbl_sub = QLabel(
            "Install the CIDM browser extension to automatically capture file downloads "
            "and download streaming videos (YouTube, HLS, DASH, MP4) with 1 click."
        )
        lbl_sub.setStyleSheet("font-size: 12px; color: #9aa0aa; line-height: 1.4;")
        lbl_sub.setWordWrap(True)
        title_box.addWidget(lbl_title)
        title_box.addWidget(lbl_sub)
        header.addLayout(title_box, 1)
        lay.addLayout(header)

        gb = QGroupBox("Detected Browsers on Your Computer")
        gb_lay = QVBoxLayout(gb)
        gb_lay.setSpacing(10)

        self.detected_browsers = detect_installed_browsers()
        if self.detected_browsers:
            for b in self.detected_browsers:
                row = QHBoxLayout()
                row.setSpacing(10)
                name_lbl = QLabel(f"<b>{b['name']}</b>")
                name_lbl.setStyleSheet("font-size: 13px;")
                path_lbl = QLabel(b["exe"])
                path_lbl.setStyleSheet("color: #6b7280; font-size: 11px;")
                path_lbl.setToolTip(b["exe"])

                btn_install = QPushButton(f"Install in {b['name']}")
                btn_install.setObjectName("primaryBtn")
                btn_install.setAutoDefault(False)
                btn_install.clicked.connect(
                    lambda _chk=False, b_info=b: self._install_browser(b_info)
                )

                info_col = QVBoxLayout()
                info_col.setSpacing(2)
                info_col.addWidget(name_lbl)
                info_col.addWidget(path_lbl)

                row.addLayout(info_col, 1)
                row.addWidget(btn_install)
                gb_lay.addLayout(row)
        else:
            lbl_none = QLabel("No standard browsers automatically detected.")
            lbl_none.setStyleSheet("color: #9aa0aa; font-style: italic;")
            gb_lay.addWidget(lbl_none)

        lay.addWidget(gb)

        bottom_actions = QHBoxLayout()
        bottom_actions.setSpacing(10)

        btn_custom = QPushButton("Add to Custom Browser (.exe)...")
        btn_custom.setAutoDefault(False)
        btn_custom.clicked.connect(self._browse_custom_browser)
        bottom_actions.addWidget(btn_custom)

        btn_open_folder = QPushButton("Open Extension Folder")
        btn_open_folder.setAutoDefault(False)
        btn_open_folder.clicked.connect(lambda: open_extension_folder(self.ext_dir))
        bottom_actions.addWidget(btn_open_folder)

        bottom_actions.addStretch(1)
        lay.addLayout(bottom_actions)

        lay.addStretch(1)

        footer = QHBoxLayout()
        btn_skip = QPushButton("Install Later / Skip")
        btn_skip.setAutoDefault(False)
        btn_skip.clicked.connect(self.reject)
        footer.addWidget(btn_skip)

        footer.addStretch(1)

        btn_done = QPushButton("Done")
        btn_done.setDefault(True)
        btn_done.clicked.connect(self.accept)
        footer.addWidget(btn_done)

        lay.addLayout(footer)

    def _install_browser(self, b_info: Dict[str, str]):
        launch_browser_for_extension_install(
            browser_exe=b_info["exe"],
            ext_url=b_info.get("ext_url", "chrome://extensions"),
            parent=self,
            browser_name=b_info["name"],
        )

    def _browse_custom_browser(self):
        exe, _ = QFileDialog.getOpenFileName(
            self,
            "Select Browser Executable",
            os.environ.get("ProgramFiles", "C:\\"),
            "Executable Files (*.exe);;All Files (*)",
        )
        if exe:
            launch_browser_for_extension_install(
                browser_exe=exe,
                ext_url="chrome://extensions",
                parent=self,
                browser_name=os.path.basename(exe),
            )


# --------------------------------------------------------------------------- #
# Settings Dialog
# --------------------------------------------------------------------------- #
class SettingsDialog(QDialog):
    def __init__(self, parent: QWidget, settings: dict):
        super().__init__(parent)
        self.parent_window = parent
        self.settings = dict(settings)
        self.setWindowTitle("CIDM Settings")
        self.resize(620, 560)
        self.setModal(True)
        self.iface_checkboxes: List[tuple] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        self.tabs = QTabWidget()
        self._build_general_tab()
        self._build_downloads_tab()
        self._build_browser_tab()
        self._build_network_tab()
        layout.addWidget(self.tabs)

        btn_box = QHBoxLayout()
        btn_box.addStretch(1)

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self.reject)
        btn_box.addWidget(self.btn_cancel)

        self.btn_save = QPushButton("Save Settings")
        self.btn_save.setObjectName("primaryBtn")
        self.btn_save.setDefault(True)
        self.btn_save.clicked.connect(self.accept)
        btn_box.addWidget(self.btn_save)

        layout.addLayout(btn_box)

    def _build_general_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(12)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setSpacing(10)

        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["Dark Grey", "Light"])
        cur_theme = self.settings.get("theme", "Dark Grey")
        idx = self.theme_combo.findText(cur_theme)
        if idx >= 0:
            self.theme_combo.setCurrentIndex(idx)
        self.theme_combo.currentTextChanged.connect(self._on_theme_changed)
        form.addRow("UI Theme:", self.theme_combo)
        lay.addLayout(form)

        gb_behavior = QGroupBox("Background & Startup Behavior")
        gb_lay = QVBoxLayout(gb_behavior)
        gb_lay.setSpacing(10)

        self.cb_tray = QCheckBox(
            "Keep running in background (minimize to system tray on close)"
        )
        self.cb_tray.setChecked(
            bool(self.settings.get("minimize_to_tray", True))
        )
        gb_lay.addWidget(self.cb_tray)

        self.cb_start_minimized = QCheckBox(
            "Start minimized directly to system tray"
        )
        self.cb_start_minimized.setChecked(
            bool(self.settings.get("start_minimized", False))
        )
        gb_lay.addWidget(self.cb_start_minimized)

        self.cb_startup = QCheckBox(
            "Launch CIDM automatically on Windows startup"
        )
        self.cb_startup.setChecked(
            bool(self.settings.get("run_on_startup", False))
        )
        if sys.platform != "win32":
            self.cb_startup.setEnabled(False)
            self.cb_startup.setToolTip(
                "Windows startup is only available on Windows."
            )
        gb_lay.addWidget(self.cb_startup)

        self.cb_notify = QCheckBox(
            "Show desktop notification when a download finishes"
        )
        self.cb_notify.setChecked(
            bool(self.settings.get("notify_on_complete", True))
        )
        gb_lay.addWidget(self.cb_notify)

        self.cb_clipboard = QCheckBox(
            "Monitor clipboard for downloadable file links"
        )
        self.cb_clipboard.setChecked(
            bool(self.settings.get("clipboard_monitor", False))
        )
        gb_lay.addWidget(self.cb_clipboard)

        lay.addWidget(gb_behavior)
        lay.addStretch(1)
        self.tabs.addTab(w, "General & Appearance")

    def _on_theme_changed(self, theme_name: str):
        if self.parent_window and hasattr(self.parent_window, "apply_theme"):
            self.parent_window.apply_theme(theme_name)

    def _build_downloads_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(12)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setSpacing(12)

        dir_box = QHBoxLayout()
        dir_box.setSpacing(8)
        self.save_dir_edit = QLineEdit(
            str(self.settings.get("save_dir") or default_download_dir())
        )
        btn_browse = QPushButton("Browse...")
        btn_browse.clicked.connect(self._browse_save_dir)
        dir_box.addWidget(self.save_dir_edit, 1)
        dir_box.addWidget(btn_browse)
        form.addRow("Default save folder:", dir_box)

        self.spin_threads = QSpinBox()
        self.spin_threads.setRange(1, 32)
        self.spin_threads.setValue(int(self.settings.get("threads", 8)))
        self.spin_threads.setFixedWidth(90)
        form.addRow("Connections per download:", self.spin_threads)

        self.spin_concur = QSpinBox()
        self.spin_concur.setRange(1, 10)
        self.spin_concur.setValue(
            int(self.settings.get("max_concurrent_downloads", 3))
        )
        self.spin_concur.setFixedWidth(90)
        form.addRow("Max active downloads:", self.spin_concur)

        self.combo_conflict = QComboBox()
        self.combo_conflict.addItems(["Auto-rename", "Overwrite", "Ask"])
        cur_conflict = str(self.settings.get("file_conflict", "Auto-rename"))
        idx = self.combo_conflict.findText(cur_conflict)
        if idx >= 0:
            self.combo_conflict.setCurrentIndex(idx)
        form.addRow("When file already exists:", self.combo_conflict)

        lay.addLayout(form)

        self.cb_categorize = QCheckBox(
            "Automatically sort downloads into category subfolders (Videos, Programs, etc.)"
        )
        self.cb_categorize.setChecked(
            bool(self.settings.get("auto_categorize", True))
        )
        lay.addWidget(self.cb_categorize)

        lay.addStretch(1)
        self.tabs.addTab(w, "Downloads & Folders")

    def _browse_save_dir(self):
        d = QFileDialog.getExistingDirectory(
            self, "Select Default Download Folder", self.save_dir_edit.text()
        )
        if d:
            self.save_dir_edit.setText(d)

    def _build_browser_tab(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(14)

        # 1. Extension Status & Info
        gb_ext = QGroupBox("CIDM Browser Extension (Manifest V3)")
        gb_ext_lay = QVBoxLayout(gb_ext)
        gb_ext_lay.setSpacing(8)

        lbl_desc = QLabel(
            "The CIDM extension integrates with your web browser to capture file downloads "
            "and detect high-speed video streams (HLS, DASH, MP4) directly."
        )
        lbl_desc.setStyleSheet("color: #9aa0aa; font-size: 12px; line-height: 1.4;")
        lbl_desc.setWordWrap(True)
        gb_ext_lay.addWidget(lbl_desc)

        ext_dir = sync_extension_files() or get_installed_extension_dir()

        loc_row = QHBoxLayout()
        loc_row.setSpacing(8)
        lbl_loc = QLabel("Location:")
        self.ext_dir_edit = QLineEdit(ext_dir)
        self.ext_dir_edit.setReadOnly(True)
        self.ext_dir_edit.setStyleSheet("font-family: monospace; font-size: 11px;")

        btn_copy = QPushButton("Copy Path")
        btn_copy.setAutoDefault(False)
        btn_copy.clicked.connect(self._copy_ext_path)

        btn_folder = QPushButton("Open Folder")
        btn_folder.setAutoDefault(False)
        btn_folder.clicked.connect(lambda: open_extension_folder(self.ext_dir_edit.text()))

        loc_row.addWidget(lbl_loc)
        loc_row.addWidget(self.ext_dir_edit, 1)
        loc_row.addWidget(btn_copy)
        loc_row.addWidget(btn_folder)
        gb_ext_lay.addLayout(loc_row)

        lay.addWidget(gb_ext)

        # 2. Detected Browsers
        gb_detected = QGroupBox("Detected Installed Browsers")
        gb_det_lay = QVBoxLayout(gb_detected)
        gb_det_lay.setSpacing(10)

        detected = detect_installed_browsers()
        if detected:
            for b in detected:
                row = QHBoxLayout()
                row.setSpacing(8)
                lbl_bname = QLabel(f"<b>{b['name']}</b>")
                lbl_bname.setFixedWidth(130)
                lbl_bpath = QLabel(b["exe"])
                lbl_bpath.setStyleSheet("color: #6b7280; font-size: 11px;")
                lbl_bpath.setToolTip(b["exe"])

                btn_add_b = QPushButton(f"Install in {b['name']}")
                btn_add_b.setAutoDefault(False)
                btn_add_b.clicked.connect(
                    lambda _chk=False, b_info=b: launch_browser_for_extension_install(
                        browser_exe=b_info["exe"],
                        ext_url=b_info.get("ext_url", "chrome://extensions"),
                        parent=self,
                        browser_name=b_info["name"],
                    )
                )

                row.addWidget(lbl_bname)
                row.addWidget(lbl_bpath, 1)
                row.addWidget(btn_add_b)
                gb_det_lay.addLayout(row)
        else:
            lbl_none = QLabel("No standard browsers automatically detected.")
            lbl_none.setStyleSheet("color: #9aa0aa; font-style: italic;")
            gb_det_lay.addWidget(lbl_none)

        lay.addWidget(gb_detected)

        # 3. Custom Browser of User's Choice
        gb_custom = QGroupBox("Add to Custom Browser of Your Choice")
        gb_cust_lay = QVBoxLayout(gb_custom)
        gb_cust_lay.setSpacing(10)

        lbl_cust_hint = QLabel(
            "Select any Chromium-based or custom browser executable (.exe) on your computer "
            "(e.g. Thorium, Ungoogled Chromium, Arc, Opera GX, Vivaldi, Floorp, Zen, or Portable Browser):"
        )
        lbl_cust_hint.setStyleSheet("color: #9aa0aa; font-size: 12px; line-height: 1.4;")
        lbl_cust_hint.setWordWrap(True)
        gb_cust_lay.addWidget(lbl_cust_hint)

        cust_row = QHBoxLayout()
        cust_row.setSpacing(8)
        self.custom_browser_edit = QLineEdit(
            str(self.settings.get("custom_browser_path", ""))
        )
        self.custom_browser_edit.setPlaceholderText(
            r"C:\Path\To\Your\Browser\browser.exe"
        )
        btn_cust_browse = QPushButton("Browse (.exe)...")
        btn_cust_browse.setAutoDefault(False)
        btn_cust_browse.clicked.connect(self._browse_custom_browser)

        cust_row.addWidget(self.custom_browser_edit, 1)
        cust_row.addWidget(btn_cust_browse)
        gb_cust_lay.addLayout(cust_row)

        btn_cust_install = QPushButton("Install Extension in Selected Browser")
        btn_cust_install.setObjectName("primaryBtn")
        btn_cust_install.setAutoDefault(False)
        btn_cust_install.clicked.connect(self._install_to_custom_browser)
        gb_cust_lay.addWidget(btn_cust_install)

        lay.addWidget(gb_custom)
        lay.addStretch(1)

        scroll.setWidget(w)
        self.tabs.addTab(scroll, "Browser Integration")

    def _copy_ext_path(self):
        app = QApplication.instance()
        if app:
            app.clipboard().setText(self.ext_dir_edit.text())
        QMessageBox.information(
            self,
            "Path Copied",
            "CIDM extension folder path copied to clipboard!\n\n"
            "Paste this path (Ctrl+V) when clicking 'Load unpacked' in your browser.",
        )

    def _browse_custom_browser(self):
        start_dir = (
            os.path.dirname(self.custom_browser_edit.text().strip())
            if os.path.exists(self.custom_browser_edit.text().strip())
            else os.environ.get("ProgramFiles", "C:\\")
        )
        exe, _ = QFileDialog.getOpenFileName(
            self,
            "Select Browser Executable",
            start_dir,
            "Executable Files (*.exe);;All Files (*)",
        )
        if exe:
            self.custom_browser_edit.setText(exe)

    def _install_to_custom_browser(self):
        exe = self.custom_browser_edit.text().strip()
        if not exe or not os.path.exists(exe):
            QMessageBox.warning(
                self,
                "Browser Executable Not Found",
                "Please browse and select a valid browser executable (.exe) first.",
            )
            return
        b_name = os.path.splitext(os.path.basename(exe))[0].capitalize()
        self.settings["custom_browser_path"] = exe
        launch_browser_for_extension_install(
            browser_exe=exe,
            ext_url="chrome://extensions",
            parent=self,
            browser_name=b_name,
        )

    def _build_network_tab(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(12)

        # 1. Multi-Interface Link Aggregation
        gb_net = QGroupBox(
            "Network Interfaces (Multi-Adapter Link Aggregation)"
        )
        gb_net_lay = QVBoxLayout(gb_net)
        gb_net_lay.setSpacing(8)

        lbl_net_desc = QLabel(
            "Select active network adapters for link aggregation channel bonding. "
            "Worker threads bind across checked adapters simultaneously."
        )
        lbl_net_desc.setStyleSheet("color: #9aa0aa; font-size: 12px;")
        lbl_net_desc.setWordWrap(True)
        gb_net_lay.addWidget(lbl_net_desc)

        self.iface_list_layout = QVBoxLayout()
        self.iface_list_layout.setSpacing(6)
        gb_net_lay.addLayout(self.iface_list_layout)

        # Same-Subnet Warning Banner & Metric Helper
        self.subnet_warning_widget = QWidget()
        sn_box = QVBoxLayout(self.subnet_warning_widget)
        sn_box.setContentsMargins(10, 8, 10, 8)
        sn_box.setSpacing(6)
        self.lbl_subnet_warning = QLabel("")
        self.lbl_subnet_warning.setStyleSheet(
            "color: #e6c875; font-size: 11px; line-height: 1.35;"
        )
        self.lbl_subnet_warning.setWordWrap(True)
        btn_metric_helper = QPushButton("Windows Interface Metric Guide")
        btn_metric_helper.setFixedWidth(215)
        btn_metric_helper.setAutoDefault(False)
        btn_metric_helper.clicked.connect(self._show_metric_helper)
        sn_box.addWidget(self.lbl_subnet_warning)
        sn_box.addWidget(btn_metric_helper)
        self.subnet_warning_widget.setStyleSheet(
            "background: rgba(201, 154, 69, 0.12); border: 1px solid #c99a45; border-radius: 6px;"
        )
        self.subnet_warning_widget.hide()
        gb_net_lay.addWidget(self.subnet_warning_widget)

        btn_refresh_ifaces = QPushButton("Refresh Interfaces")
        btn_refresh_ifaces.setFixedWidth(155)
        btn_refresh_ifaces.setAutoDefault(False)
        btn_refresh_ifaces.clicked.connect(self._refresh_interfaces)
        gb_net_lay.addWidget(btn_refresh_ifaces)

        self._refresh_interfaces()
        lay.addWidget(gb_net)

        # 2. Per-Worker Proxy Pool
        gb_proxy = QGroupBox(
            "Per-Worker Proxy Pool (Bypass Server IP Rate Limits)"
        )
        gb_proxy_lay = QVBoxLayout(gb_proxy)
        gb_proxy_lay.setSpacing(8)

        self.cb_proxy_pool = QCheckBox(
            "Enable Per-Worker Proxy Pool (distribute download threads across proxies)"
        )
        self.cb_proxy_pool.setChecked(
            bool(self.settings.get("proxy_pool_enabled", False))
        )
        gb_proxy_lay.addWidget(self.cb_proxy_pool)

        self.cb_proxy_include_direct = QCheckBox(
            "Include direct connection in worker pool rotation"
        )
        self.cb_proxy_include_direct.setChecked(
            bool(self.settings.get("proxy_pool_include_direct", True))
        )
        self.cb_proxy_include_direct.setEnabled(self.cb_proxy_pool.isChecked())
        gb_proxy_lay.addWidget(self.cb_proxy_include_direct)

        lbl_proxies = QLabel(
            "Proxy List (one per line — supports HTTP, HTTPS, and SOCKS5):"
        )
        lbl_proxies.setStyleSheet("color: #9aa0aa; font-size: 12px;")
        gb_proxy_lay.addWidget(lbl_proxies)

        self.txt_proxy_pool = QTextEdit()
        self.txt_proxy_pool.setPlaceholderText(
            "http://1.2.3.4:8080\nsocks5://user:pass@5.6.7.8:1080\nhttp://104.28.16.2:3128"
        )
        self.txt_proxy_pool.setFixedHeight(80)
        existing_proxies = self.settings.get("proxy_pool") or []
        self.txt_proxy_pool.setPlainText("\n".join(existing_proxies))
        self.txt_proxy_pool.setEnabled(self.cb_proxy_pool.isChecked())
        gb_proxy_lay.addWidget(self.txt_proxy_pool)

        self.cb_proxy_pool.toggled.connect(
            self.cb_proxy_include_direct.setEnabled
        )
        self.cb_proxy_pool.toggled.connect(self.txt_proxy_pool.setEnabled)

        lay.addWidget(gb_proxy)

        # 3. Speed Limiter
        gb_speed = QGroupBox("Bandwidth Throttling")
        gb_lay = QVBoxLayout(gb_speed)
        gb_lay.setSpacing(8)

        self.cb_speed_limit = QCheckBox("Enable global download speed limit")
        self.cb_speed_limit.setChecked(
            bool(self.settings.get("speed_limit_enabled", False))
        )
        gb_lay.addWidget(self.cb_speed_limit)

        speed_row = QHBoxLayout()
        speed_row.setSpacing(8)
        speed_lbl = QLabel("Max speed:")
        self.spin_speed = QSpinBox()
        self.spin_speed.setRange(50, 1000000)
        self.spin_speed.setSingleStep(100)
        self.spin_speed.setSuffix(" KB/s")
        self.spin_speed.setValue(
            int(self.settings.get("speed_limit_kbps", 1024))
        )
        self.spin_speed.setFixedWidth(135)
        self.spin_speed.setEnabled(self.cb_speed_limit.isChecked())
        self.cb_speed_limit.toggled.connect(self.spin_speed.setEnabled)
        speed_row.addWidget(speed_lbl)
        speed_row.addWidget(self.spin_speed)
        speed_row.addStretch(1)
        gb_lay.addLayout(speed_row)

        lay.addWidget(gb_speed)

        # 4. Custom User-Agent & Retries
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setSpacing(10)

        self.ua_edit = QLineEdit(
            str(self.settings.get("custom_user_agent", ""))
        )
        self.ua_edit.setPlaceholderText(DEFAULT_USER_AGENT)
        form.addRow("Custom User-Agent:", self.ua_edit)

        self.spin_retries = QSpinBox()
        self.spin_retries.setRange(0, 10)
        self.spin_retries.setValue(int(self.settings.get("retry_attempts", 3)))
        self.spin_retries.setFixedWidth(90)
        form.addRow("Retry attempts on drop:", self.spin_retries)

        lay.addLayout(form)
        lay.addStretch(1)
        scroll.setWidget(w)
        self.tabs.addTab(scroll, "Network & Aggregation")

    def _refresh_interfaces(self):
        while self.iface_list_layout.count():
            item = self.iface_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.iface_checkboxes.clear()

        enabled = self.settings.get("enabled_interfaces") or []
        ifaces = get_active_interfaces()
        if not ifaces:
            lbl_none = QLabel(
                "No active non-loopback network adapters found."
            )
            lbl_none.setStyleSheet("color: #cf5c5c; font-style: italic;")
            self.iface_list_layout.addWidget(lbl_none)
            self._update_subnet_warning()
            return

        for iface in ifaces:
            name, ip = iface["name"], iface["ip"]
            cb = QCheckBox(f"{name} ({ip})")
            is_checked = (not enabled) or (name in enabled) or (ip in enabled)
            cb.setChecked(is_checked)
            cb.toggled.connect(lambda _c: self._update_subnet_warning())
            self.iface_list_layout.addWidget(cb)
            self.iface_checkboxes.append((cb, iface))

        self._update_subnet_warning()

    def _update_subnet_warning(self):
        checked_ifaces = [
            iface for cb, iface in self.iface_checkboxes if cb.isChecked()
        ]
        overlap = check_same_subnet(checked_ifaces)
        if overlap:
            if1, if2, cidr = overlap
            self.lbl_subnet_warning.setText(
                f"<b>Same-Subnet Detected:</b> '{if1['name']}' ({if1['ip']}) and '{if2['name']}' ({if2['ip']}) "
                f"share subnet <b>{cidr}</b>.<br>"
                "Windows default gateway routing may route both adapters over the same connection. "
                "<b>Tip:</b> Connect the secondary adapter to a separate network (Guest Wi-Fi or Phone 5G Hotspot), "
                "or equalize interface metrics in Windows Network Properties."
            )
            self.subnet_warning_widget.show()
        else:
            self.subnet_warning_widget.hide()

    def _show_metric_helper(self):
        msg = (
            "<b>Windows Interface Metric & Same-Subnet Routing Guide:</b><br><br>"
            "When two network adapters (e.g. Ethernet + Wi-Fi) connect to the same router subnet (e.g. 192.168.1.x), "
            "Windows TCP/IP automatically assigns a lower metric to Ethernet (~15) than Wi-Fi (~35), routing "
            "all outbound traffic exclusively through the adapter with the lower metric.<br><br>"
            "<b>Recommended Fix (Zero-Config):</b><br>"
            "Connect your secondary adapter (Wi-Fi or USB tethering) to an isolated network or subnet such as "
            "your phone's 5G Mobile Hotspot, or your router's isolated Guest Wi-Fi network (e.g. 192.168.2.x).<br><br>"
            "<b>Manual Fix (Equalizing Interface Metrics in Windows):</b><br>"
            "1. Press <b>Win + R</b>, type <code>ncpa.cpl</code> and press Enter.<br>"
            "2. Right-click your Ethernet adapter -> <b>Properties</b>.<br>"
            "3. Select <b>Internet Protocol Version 4 (TCP/IPv4)</b> -> <b>Properties</b> -> <b>Advanced...</b><br>"
            "4. Uncheck <i>'Automatic metric'</i> and type <b>10</b> in Interface metric.<br>"
            "5. Repeat the exact same steps on your Wi-Fi adapter (also setting metric to <b>10</b>).<br>"
            "6. Click OK on all windows. Windows will now balance and route outbound connections equally across both adapters!"
        )
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle("Interface Metric & Same-Subnet Routing Guide")
        box.setText(msg)
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        box.exec()

    def values(self) -> dict:
        checked_ifaces = [
            iface["name"]
            for cb, iface in self.iface_checkboxes
            if cb.isChecked()
        ]
        proxies_list = [
            line.strip()
            for line in self.txt_proxy_pool.toPlainText().splitlines()
            if line.strip()
        ]
        return {
            "theme": self.theme_combo.currentText(),
            "minimize_to_tray": self.cb_tray.isChecked(),
            "start_minimized": self.cb_start_minimized.isChecked(),
            "run_on_startup": self.cb_startup.isChecked(),
            "notify_on_complete": self.cb_notify.isChecked(),
            "clipboard_monitor": self.cb_clipboard.isChecked(),
            "save_dir": self.save_dir_edit.text().strip()
            or default_download_dir(),
            "threads": self.spin_threads.value(),
            "max_concurrent_downloads": self.spin_concur.value(),
            "file_conflict": self.combo_conflict.currentText(),
            "auto_categorize": self.cb_categorize.isChecked(),
            "speed_limit_enabled": self.cb_speed_limit.isChecked(),
            "speed_limit_kbps": self.spin_speed.value(),
            "custom_user_agent": self.ua_edit.text().strip(),
            "retry_attempts": self.spin_retries.value(),
            "enabled_interfaces": checked_ifaces,
            "proxy_pool_enabled": self.cb_proxy_pool.isChecked(),
            "proxy_pool_include_direct": self.cb_proxy_include_direct.isChecked(),
            "proxy_pool": proxies_list,
            "custom_browser_path": self.custom_browser_edit.text().strip()
            if hasattr(self, "custom_browser_edit")
            else self.settings.get("custom_browser_path", ""),
            "extension_installed_prompt_shown": self.settings.get(
                "extension_installed_prompt_shown", False
            ),
        }

    def reject(self):
        original_theme = self.settings.get("theme", "Dark Grey")
        if self.parent_window and hasattr(self.parent_window, "apply_theme"):
            self.parent_window.apply_theme(original_theme)
        super().reject()


# --------------------------------------------------------------------------- #
# Add-URL / intercepted-download dialog
# --------------------------------------------------------------------------- #
class AddDownloadDialog(QDialog):
    def __init__(
        self,
        parent,
        url="",
        filename="",
        cookies="",
        user_agent="",
        referer="",
        origin="",
        stream_type="",
        save_dir="",
        threads=8,
        on_top=False,
        kind="",
        subtitles: Optional[List[dict]] = None,
        settings: Optional[dict] = None,
    ):
        super().__init__(parent)
        self.settings = settings or {}
        self.kind = kind
        self.origin = origin or ""
        self.stream_type = (stream_type or "").lower()
        self.is_media = (
            self.kind in ("media", "hls", "dash")
            or self.stream_type in ("hls", "dash", "media")
            or is_media_url(url)
        )
        self.is_hls = (
            (
                self.kind == "hls"
                or self.stream_type == "hls"
                or is_hls_url(url)
            )
            and not self.is_media
        )

        title = (
            "Download Media Stream"
            if self.is_media
            else ("Download Stream" if self.is_hls else "Add Download")
        )
        self.setWindowTitle(title)
        self.resize(520, 270)
        self.setModal(True)
        if on_top:
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.cookies, self.user_agent, self.referer = (
            cookies,
            user_agent,
            referer,
        )
        self._name_edited = bool(filename)
        self._gen = 0
        self._probe_out: Optional[tuple[int, bool, Any, Any]] = None
        self._probe_lock = threading.Lock()
        self._probed_media_result = None

        self.url_edit = QLineEdit(url)
        self.url_edit.setPlaceholderText(
            "https://example.com/file.zip or YouTube URL"
        )

        self.format_label = QLabel("Quality / Format:")
        self.format_combo = QComboBox()
        self.format_combo.currentIndexChanged.connect(self._on_format_changed)
        if self.is_media:
            default_opt = QualityOption(
                label="Best Video + Audio (MP4)",
                format_id="bv*+ba/b",
                ext="mp4",
            )
            self.format_combo.addItem(default_opt.label, userData=default_opt)

        self.sub_track_label = QLabel("Subtitle Track:")
        self.sub_track_combo = QComboBox()
        self.sub_mode_label = QLabel("Subtitle Mode:")
        self.sub_mode_combo = QComboBox()
        self.sub_mode_combo.addItem(
            "Embed into MP4 (Soft Subtitles — mov_text)", "embed"
        )
        self.sub_mode_combo.addItem(
            "Save as External .srt Sidecar File", "sidecar"
        )
        if not find_ffmpeg():
            self.sub_mode_combo.setCurrentIndex(1)

        clean_initial_name = sanitize_filename(filename) if filename else ""
        self.name_edit = QLineEdit(clean_initial_name)
        self.name_edit.setPlaceholderText(
            "Detecting from server / media..."
        )
        self.name_edit.textEdited.connect(
            lambda _t: setattr(self, "_name_edited", True)
        )
        if not clean_initial_name and url:
            guess = filename_from_url(url)
            if self.is_hls and guess.lower().endswith((".m3u8", ".m3u")):
                guess = os.path.splitext(guess)[0]
            self.name_edit.setText(guess)
        self.info_label = QLabel("")
        self.info_label.setStyleSheet("color: #9aa0aa; font-size: 12px;")

        self.dir_edit = QLineEdit(save_dir or default_download_dir())
        browse = QPushButton("Browse...")
        browse.setAutoDefault(False)
        browse.clicked.connect(self._browse)
        dir_row = QHBoxLayout()
        dir_row.setSpacing(8)
        dir_row.addWidget(self.dir_edit, 1)
        dir_row.addWidget(browse)

        self.thread_spin = QSpinBox()
        self.thread_spin.setRange(1, 32)
        self.thread_spin.setValue(int(threads))
        self.thread_spin.setFixedWidth(90)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setVerticalSpacing(6)
        form.setHorizontalSpacing(8)
        form.addRow("URL:", self.url_edit)
        form.addRow(self.format_label, self.format_combo)
        form.addRow(self.sub_track_label, self.sub_track_combo)
        form.addRow(self.sub_mode_label, self.sub_mode_combo)
        form.addRow("File name:", self.name_edit)
        form.addRow("", self.info_label)
        form.addRow("Save to:", dir_row)
        form.addRow("Connections:", self.thread_spin)

        self.adapter_checkboxes: List[tuple] = []
        ifaces = get_active_interfaces()
        enabled_pref = self.settings.get("enabled_interfaces") or []
        if ifaces:
            adapter_box = QWidget()
            ad_lay = QVBoxLayout(adapter_box)
            ad_lay.setContentsMargins(0, 2, 0, 2)
            ad_lay.setSpacing(5)
            for iface in ifaces:
                name, ip = iface["name"], iface["ip"]
                cb = QCheckBox(f"{name} ({ip})")
                is_checked = (
                    (not enabled_pref)
                    or (name in enabled_pref)
                    or (ip in enabled_pref)
                )
                cb.setChecked(is_checked)
                ad_lay.addWidget(cb)
                self.adapter_checkboxes.append((cb, ip, name))
            form.addRow("Network Adapters:", adapter_box)

        # Proxy Pool row (if proxies are configured in settings)
        self.cb_use_proxy_pool = None
        proxy_pool = self.settings.get("proxy_pool") or []
        if proxy_pool:
            self.cb_use_proxy_pool = QCheckBox(
                f"Enable Proxy Pool ({len(proxy_pool)} proxies configured)"
            )
            self.cb_use_proxy_pool.setChecked(
                bool(self.settings.get("proxy_pool_enabled", False))
            )
            form.addRow("Proxy Pool:", self.cb_use_proxy_pool)

        self.format_label.setVisible(self.is_media)
        self.format_combo.setVisible(self.is_media)
        self.sub_track_label.setVisible(False)
        self.sub_track_combo.setVisible(False)
        self.sub_mode_label.setVisible(False)
        self.sub_mode_combo.setVisible(False)

        self.detected_subtitles = list(subtitles or [])
        if self.detected_subtitles:
            self._populate_subtitles(self.detected_subtitles)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 10)
        layout.setSpacing(8)
        if cookies or referer:
            badge = QLabel("Browser session (cookies / referer) attached")
            badge.setStyleSheet("color: #4f86c6; font-weight: 600;")
            layout.addWidget(badge)
        layout.addLayout(form)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.setAutoDefault(False)
        cancel.clicked.connect(self.reject)
        ok = QPushButton("Start Download")
        ok.setObjectName("primaryBtn")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(ok)
        layout.addLayout(buttons)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(600)
        self._debounce.timeout.connect(self._start_probe)
        self.url_edit.textChanged.connect(lambda _t: self._debounce.start())

        self._poller = QTimer(self)
        self._poller.setInterval(150)
        self._poller.timeout.connect(self._poll_probe)
        self._poller.start()
        if url:
            QTimer.singleShot(50, self._start_probe)

    def _populate_subtitles(self, subs: List[dict]):
        if not subs:
            return
        self.sub_track_combo.blockSignals(True)
        if self.sub_track_combo.count() == 0:
            self.sub_track_combo.addItem("None", None)
        for s in subs:
            label = s.get("label") or s.get("lang") or "Subtitles"
            already = False
            for idx in range(self.sub_track_combo.count()):
                data = self.sub_track_combo.itemData(idx)
                if data and (
                    (data.get("url") and data.get("url") == s.get("url"))
                    or (data.get("lang") and data.get("lang") == s.get("lang"))
                ):
                    already = True
                    break
            if not already:
                self.sub_track_combo.addItem(label, s)
        self.sub_track_combo.blockSignals(False)
        has_tracks = self.sub_track_combo.count() > 1
        self.sub_track_label.setVisible(has_tracks)
        self.sub_track_combo.setVisible(has_tracks)
        self.sub_mode_label.setVisible(has_tracks)
        self.sub_mode_combo.setVisible(has_tracks)

    def showEvent(self, event):
        super().showEvent(event)
        self.raise_()
        self.activateWindow()

    def _browse(self):
        d = QFileDialog.getExistingDirectory(
            self, "Select save folder", self.dir_edit.text()
        )
        if d:
            self.dir_edit.setText(d)

    def _start_probe(self):
        url = self.url_edit.text().strip()
        if not url.lower().startswith(("http://", "https://")):
            self.info_label.setText("")
            self.format_label.setVisible(False)
            self.format_combo.setVisible(False)
            return
        self._gen += 1
        gen = self._gen
        self.is_media = (
            self.kind in ("media", "hls", "dash")
            or self.stream_type in ("hls", "dash", "media")
            or is_media_url(url)
        )
        self.is_hls = (
            (
                self.kind == "hls"
                or self.stream_type == "hls"
                or is_hls_url(url)
            )
            and not self.is_media
        )

        if self.is_media:
            self.format_label.setVisible(True)
            self.format_combo.setVisible(True)
            if self.format_combo.count() == 0:
                default_opt = QualityOption(
                    label="Best Video + Audio (MP4)",
                    format_id="bv*+ba/b",
                    ext="mp4",
                )
                self.format_combo.addItem(
                    default_opt.label, userData=default_opt
                )
            self.info_label.setText("Probing media stream (yt-dlp)...")
        elif self.is_hls:
            self.format_label.setVisible(False)
            self.format_combo.setVisible(False)
            self.info_label.setText(
                "HLS video stream - parts are downloaded in parallel and merged"
            )
            return
        else:
            self.format_label.setVisible(False)
            self.format_combo.setVisible(False)
            self.info_label.setText("Contacting server...")

        def work():
            m_res = None
            u_res = None
            try:
                if self.is_media:
                    m_res = probe_media(
                        url,
                        cookies=self.cookies,
                        user_agent=self.user_agent,
                        referer=self.referer,
                        origin=self.origin,
                    )
                else:
                    u_res = probe_url(
                        url,
                        self.cookies,
                        self.user_agent,
                        self.referer,
                        timeout=(8, 12),
                    )
            except Exception:
                pass
            with self._probe_lock:
                self._probe_out = (gen, self.is_media, m_res, u_res)

        threading.Thread(target=work, daemon=True).start()

    def _poll_probe(self):
        with self._probe_lock:
            out, self._probe_out = self._probe_out, None
        if not out:
            return
        if not isinstance(out, tuple) or len(out) != 4:
            return
        gen, is_media, m_res, u_res = out
        if gen != self._gen:
            return

        if is_media:
            if m_res is None:
                self.info_label.setText(
                    "Could not probe media (the download may still work)."
                )
                self.info_label.setStyleSheet(
                    "color: #9aa0aa; font-size: 12px;"
                )
                return
            self._probed_media_result = m_res

            if m_res.is_live:
                self.info_label.setText(
                    "Active livestream detected. Only VOD (non-live) streams are supported."
                )
                self.info_label.setStyleSheet(
                    "color: #cf5c5c; font-weight: bold; font-size: 12px;"
                )
            else:
                dur_str = (
                    f" ({m_res.duration // 60}m {m_res.duration % 60:02d}s)"
                    if m_res.duration
                    else ""
                )
                self.info_label.setText(f"{m_res.title}{dur_str}")
                self.info_label.setStyleSheet(
                    "color: #9aa0aa; font-size: 12px;"
                )

            self.format_combo.blockSignals(True)
            self.format_combo.clear()
            formats = m_res.formats
            if not isinstance(formats, (list, tuple)):
                formats = []
            for opt in formats:
                self.format_combo.addItem(opt.label, userData=opt)
            self.format_combo.blockSignals(False)

            subtitles = m_res.subtitles
            if isinstance(subtitles, (list, tuple)):
                self._populate_subtitles(
                    [subtitle for subtitle in subtitles if isinstance(subtitle, dict)]
                )

            cur_opt = self.format_combo.currentData()
            ext = cur_opt.ext if cur_opt else "mp4"

            if not self._name_edited:
                title = m_res.sanitized_title or "video"
                self.name_edit.setText(f"{title}.{ext}")
            else:
                current_name = self.name_edit.text()
                stem, existing_ext = os.path.splitext(current_name)
                if not existing_ext and stem:
                    self.name_edit.setText(f"{stem}.{ext}")
        else:
            if u_res is None:
                self.info_label.setText(
                    "Could not probe the server (the download may still work)."
                )
                self.info_label.setStyleSheet(
                    "color: #9aa0aa; font-size: 12px;"
                )
                return
            size = (
                format_size(u_res.file_size)
                if u_res.file_size
                else "unknown size"
            )
            rng = (
                "resumable, multi-connection"
                if u_res.supports_ranges
                else "single connection only"
            )
            self.info_label.setText(f"{size}  ·  {rng}")
            self.info_label.setStyleSheet("color: #9aa0aa; font-size: 12px;")
            if u_res.filename and not self._name_edited:
                self.name_edit.setText(u_res.filename)

    def _on_format_changed(self):
        if not self.is_media or not self._probed_media_result:
            return
        cur_opt = self.format_combo.currentData()
        if not cur_opt:
            return
        if not self._name_edited:
            self.name_edit.setText(
                f"{self._probed_media_result.sanitized_title}.{cur_opt.ext}"
            )
        else:
            current_name = self.name_edit.text()
            stem, _ = os.path.splitext(current_name)
            if stem:
                self.name_edit.setText(f"{stem}.{cur_opt.ext}")

    def accept(self):
        url = self.url_edit.text().strip()
        if not url.lower().startswith(("http://", "https://")):
            QMessageBox.warning(
                self, "Invalid URL", "Please enter a valid http:// or https:// URL."
            )
            return
        if self._probed_media_result and self._probed_media_result.is_live:
            QMessageBox.warning(
                self,
                "Livestream Not Supported",
                "This URL is an active livestream. CIDM only supports VOD (video-on-demand) streams and files.\n\n"
                "Please select a recorded/completed video.",
            )
            return
        folder = self.dir_edit.text().strip()
        if not folder:
            QMessageBox.warning(
                self, "Save folder", "Please choose a folder to save to."
            )
            return
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError as exc:
            QMessageBox.warning(
                self, "Save folder", f"Cannot use that folder:\n{exc}"
            )
            return
        super().accept()

    def values(self) -> dict:
        cur_opt = self.format_combo.currentData() if self.is_media else None
        sub_track = self.sub_track_combo.currentData()
        sub_mode = self.sub_mode_combo.currentData() or "embed"
        selected_ips = [
            ip for cb, ip, name in self.adapter_checkboxes if cb.isChecked()
        ]
        proxy_pool = list(self.settings.get("proxy_pool") or [])
        proxy_pool_enabled = (
            self.cb_use_proxy_pool.isChecked()
            if self.cb_use_proxy_pool
            else bool(self.settings.get("proxy_pool_enabled", False))
        )
        proxy_pool_include_direct = bool(
            self.settings.get("proxy_pool_include_direct", True)
        )
        return {
            "url": self.url_edit.text().strip(),
            "filename": self.name_edit.text().strip(),
            "save_dir": self.dir_edit.text().strip(),
            "threads": self.thread_spin.value(),
            "cookies": self.cookies,
            "user_agent": self.user_agent,
            "referer": self.referer,
            "origin": self.origin,
            "stream_type": self.stream_type,
            "kind": "media"
            if self.is_media
            else ("hls" if self.is_hls else ""),
            "format_id": cur_opt.format_id if cur_opt else "",
            "quality_label": cur_opt.label if cur_opt else "",
            "media_title": self._probed_media_result.title
            if self._probed_media_result
            else "",
            "subtitle_track": sub_track,
            "subtitle_mode": sub_mode,
            "selected_ips": selected_ips,
            "proxy_pool": proxy_pool,
            "proxy_pool_enabled": proxy_pool_enabled,
            "proxy_pool_include_direct": proxy_pool_include_direct,
        }


# --------------------------------------------------------------------------- #
# Segment Visualizer & Media Status Panel
# --------------------------------------------------------------------------- #
class SegmentVisualizerWidget(QWidget):
    """Draws IDM-style byte-range segments and dynamic work stealing across chunks."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFixedHeight(14)
        self.file_size = 0
        self.segments: List[Dict[str, Any]] = []

    def update_segments(self, file_size: int, segments: List[Dict[str, Any]]):
        self.file_size = max(0, file_size)
        self.segments = segments or []
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        w, h = self.width(), self.height()

        painter.setBrush(QBrush(QColor("#141518")))
        painter.setPen(QPen(QColor("#33373e"), 1))
        painter.drawRoundedRect(0, 0, w - 1, h - 1, 4, 4)

        if not self.segments or self.file_size <= 0:
            return

        for s in self.segments:
            start_x = int((s["start"] / self.file_size) * (w - 2)) + 1
            end_x = int(((s["end"] + 1) / self.file_size) * (w - 2)) + 1
            pos_x = (
                int(
                    (min(s["end"] + 1, s.get("pos", s["start"])) / self.file_size)
                    * (w - 2)
                )
                + 1
            )

            chunk_w = max(1, end_x - start_x)
            done_w = max(0, min(chunk_w, pos_x - start_x))

            painter.fillRect(start_x, 1, chunk_w, h - 2, QColor("#282b30"))
            if done_w > 0:
                is_active = s.get("active", False)
                is_done = s.get("pos", 0) > s["end"]
                color = (
                    QColor("#4ea876")
                    if is_done
                    else (
                        QColor("#5f96d6")
                        if is_active
                        else QColor("#4f86c6")
                    )
                )
                painter.fillRect(start_x, 1, done_w, h - 2, color)

            painter.setPen(QPen(QColor("#18191c"), 1))
            painter.drawLine(end_x, 1, end_x, h - 2)


class SegmentPanel(QGroupBox):
    def __init__(self):
        super().__init__("Connections && Progress")
        self.setObjectName("segmentPanel")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 6, 8, 6)
        outer.setSpacing(6)
        self.summary = QLabel("Select a download to see its details.")
        self.summary.setStyleSheet("color: #9aa0aa; font-size: 11px;")
        outer.addWidget(self.summary)

        # Multi-Interface Link Aggregation Real-Time Throughput Banner
        self.adapter_summary = QLabel("")
        self.adapter_summary.setStyleSheet(
            "color: #4f86c6; font-size: 11px; font-weight: 600; padding: 1px 0;"
        )
        self.adapter_summary.setVisible(False)
        outer.addWidget(self.adapter_summary)

        # IDM Visualizer Strip
        self.visualizer = SegmentVisualizerWidget()
        outer.addWidget(self.visualizer)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.content_widget = QWidget()
        cw_layout = QVBoxLayout(self.content_widget)
        cw_layout.setContentsMargins(0, 0, 0, 0)
        cw_layout.setSpacing(4)

        self.container = QWidget()
        self.grid = QGridLayout(self.container)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(8)
        self.grid.setVerticalSpacing(3)
        self.grid.setColumnStretch(1, 1)

        self.media_container = QWidget()
        media_box = QVBoxLayout(self.media_container)
        media_box.setContentsMargins(2, 2, 2, 2)
        media_box.setSpacing(6)

        self.media_grid = QGridLayout()
        self.media_grid.setHorizontalSpacing(12)
        self.media_grid.setVerticalSpacing(4)

        lbl_f = QLabel("Stream Format:")
        lbl_f.setStyleSheet(
            "color: #9aa0aa; font-weight: 600; font-size: 11px;")
        self.lbl_format = QLabel("")
        self.lbl_format.setStyleSheet("font-weight: 500; font-size: 11px;")

        lbl_r = QLabel("Resolution:")
        lbl_r.setStyleSheet(
            "color: #9aa0aa; font-weight: 600; font-size: 11px;")
        self.lbl_res = QLabel("")
        self.lbl_res.setStyleSheet("font-weight: 500; font-size: 11px;")

        lbl_m = QLabel("FFmpeg State:")
        lbl_m.setStyleSheet(
            "color: #9aa0aa; font-weight: 600; font-size: 11px;")
        self.lbl_merge = QLabel("")
        self.lbl_merge.setStyleSheet(
            "color: #4f86c6; font-weight: 600; font-size: 11px;")

        lbl_s = QLabel("Downloaded Stats:")
        lbl_s.setStyleSheet(
            "color: #9aa0aa; font-weight: 600; font-size: 11px;")
        self.lbl_stats = QLabel("")
        self.lbl_stats.setStyleSheet("font-size: 11px;")

        self.media_grid.addWidget(lbl_f, 0, 0)
        self.media_grid.addWidget(self.lbl_format, 0, 1)
        self.media_grid.addWidget(lbl_r, 0, 2)
        self.media_grid.addWidget(self.lbl_res, 0, 3)
        self.media_grid.addWidget(lbl_m, 1, 0)
        self.media_grid.addWidget(self.lbl_merge, 1, 1)
        self.media_grid.addWidget(lbl_s, 1, 2)
        self.media_grid.addWidget(self.lbl_stats, 1, 3)
        self.media_grid.setColumnStretch(1, 1)
        self.media_grid.setColumnStretch(3, 1)

        self.media_bar = QProgressBar()
        self.media_bar.setRange(0, 1000)
        self.media_bar.setFixedHeight(14)

        media_box.addLayout(self.media_grid)
        media_box.addWidget(self.media_bar)

        cw_layout.addWidget(self.container)
        cw_layout.addWidget(self.media_container)
        scroll.setWidget(self.content_widget)
        outer.addWidget(scroll, 1)

        self.media_container.hide()
        self._rows: List[tuple] = []

    def _clear(self):
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._rows = []

    def _rebuild(self, n: int):
        self._clear()
        for i in range(n):
            lbl = QLabel(f"Thread {i + 1}")
            lbl.setMinimumWidth(145)
            lbl.setStyleSheet("color: #9aa0aa; font-size: 11px;")
            bar = QProgressBar()
            bar.setRange(0, 1000)
            bar.setFixedHeight(12)
            info = QLabel("")
            info.setFixedWidth(135)
            info.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            info.setStyleSheet("color: #9aa0aa; font-size: 11px;")
            self.grid.addWidget(lbl, i, 0)
            self.grid.addWidget(bar, i, 1)
            self.grid.addWidget(info, i, 2)
            self._rows.append((lbl, bar, info))
        self.grid.setRowStretch(n, 1)

    def show_snapshot(self, snap: Optional[dict]):
        if snap is None:
            self._clear()
            self.setTitle("Connections && Progress")
            self.visualizer.update_segments(0, [])
            self.container.hide()
            self.media_container.hide()
            self.adapter_summary.setVisible(False)
            self.summary.setText("Select a download to see its details.")
            return

        if snap.get("is_media"):
            self.setTitle("Media Stream Details")
            self.visualizer.update_segments(0, [])
            self.container.hide()
            self.media_container.show()
            self.adapter_summary.setVisible(False)
            title = (
                snap.get("title") or snap.get("filename") or "Media Download"
            )
            self.summary.setText(f"{title}  ·  {snap['status']}")

            q_label = snap.get("quality_label") or "Best Video + Audio"
            self.lbl_format.setText(q_label)

            res = snap.get("resolution")
            if not res:
                res = (
                    q_label.split()[0]
                    if "p (" in q_label
                    else "Best Available"
                )
            self.lbl_res.setText(res)

            merge_state = (
                snap.get("merge_state")
                or snap.get("ffmpeg_status")
                or "Ready"
            )
            self.lbl_merge.setText(merge_state)

            dl_str = format_size(snap["downloaded"])
            sz_str = (
                format_size(snap["file_size"])
                if snap["file_size"]
                else "Unknown"
            )
            speed_txt = (
                f" @ {snap['speed_str']}" if snap.get("speed_str") else ""
            )
            eta_txt = (
                f", ETA: {snap['eta_str']}"
                if snap.get("eta_str") and snap["eta_str"] != "-"
                else ""
            )
            self.lbl_stats.setText(
                f"{dl_str} of {sz_str}{speed_txt}{eta_txt}"
            )

            self.media_bar.setValue(int(snap["percent"] * 10))
            self.media_bar.setFormat(f"{snap['percent']:.1f}%")
            state = {
                Status.COMPLETED: "done",
                Status.ERROR: "error",
                Status.PAUSED: "paused",
                Status.PAUSING: "paused",
            }.get(snap["status"], "")
            if self.media_bar.property("state") != state:
                self.media_bar.setProperty("state", state)
                self.media_bar.style().unpolish(self.media_bar)
                self.media_bar.style().polish(self.media_bar)
            return

        self.setTitle("Connections && Progress")
        self.media_container.hide()
        self.container.show()
        segs = snap["segments"]
        self.visualizer.update_segments(snap.get("file_size", 0), segs)

        # Update multi-interface link aggregation / proxy pool throughput summary
        route_stats = (
            snap.get("route_stats") or snap.get("interface_stats") or {}
        )
        if route_stats:
            stat_parts = []
            has_proxy = False
            for r_key, sinfo in route_stats.items():
                name = sinfo.get("adapter") or r_key
                if any(
                    x in str(r_key).lower()
                    for x in ("proxy", "socks", "http://", "https://")
                ):
                    has_proxy = True
                sp = sinfo.get("speed_str") or "0 B/s"
                b = sinfo.get("bytes_str") or "0 B"
                stat_parts.append(f"{name}: {sp} ({b})")
            if stat_parts:
                prefix = (
                    "Multi-IP / Proxy Pool:  "
                    if has_proxy
                    else "Link Aggregation:  "
                )
                self.adapter_summary.setText(prefix + "  |  ".join(stat_parts))
                self.adapter_summary.setVisible(True)
            else:
                self.adapter_summary.setVisible(False)
        else:
            self.adapter_summary.setVisible(False)

        if not segs:
            self._clear()
            self.summary.setText(
                f"{snap['filename'] or 'Download'}: {snap['status']} — "
                "connection details appear once the download starts."
            )
            return
        if len(segs) != len(self._rows):
            self._rebuild(len(segs))
        mode = (
            "multi-connection (work stealing)"
            if snap["supports_ranges"]
            else "single connection"
        )
        self.summary.setText(
            f"{snap['filename']}  ·  {len(segs)} segment(s) ({mode})  ·  "
            f"{format_size(snap['downloaded'])} of "
            f"{format_size(snap['file_size']) if snap['file_size'] else 'unknown'}"
        )
        for i, (seg, (lbl, bar, info)) in enumerate(zip(segs, self._rows)):
            route_lbl = seg.get("route_label") or seg.get("adapter_name")
            if not route_lbl and seg.get("source_ip"):
                route_lbl = seg["source_ip"]
            if route_lbl and route_lbl != "Default":
                lbl.setText(f"Thread {i + 1} [{route_lbl}]")
            else:
                lbl.setText(f"Thread {i + 1}")

            if seg["length"] > 0:
                bar.setRange(0, 1000)
                bar.setValue(int(seg["percent"] * 10))
                bar.setFormat(f"{seg['percent']:.1f}%")
                if snap.get("unit") == "segments":
                    info.setText(
                        f"{seg['downloaded']} / {seg['length']} parts"
                    )
                else:
                    info.setText(
                        f"{format_size(seg['downloaded'])} / {format_size(seg['length'])}"
                    )
                state = "done" if seg["downloaded"] >= seg["length"] else ""
            else:
                bar.setRange(0, 0) if snap[
                    "status"
                ] == Status.DOWNLOADING else bar.setRange(0, 1000)
                bar.setFormat("")
                info.setText(format_size(seg["downloaded"]))
                state = ""
            if bar.property("state") != state:
                bar.setProperty("state", state)
                bar.style().unpolish(bar)
                bar.style().polish(bar)


# --------------------------------------------------------------------------- #
# Checksum Verifier Thread & Properties Dialog
# --------------------------------------------------------------------------- #
class ChecksumThread(QThread):
    progress = Signal(int, int)
    finished = Signal(str)

    def __init__(self, filepath: str, algo: str):
        super().__init__()
        self.filepath = filepath
        self.algo = algo
        self._cancel_flag = threading.Event()

    def cancel(self):
        self._cancel_flag.set()

    def run(self):
        def _cb(done, total):
            self.progress.emit(done, total)

        res = calculate_file_checksum(
            self.filepath, self.algo, _cb, self._cancel_flag
        )
        self.finished.emit(res)


class PropertiesDialog(QDialog):
    def __init__(self, parent: QWidget, task: DownloadTask):
        super().__init__(parent)
        self.task = task
        self.setWindowTitle(f"Properties — {task.filename or 'Download'}")
        self.resize(520, 410)
        self.setModal(True)
        self._calc_thread: Optional[ChecksumThread] = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(14, 14, 14, 14)

        tabs = QTabWidget()

        # General Tab
        w_gen = QWidget()
        l_gen = QFormLayout(w_gen)
        l_gen.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        l_gen.setContentsMargins(14, 14, 14, 14)
        l_gen.setSpacing(8)

        self.edit_url = QLineEdit(self.task.url)
        self.edit_url.setReadOnly(True)
        l_gen.addRow("URL:", self.edit_url)

        self.edit_file = QLineEdit(self.task.filename)
        self.edit_file.setReadOnly(True)
        l_gen.addRow("Filename:", self.edit_file)

        self.edit_path = QLineEdit(self.task.save_dir)
        self.edit_path.setReadOnly(True)
        l_gen.addRow("Folder:", self.edit_path)

        sz_str = (
            format_size(self.task.file_size)
            if self.task.file_size
            else "Unknown"
        )
        l_gen.addRow("File Size:", QLabel(sz_str))

        resumable = (
            "Yes (Byte ranges supported)"
            if getattr(self.task, "supports_ranges", False)
            else "No (Single connection)"
        )
        l_gen.addRow("Resume Support:", QLabel(resumable))

        l_gen.addRow("Current Status:", QLabel(self.task.status))
        q_name = getattr(self.task, "queue_name", "Main Download Queue")
        l_gen.addRow("Assigned Queue:", QLabel(q_name))

        if self.task.referer:
            ref_edit = QLineEdit(self.task.referer)
            ref_edit.setReadOnly(True)
            l_gen.addRow("Referer:", ref_edit)

        tabs.addTab(w_gen, "General")

        # Checksum Verification Tab
        w_chk = QWidget()
        l_chk = QVBoxLayout(w_chk)
        l_chk.setContentsMargins(16, 16, 16, 16)
        l_chk.setSpacing(12)

        top_row = QHBoxLayout()
        top_row.setSpacing(8)
        top_row.addWidget(QLabel("Algorithm:"))
        self.cb_algo = QComboBox()
        self.cb_algo.addItems(["SHA-256", "MD5", "SHA-1"])
        top_row.addWidget(self.cb_algo)
        top_row.addStretch()

        self.btn_calc = QPushButton("Calculate Checksum")
        self.btn_calc.clicked.connect(self._start_calc)
        top_row.addWidget(self.btn_calc)
        l_chk.addLayout(top_row)

        self.chk_bar = QProgressBar()
        self.chk_bar.setRange(0, 1000)
        self.chk_bar.setValue(0)
        self.chk_bar.setFixedHeight(16)
        self.chk_bar.setVisible(False)
        l_chk.addWidget(self.chk_bar)

        form_chk = QFormLayout()
        form_chk.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form_chk.setSpacing(10)
        self.edit_calc_hash = QLineEdit()
        self.edit_calc_hash.setReadOnly(True)
        self.edit_calc_hash.setPlaceholderText(
            "Click 'Calculate Checksum' to compute"
        )
        form_chk.addRow("Calculated Hash:", self.edit_calc_hash)

        self.edit_expected_hash = QLineEdit()
        self.edit_expected_hash.setPlaceholderText(
            "Paste expected hash here to compare"
        )
        self.edit_expected_hash.textChanged.connect(self._compare_hash)
        form_chk.addRow("Expected Hash:", self.edit_expected_hash)

        self.lbl_match_result = QLabel("")
        self.lbl_match_result.setStyleSheet(
            "font-weight: 600; font-size: 13px;"
        )
        form_chk.addRow("Verification:", self.lbl_match_result)
        l_chk.addLayout(form_chk)
        l_chk.addStretch()

        tabs.addTab(w_chk, "Checksum Verifier")
        layout.addWidget(tabs)

        btn_box = QHBoxLayout()
        btn_box.addStretch()
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        btn_box.addWidget(btn_close)
        layout.addLayout(btn_box)

    def _start_calc(self):
        target = os.path.join(self.task.save_dir, self.task.filename)
        if not os.path.isfile(target):
            QMessageBox.warning(
                self,
                "File Not Found",
                f"Cannot find '{target}' on disk.\nDownload must be completed first.",
            )
            return

        self.btn_calc.setEnabled(False)
        self.chk_bar.setVisible(True)
        self.chk_bar.setValue(0)
        self.lbl_match_result.setText("Computing hash...")
        self.lbl_match_result.setStyleSheet("color: #4f86c6;")

        algo = self.cb_algo.currentText().lower().replace("-", "")
        self._calc_thread = ChecksumThread(target, algo)
        self._calc_thread.progress.connect(self._on_progress)
        self._calc_thread.finished.connect(self._on_finished)
        self._calc_thread.start()

    def _on_progress(self, done, total):
        if total > 0:
            self.chk_bar.setValue(int(done / total * 1000))

    def _on_finished(self, hash_str):
        self.btn_calc.setEnabled(True)
        self.chk_bar.setVisible(False)
        self.edit_calc_hash.setText(hash_str)
        self._compare_hash()

    def _compare_hash(self):
        calc = self.edit_calc_hash.text().strip().lower()
        exp = self.edit_expected_hash.text().strip().lower()
        if not calc or not exp:
            self.lbl_match_result.setText("Enter expected hash to verify")
            self.lbl_match_result.setStyleSheet("color: #9aa0aa;")
            return
        if calc == exp:
            self.lbl_match_result.setText(
                "Checksum MATCH (Integrity Verified)"
            )
            self.lbl_match_result.setStyleSheet(
                "color: #4ea876; font-weight: bold;"
            )
        else:
            self.lbl_match_result.setText(
                "Checksum MISMATCH (File Corrupted or Altered)"
            )
            self.lbl_match_result.setStyleSheet(
                "color: #cf5c5c; font-weight: bold;"
            )


# --------------------------------------------------------------------------- #
# Refresh Address Dialog (Expired CDN links)
# --------------------------------------------------------------------------- #
class RefreshAddressDialog(QDialog):
    def __init__(self, parent: QWidget, task: DownloadTask):
        super().__init__(parent)
        self.task = task
        self.setWindowTitle("Refresh Download Address")
        self.resize(560, 260)
        self.setModal(True)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(18, 18, 18, 16)

        lbl_info = QLabel(
            "If a download failed or paused because its link expired (common on cloud hosts or CDNs),\n"
            "generate a fresh download link in your browser and paste it below to resume seamlessly."
        )
        lbl_info.setStyleSheet("color: #9aa0aa; line-height: 1.4;")
        lbl_info.setWordWrap(True)
        layout.addWidget(lbl_info)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setSpacing(10)
        self.lbl_name = QLabel(self.task.filename)
        self.lbl_name.setStyleSheet("font-weight: 600;")
        form.addRow("File:", self.lbl_name)

        self.edit_old_url = QLineEdit(self.task.url)
        self.edit_old_url.setReadOnly(True)
        form.addRow("Original URL:", self.edit_old_url)

        self.edit_new_url = QLineEdit()
        self.edit_new_url.setPlaceholderText(
            "https://... (paste fresh link here)"
        )
        form.addRow("New URL:", self.edit_new_url)
        layout.addLayout(form)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_browser = QPushButton("Open Source in Browser")
        btn_browser.clicked.connect(self._open_browser)
        btn_row.addWidget(btn_browser)
        btn_row.addStretch()

        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)

        btn_apply = QPushButton("Update & Resume")
        btn_apply.setObjectName("primaryBtn")
        btn_apply.clicked.connect(self._apply)
        btn_row.addWidget(btn_apply)

        layout.addLayout(btn_row)

    def _open_browser(self):
        ref = self.task.referer or self.task.url
        QDesktopServices.openUrl(QUrl(ref))

    def _apply(self):
        new_url = self.edit_new_url.text().strip()
        if not new_url.startswith(("http://", "https://")):
            QMessageBox.warning(
                self,
                "Invalid URL",
                "Please enter a valid http(s):// download link.",
            )
            return
        self.task.refresh_url(new_url)
        self.task.resume()
        self.accept()


# --------------------------------------------------------------------------- #
# Post-Queue Countdown Dialog
# --------------------------------------------------------------------------- #
class CountdownDialog(QDialog):
    def __init__(self, parent: QWidget, action_name: str, seconds: int = 10):
        super().__init__(parent)
        self.action_name = action_name
        self.remaining = seconds
        self.cancelled = False
        self.setWindowTitle(f"CIDM — {action_name}")
        self.setFixedSize(380, 175)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(20, 20, 20, 20)

        self.lbl_msg = QLabel(
            f"Download queue completed.\nComputer will {action_name.lower()} in {self.remaining} seconds."
        )
        self.lbl_msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_msg.setStyleSheet("font-size: 14px; font-weight: 500;")
        layout.addWidget(self.lbl_msg)

        btn_box = QHBoxLayout()
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setStyleSheet(
            "padding: 8px 24px; font-weight: bold; background-color: #cf5c5c; border-color: #cf5c5c; color: white;"
        )
        self.btn_cancel.clicked.connect(self._cancel)
        btn_box.addStretch()
        btn_box.addWidget(self.btn_cancel)
        btn_box.addStretch()
        layout.addLayout(btn_box)

        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

    def _tick(self):
        self.remaining -= 1
        if self.remaining <= 0:
            self.timer.stop()
            self.accept()
            execute_system_action(self.action_name)
        else:
            self.lbl_msg.setText(
                f"Download queue completed.\nComputer will {self.action_name.lower()} in {self.remaining} seconds."
            )

    def _cancel(self):
        self.cancelled = True
        self.timer.stop()
        self.reject()


# --------------------------------------------------------------------------- #
# Batch Download & Pattern Generator Dialog
# --------------------------------------------------------------------------- #
class BatchDownloadDialog(QDialog):
    def __init__(
        self,
        parent: QWidget,
        initial_urls: Optional[List[str]] = None,
        referer: str = "",
        save_dir: str = "",
        threads: int = 8,
    ):
        super().__init__(parent)
        self.setWindowTitle("Batch Download / Pattern Generator")
        self.resize(720, 500)
        self.setModal(True)
        self.referer = referer
        self.save_dir = save_dir or default_download_dir()
        self.threads = threads
        self._build_ui(initial_urls or [])

    def _build_ui(self, initial_urls: List[str]):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(14, 14, 14, 14)

        self.tabs = QTabWidget()

        # Tab 1: Wildcard Generator
        w_pat = QWidget()
        l_pat = QVBoxLayout(w_pat)
        l_pat.setContentsMargins(12, 12, 12, 12)
        l_pat.setSpacing(8)

        f_pat = QFormLayout()
        f_pat.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.edit_pattern = QLineEdit()
        self.edit_pattern.setPlaceholderText(
            "https://example.com/files/part[01-20].zip  or  img_[a-z].jpg"
        )
        f_pat.addRow("Pattern URL:", self.edit_pattern)
        l_pat.addLayout(f_pat)

        lbl_pat_hint = QLabel(
            "Wildcard Examples: [01-20] (zero-padded numbers), [1-100] (integers), [a-z] (letters)"
        )
        lbl_pat_hint.setStyleSheet("color: #9aa0aa; font-size: 12px;")
        l_pat.addWidget(lbl_pat_hint)

        btn_gen_row = QHBoxLayout()
        btn_gen = QPushButton("Generate Matching URLs")
        btn_gen.clicked.connect(self._generate_wildcard)
        btn_gen_row.addWidget(btn_gen)
        btn_gen_row.addStretch()
        l_pat.addLayout(btn_gen_row)
        self.tabs.addTab(w_pat, "Wildcard Pattern")

        # Tab 2: Paste / Import List
        w_txt = QWidget()
        l_txt = QVBoxLayout(w_txt)
        l_txt.setContentsMargins(14, 14, 14, 14)
        l_txt.setSpacing(10)

        self.edit_urls_text = QTextEdit()
        self.edit_urls_text.setPlaceholderText(
            "Paste URLs here (one URL per line)..."
        )
        if initial_urls:
            self.edit_urls_text.setPlainText("\n".join(initial_urls))
        l_txt.addWidget(self.edit_urls_text)

        row_txt = QHBoxLayout()
        row_txt.setSpacing(8)
        btn_import = QPushButton("Import from .txt File...")
        btn_import.clicked.connect(self._import_txt)
        row_txt.addWidget(btn_import)
        row_txt.addStretch()

        btn_filter = QPushButton("Filter & Populate List")
        btn_filter.clicked.connect(self._populate_from_text)
        row_txt.addWidget(btn_filter)
        l_txt.addLayout(row_txt)
        self.tabs.addTab(w_txt, "Paste / Import URL List")

        layout.addWidget(self.tabs)

        # Preview Table
        layout.addWidget(QLabel("Items to Download:"))
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["", "File Name", "URL"])
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Fixed
        )
        self.table.setColumnWidth(0, 38)
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Interactive
        )
        self.table.setColumnWidth(1, 210)
        self.table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(32)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        layout.addWidget(self.table)

        tbl_ctrl = QHBoxLayout()
        tbl_ctrl.setSpacing(8)
        btn_sel_all = QPushButton("Select All")
        btn_sel_all.clicked.connect(lambda: self._set_all_checked(True))
        btn_desel_all = QPushButton("Deselect All")
        btn_desel_all.clicked.connect(lambda: self._set_all_checked(False))
        self.lbl_count = QLabel("0 item(s) selected")
        self.lbl_count.setStyleSheet("color: #9aa0aa;")
        tbl_ctrl.addWidget(btn_sel_all)
        tbl_ctrl.addWidget(btn_desel_all)
        tbl_ctrl.addSpacing(8)
        tbl_ctrl.addWidget(self.lbl_count)
        tbl_ctrl.addStretch()
        layout.addLayout(tbl_ctrl)

        # Destination & Queue options
        b_form = QFormLayout()
        b_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        b_form.setSpacing(10)
        d_row = QHBoxLayout()
        d_row.setSpacing(8)
        self.edit_save_dir = QLineEdit(self.save_dir)
        btn_browse = QPushButton("Browse...")
        btn_browse.clicked.connect(self._browse_dir)
        d_row.addWidget(self.edit_save_dir, 1)
        d_row.addWidget(btn_browse)
        b_form.addRow("Save To:", d_row)

        q_row = QHBoxLayout()
        q_row.setSpacing(10)
        self.combo_queue = QComboBox()
        self.combo_queue.addItems(
            ["Main Download Queue", "Synchronization Queue"]
        )
        self.combo_queue.setEditable(True)
        q_row.addWidget(self.combo_queue, 1)

        q_row.addWidget(QLabel("Threads:"))
        self.spin_th = QSpinBox()
        self.spin_th.setRange(1, 32)
        self.spin_th.setValue(self.threads)
        self.spin_th.setFixedWidth(80)
        q_row.addWidget(self.spin_th)
        b_form.addRow("Add To Queue:", q_row)
        layout.addLayout(b_form)

        # Dialog Buttons
        btn_box = QHBoxLayout()
        btn_box.setSpacing(8)
        btn_box.addStretch()
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_box.addWidget(btn_cancel)

        self.btn_download = QPushButton("Start Download / Queue")
        self.btn_download.setObjectName("primaryBtn")
        self.btn_download.clicked.connect(self.accept)
        btn_box.addWidget(self.btn_download)
        layout.addLayout(btn_box)

        if initial_urls:
            self._populate_from_text()

    def _row_checkbox(self, row: int) -> Optional[QCheckBox]:
        w = self.table.cellWidget(row, 0)
        if isinstance(w, QCheckBox):
            return w
        if w is not None:
            return w.findChild(QCheckBox)
        return None

    def _browse_dir(self):
        d = QFileDialog.getExistingDirectory(
            self, "Select Save Directory", self.edit_save_dir.text()
        )
        if d:
            self.edit_save_dir.setText(d)

    def _set_all_checked(self, checked: bool):
        for r in range(self.table.rowCount()):
            cb = self._row_checkbox(r)
            if cb is not None:
                cb.setChecked(checked)
        self._update_count()

    def _update_count(self):
        count = sum(
            1
            for r in range(self.table.rowCount())
            if getattr(self._row_checkbox(r), "isChecked", lambda: False)()
        )
        self.lbl_count.setText(
            f"{count} of {self.table.rowCount()} item(s) selected"
        )

    def _generate_wildcard(self):
        pattern = self.edit_pattern.text().strip()
        if not pattern:
            return

        m_num = re.search(r"\[(\d+)-(\d+)\]", pattern)
        m_char = re.search(r"\[([a-zA-Z])-([a-zA-Z])\]", pattern)

        generated = []
        if m_num:
            s_str, e_str = m_num.group(1), m_num.group(2)
            pad_len = (
                len(s_str) if s_str.startswith("0") and len(s_str) > 1 else 0
            )
            start, end = int(s_str), int(e_str)
            step = 1 if end >= start else -1
            for n in range(start, end + step, step):
                n_str = str(n).zfill(pad_len) if pad_len else str(n)
                url = pattern[: m_num.start()] + n_str + pattern[m_num.end():]
                generated.append(url)
        elif m_char:
            c1, c2 = ord(m_char.group(1)), ord(m_char.group(2))
            step = 1 if c2 >= c1 else -1
            for code in range(c1, c2 + step, step):
                url = (
                    pattern[: m_char.start()]
                    + chr(code)
                    + pattern[m_char.end():]
                )
                generated.append(url)
        else:
            QMessageBox.warning(
                self,
                "Invalid Pattern",
                "Could not find a valid range like [01-20] or [a-z] in pattern.",
            )
            return

        self._fill_table(generated)

    def _import_txt(self):
        fn, _ = QFileDialog.getOpenFileName(
            self,
            "Import Links from Text File",
            "",
            "Text Files (*.txt);;All Files (*.*)",
        )
        if fn and os.path.isfile(fn):
            try:
                with open(fn, "r", encoding="utf-8", errors="ignore") as f:
                    self.edit_urls_text.setPlainText(f.read())
                self._populate_from_text()
            except Exception as e:
                QMessageBox.warning(
                    self, "Import Error", f"Could not read file: {e}"
                )

    def _populate_from_text(self):
        raw = self.edit_urls_text.toPlainText()
        urls = []
        for line in raw.splitlines():
            u = line.strip()
            if u.startswith(("http://", "https://")):
                urls.append(u)
        self._fill_table(urls)

    def _fill_table(self, urls: List[str]):
        self.table.setRowCount(0)
        for u in urls:
            r = self.table.rowCount()
            self.table.insertRow(r)

            cb = QCheckBox()
            cb.setChecked(True)
            cb.toggled.connect(self._update_count)
            self.table.setCellWidget(r, 0, _center_widget_in_cell(cb))

            fname = filename_from_url(u)
            self.table.setItem(r, 1, QTableWidgetItem(fname))
            self.table.setItem(r, 2, QTableWidgetItem(u))

        self._update_count()

    def get_selected_tasks_info(self) -> List[Dict[str, Any]]:
        save_dir = (
            self.edit_save_dir.text().strip() or default_download_dir()
        )
        queue_name = (
            self.combo_queue.currentText().strip() or "Main Download Queue"
        )
        threads = self.spin_th.value()
        items = []

        for r in range(self.table.rowCount()):
            cb = self._row_checkbox(r)
            if cb and cb.isChecked():
                fname = self.table.item(r, 1).text()
                url = self.table.item(r, 2).text()
                items.append({
                    "url": url,
                    "filename": fname,
                    "save_dir": save_dir,
                    "threads": threads,
                    "queue_name": queue_name,
                    "referer": self.referer,
                })
        return items


# --------------------------------------------------------------------------- #
# Scheduler & Queue Manager Dialog
# --------------------------------------------------------------------------- #
class SchedulerDialog(QDialog):
    def __init__(
        self,
        parent: MainWindow,
        tasks: Dict[int, DownloadTask],
        queues_config: dict,
    ):
        super().__init__(parent)
        self.parent_window = parent
        self.tasks = tasks
        self.queues_config = dict(queues_config or {})
        self.setWindowTitle("Download Scheduler & Queues")
        self.resize(660, 480)
        self.setModal(True)
        self._ensure_default_queues()
        self._build_ui()

    def _ensure_default_queues(self):
        for qn in ["Main Download Queue", "Synchronization Queue"]:
            if qn not in self.queues_config:
                self.queues_config[qn] = {
                    "max_concurrent": 3 if qn == "Main Download Queue" else 1,
                    "start_time": None,
                    "stop_time": None,
                    "recurring": False,
                    "on_complete": "Do nothing",
                }

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(14, 14, 14, 14)

        # Top Queue Selector
        top_box = QHBoxLayout()
        top_box.setSpacing(8)
        top_box.addWidget(QLabel("Select Queue:"))
        self.cb_queue = QComboBox()
        self.cb_queue.addItems(list(self.queues_config.keys()))
        self.cb_queue.currentTextChanged.connect(self._on_queue_selected)
        top_box.addWidget(self.cb_queue, 1)

        btn_new_q = QPushButton("+ New Queue")
        btn_new_q.clicked.connect(self._add_queue)
        top_box.addWidget(btn_new_q)
        layout.addLayout(top_box)

        # Queue Items Table with Reordering
        mid_box = QHBoxLayout()
        mid_box.setSpacing(10)
        self.table_items = QTableWidget(0, 3)
        self.table_items.setHorizontalHeaderLabels(
            ["Order", "Filename", "Status"]
        )
        self.table_items.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Fixed
        )
        self.table_items.setColumnWidth(0, 60)
        self.table_items.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.table_items.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Interactive
        )
        self.table_items.setColumnWidth(2, 115)
        self.table_items.verticalHeader().setVisible(False)
        self.table_items.verticalHeader().setDefaultSectionSize(32)
        self.table_items.setAlternatingRowColors(True)
        self.table_items.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        mid_box.addWidget(self.table_items, 1)

        btn_vbox = QVBoxLayout()
        btn_vbox.setSpacing(8)
        self.btn_up = QPushButton("Move Up")
        self.btn_up.clicked.connect(self._move_up)
        self.btn_down = QPushButton("Move Down")
        self.btn_down.clicked.connect(self._move_down)
        btn_vbox.addWidget(self.btn_up)
        btn_vbox.addWidget(self.btn_down)
        btn_vbox.addStretch()
        mid_box.addLayout(btn_vbox)
        layout.addLayout(mid_box)

        # Schedule and Timing Box
        gb_timing = QGroupBox("Schedule && Concurrency Rules")
        f_timing = QFormLayout(gb_timing)
        f_timing.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        f_timing.setSpacing(10)

        self.spin_concur = QSpinBox()
        self.spin_concur.setRange(1, 8)
        self.spin_concur.setValue(3)
        self.spin_concur.setFixedWidth(80)
        f_timing.addRow(
            "Max Concurrent Downloads:", self.spin_concur
        )

        start_row = QHBoxLayout()
        start_row.setSpacing(10)
        self.chk_start = QCheckBox("Start queue at:")
        self.time_start = QTimeEdit(QTime.currentTime().addSecs(3600))
        self.time_start.setEnabled(False)
        self.chk_start.toggled.connect(self.time_start.setEnabled)
        start_row.addWidget(self.chk_start)
        start_row.addWidget(self.time_start)

        self.chk_daily = QCheckBox("Repeat Daily")
        start_row.addWidget(self.chk_daily)
        start_row.addStretch()
        f_timing.addRow("Start Trigger:", start_row)

        stop_row = QHBoxLayout()
        stop_row.setSpacing(10)
        self.chk_stop = QCheckBox("Stop queue at:")
        self.time_stop = QTimeEdit(QTime.currentTime().addSecs(7200))
        self.time_stop.setEnabled(False)
        self.chk_stop.toggled.connect(self.time_stop.setEnabled)
        stop_row.addWidget(self.chk_stop)
        stop_row.addWidget(self.time_stop)
        stop_row.addStretch()
        f_timing.addRow("Stop Trigger:", stop_row)

        self.combo_action = QComboBox()
        self.combo_action.addItems(
            ["Do nothing", "Exit CIDM", "Sleep Computer", "Shut down Computer"]
        )
        f_timing.addRow("On Queue Completion:", self.combo_action)

        layout.addWidget(gb_timing)

        # Dialog Buttons
        btn_box = QHBoxLayout()
        btn_box.setSpacing(8)
        btn_box.addStretch()
        btn_close = QPushButton("Cancel")
        btn_close.clicked.connect(self.reject)
        btn_box.addWidget(btn_close)

        btn_save = QPushButton("Save & Apply")
        btn_save.setObjectName("primaryBtn")
        btn_save.clicked.connect(self._save_and_apply)
        btn_box.addWidget(btn_save)
        layout.addLayout(btn_box)

        self._on_queue_selected(self.cb_queue.currentText())

    def _on_queue_selected(self, qname: str):
        cfg = self.queues_config.get(qname, {})
        self.spin_concur.setValue(cfg.get("max_concurrent", 3))

        st_str = cfg.get("start_time")
        if st_str:
            self.chk_start.setChecked(True)
            self.time_start.setTime(QTime.fromString(st_str, "HH:mm"))
        else:
            self.chk_start.setChecked(False)

        sp_str = cfg.get("stop_time")
        if sp_str:
            self.chk_stop.setChecked(True)
            self.time_stop.setTime(QTime.fromString(sp_str, "HH:mm"))
        else:
            self.chk_stop.setChecked(False)

        self.chk_daily.setChecked(bool(cfg.get("recurring", False)))

        action = cfg.get("on_complete", "Do nothing")
        idx = self.combo_action.findText(action)
        if idx >= 0:
            self.combo_action.setCurrentIndex(idx)

        self._populate_queue_items(qname)

    def _populate_queue_items(self, qname: str):
        self.table_items.setRowCount(0)
        qtasks = [
            t
            for t in self.tasks.values()
            if getattr(t, "queue_name", "Main Download Queue") == qname
        ]
        qtasks.sort(key=lambda t: getattr(t, "queue_order", 0))

        for idx, t in enumerate(qtasks):
            r = self.table_items.rowCount()
            self.table_items.insertRow(r)
            order_it = QTableWidgetItem(str(idx + 1))
            order_it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table_items.setItem(r, 0, order_it)
            item_name = QTableWidgetItem(t.filename or t.url)
            item_name.setData(Qt.ItemDataRole.UserRole, t.id)
            self.table_items.setItem(r, 1, item_name)
            st_it = QTableWidgetItem(t.status)
            st_it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table_items.setItem(r, 2, st_it)

    def _move_up(self):
        row = self.table_items.currentRow()
        if row <= 0:
            return
        self._swap_rows(row, row - 1)
        self.table_items.selectRow(row - 1)

    def _move_down(self):
        row = self.table_items.currentRow()
        if row < 0 or row >= self.table_items.rowCount() - 1:
            return
        self._swap_rows(row, row + 1)
        self.table_items.selectRow(row + 1)

    def _swap_rows(self, r1: int, r2: int):
        id1 = self.table_items.item(r1, 1).data(Qt.ItemDataRole.UserRole)
        id2 = self.table_items.item(r2, 1).data(Qt.ItemDataRole.UserRole)
        t1, t2 = self.tasks.get(id1), self.tasks.get(id2)
        if t1 and t2:
            o1, o2 = (
                getattr(t1, "queue_order", r1),
                getattr(t2, "queue_order", r2),
            )
            t1.queue_order = o2
            t2.queue_order = o1
        self._populate_queue_items(self.cb_queue.currentText())

    def _add_queue(self):
        text, ok = QInputDialog.getText(
            self, "New Queue", "Enter queue name:"
        )
        if ok and text.strip():
            qn = text.strip()
            if qn not in self.queues_config:
                self.queues_config[qn] = {
                    "max_concurrent": 2,
                    "start_time": None,
                    "stop_time": None,
                    "recurring": False,
                    "on_complete": "Do nothing",
                }
                self.cb_queue.addItem(qn)
                self.cb_queue.setCurrentText(qn)

    def _save_and_apply(self):
        qname = self.cb_queue.currentText()
        self.queues_config[qname] = {
            "max_concurrent": self.spin_concur.value(),
            "start_time": (
                self.time_start.time().toString("HH:mm")
                if self.chk_start.isChecked()
                else None
            ),
            "stop_time": (
                self.time_stop.time().toString("HH:mm")
                if self.chk_stop.isChecked()
                else None
            ),
            "recurring": self.chk_daily.isChecked(),
            "on_complete": self.combo_action.currentText(),
        }
        self.accept()


# --------------------------------------------------------------------------- #
# Site Grabber / Spider Dialog
# --------------------------------------------------------------------------- #
class GrabberThread(QThread):
    item_found = Signal(object)
    progress = Signal(int, int, str)
    finished_crawl = Signal(list)

    def __init__(self, grabber: SiteGrabber):
        super().__init__()
        self.grabber = grabber

    def run(self):
        self.grabber.on_item_found = lambda it: self.item_found.emit(it)
        self.grabber.on_progress = lambda p, q, u: self.progress.emit(p, q, u)
        res = self.grabber.crawl()
        self.finished_crawl.emit(res)


class SiteGrabberDialog(QDialog):
    def __init__(self, parent: QWidget, save_dir: str = "", threads: int = 8):
        super().__init__(parent)
        self.setWindowTitle("Site Grabber / Spider")
        self.resize(740, 520)
        self.setModal(True)
        self.save_dir = save_dir or default_download_dir()
        self.threads = threads
        self.discovered_items: List[GrabbedItem] = []
        self._thread: Optional[GrabberThread] = None
        self._grabber: Optional[SiteGrabber] = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(14, 14, 14, 14)

        # Config Form
        gb_cfg = QGroupBox("Crawler Settings")
        f_cfg = QFormLayout(gb_cfg)
        f_cfg.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        f_cfg.setSpacing(8)

        self.edit_start_url = QLineEdit()
        self.edit_start_url.setPlaceholderText(
            "https://example.com/gallery/ or page URL"
        )
        f_cfg.addRow("Start Page URL:", self.edit_start_url)

        opt_row = QHBoxLayout()
        opt_row.setSpacing(12)
        self.spin_depth = QSpinBox()
        self.spin_depth.setRange(1, 4)
        self.spin_depth.setValue(2)
        self.spin_depth.setFixedWidth(70)
        opt_row.addWidget(self.spin_depth)

        self.chk_same_domain = QCheckBox("Stay on same domain")
        self.chk_same_domain.setChecked(True)
        opt_row.addWidget(self.chk_same_domain)
        opt_row.addStretch()
        f_cfg.addRow("Crawl Depth:", opt_row)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(12)
        self.chk_img = QCheckBox("Images")
        self.chk_img.setChecked(True)
        self.chk_vid = QCheckBox("Videos")
        self.chk_vid.setChecked(True)
        self.chk_aud = QCheckBox("Audio")
        self.chk_doc = QCheckBox("Documents")
        self.chk_arc = QCheckBox("Archives")
        for cb in (
            self.chk_img,
            self.chk_vid,
            self.chk_aud,
            self.chk_doc,
            self.chk_arc,
        ):
            filter_row.addWidget(cb)
        filter_row.addStretch()
        f_cfg.addRow("File Presets:", filter_row)

        self.edit_custom_ext = QLineEdit()
        self.edit_custom_ext.setPlaceholderText(
            ".mkv, .pdf, .zip (optional custom extensions)"
        )
        f_cfg.addRow("Custom Ext:", self.edit_custom_ext)

        btn_row = QHBoxLayout()
        self.btn_crawl = QPushButton("Start Crawling")
        self.btn_crawl.setObjectName("primaryBtn")
        self.btn_crawl.clicked.connect(self._toggle_crawl)
        btn_row.addWidget(self.btn_crawl)
        btn_row.addStretch()
        f_cfg.addRow("", btn_row)

        layout.addWidget(gb_cfg)

        # Results area
        self.lbl_status = QLabel("Ready to crawl.")
        self.lbl_status.setStyleSheet("color: #9aa0aa; font-size: 12px;")
        layout.addWidget(self.lbl_status)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            ["", "File Name", "Category", "URL"]
        )
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Fixed
        )
        self.table.setColumnWidth(0, 38)
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Interactive
        )
        self.table.setColumnWidth(1, 190)
        self.table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Fixed
        )
        self.table.setColumnWidth(2, 95)
        self.table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch
        )
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(32)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        layout.addWidget(self.table)

        tbl_btns = QHBoxLayout()
        tbl_btns.setSpacing(8)
        btn_all = QPushButton("Select All")
        btn_all.clicked.connect(lambda: self._set_all_checked(True))
        btn_none = QPushButton("Deselect All")
        btn_none.clicked.connect(lambda: self._set_all_checked(False))
        tbl_btns.addWidget(btn_all)
        tbl_btns.addWidget(btn_none)
        tbl_btns.addStretch()
        layout.addLayout(tbl_btns)

        # Bottom download controls
        b_form = QFormLayout()
        b_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        b_form.setSpacing(10)
        d_row = QHBoxLayout()
        d_row.setSpacing(8)
        self.edit_save_dir = QLineEdit(self.save_dir)
        btn_b = QPushButton("Browse...")
        btn_b.clicked.connect(self._browse_dir)
        d_row.addWidget(self.edit_save_dir, 1)
        d_row.addWidget(btn_b)
        b_form.addRow("Download Folder:", d_row)

        self.combo_queue = QComboBox()
        self.combo_queue.addItems(
            ["Main Download Queue", "Synchronization Queue"]
        )
        b_form.addRow("Queue:", self.combo_queue)
        layout.addLayout(b_form)

        btn_box = QHBoxLayout()
        btn_box.setSpacing(8)
        btn_box.addStretch()
        btn_cancel = QPushButton("Close")
        btn_cancel.clicked.connect(self.reject)
        btn_box.addWidget(btn_cancel)

        self.btn_download = QPushButton("Download Checked Files")
        self.btn_download.setObjectName("primaryBtn")
        self.btn_download.clicked.connect(self.accept)
        btn_box.addWidget(self.btn_download)
        layout.addLayout(btn_box)

    def _row_checkbox(self, row: int) -> Optional[QCheckBox]:
        w = self.table.cellWidget(row, 0)
        if isinstance(w, QCheckBox):
            return w
        if w is not None:
            return w.findChild(QCheckBox)
        return None

    def _browse_dir(self):
        d = QFileDialog.getExistingDirectory(
            self, "Select Save Directory", self.edit_save_dir.text()
        )
        if d:
            self.edit_save_dir.setText(d)

    def _set_all_checked(self, checked: bool):
        for r in range(self.table.rowCount()):
            cb = self._row_checkbox(r)
            if cb is not None:
                cb.setChecked(checked)

    def _toggle_crawl(self):
        if self._thread and self._thread.isRunning():
            if self._grabber:
                self._grabber.cancel()
            self.btn_crawl.setText("Start Crawling")
            self.lbl_status.setText("Crawl stopped by user.")
            return

        start_url = self.edit_start_url.text().strip()
        if not start_url.startswith(("http://", "https://")):
            QMessageBox.warning(
                self, "Invalid URL", "Please enter a valid http(s) URL."
            )
            return

        cats = set()
        if self.chk_img.isChecked():
            cats.add("images")
        if self.chk_vid.isChecked():
            cats.add("videos")
        if self.chk_aud.isChecked():
            cats.add("audio")
        if self.chk_doc.isChecked():
            cats.add("documents")
        if self.chk_arc.isChecked():
            cats.add("archives")

        custom_exts = set(
            re.findall(r"\.[a-zA-Z0-9]+", self.edit_custom_ext.text())
        )

        self.table.setRowCount(0)
        self.discovered_items = []
        self._grabber = SiteGrabber(
            start_url=start_url,
            max_depth=self.spin_depth.value(),
            stay_on_domain=self.chk_same_domain.isChecked(),
            categories=cats,
            custom_extensions=custom_exts,
        )

        self._thread = GrabberThread(self._grabber)
        self._thread.item_found.connect(self._on_item_found)
        self._thread.progress.connect(self._on_crawl_progress)
        self._thread.finished_crawl.connect(self._on_crawl_finished)
        self._thread.start()

        self.btn_crawl.setText("Stop Crawling")
        self.lbl_status.setText(f"Crawling starting from {start_url}...")

    def _on_item_found(self, item: GrabbedItem):
        self.discovered_items.append(item)
        r = self.table.rowCount()
        self.table.insertRow(r)

        cb = QCheckBox()
        cb.setChecked(True)
        self.table.setCellWidget(r, 0, _center_widget_in_cell(cb))
        self.table.setItem(r, 1, QTableWidgetItem(item.filename))
        cat_it = QTableWidgetItem(item.category)
        cat_it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setItem(r, 2, cat_it)
        self.table.setItem(r, 3, QTableWidgetItem(item.url))

    def _on_crawl_progress(self, pages: int, queue_len: int, current_url: str):
        self.lbl_status.setText(
            f"Crawled {pages} page(s), {queue_len} in queue. Found {len(self.discovered_items)} file(s)."
        )

    def _on_crawl_finished(self, items: List[GrabbedItem]):
        self.btn_crawl.setText("Start Crawling")
        self.lbl_status.setText(
            f"Crawl completed! Discovered {len(self.discovered_items)} matching files."
        )

    def get_selected_tasks_info(self) -> List[Dict[str, Any]]:
        save_dir = (
            self.edit_save_dir.text().strip() or default_download_dir()
        )
        queue_name = (
            self.combo_queue.currentText().strip() or "Main Download Queue"
        )
        results = []

        for r in range(self.table.rowCount()):
            cb = self._row_checkbox(r)
            if cb and cb.isChecked():
                fname = self.table.item(r, 1).text()
                url = self.table.item(r, 3).text()
                results.append({
                    "url": url,
                    "filename": fname,
                    "save_dir": save_dir,
                    "threads": self.threads,
                    "queue_name": queue_name,
                })
        return results


# --------------------------------------------------------------------------- #
# Floating Drop Target Widget
# --------------------------------------------------------------------------- #
class DropTargetWidget(QWidget):
    """Floating mini drop target (IDM style basket) that accepts dragged links."""

    def __init__(self, main_window: MainWindow):
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.FramelessWindowHint,
        )
        self.main_window = main_window
        self.setFixedSize(76, 76)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAcceptDrops(True)
        self._dragging = False
        self._drag_pos = QPoint()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        painter.setBrush(QBrush(QColor(32, 34, 38, 235)))
        painter.setPen(QPen(QColor("#4f86c6"), 2))
        painter.drawRoundedRect(3, 3, 70, 70, 16, 16)

        pen = QPen(
            QColor("#ffffff"),
            3,
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
            Qt.PenJoinStyle.RoundJoin,
        )
        painter.setPen(pen)
        painter.drawLine(38, 20, 38, 46)
        painter.drawLine(27, 36, 38, 47)
        painter.drawLine(49, 36, 38, 47)
        painter.drawLine(24, 56, 52, 56)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._drag_pos = (
                event.globalPosition().toPoint()
                - self.frameGeometry().topLeft()
            )
            event.accept()

    def mouseMoveEvent(self, event):
        if self._dragging and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._dragging = False

    def mouseDoubleClickEvent(self, event):
        self.main_window.show_and_activate()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() or event.mimeData().hasText():
            event.acceptProposedAction()

    def dropEvent(self, event):
        event.acceptProposedAction()
        self.main_window.handle_dropped_content(event.mimeData())


# --------------------------------------------------------------------------- #
# Main window
# --------------------------------------------------------------------------- #
class SpeedLimitPopup(QFrame):
    """qBittorrent-style popup popover for toggling and adjusting the global speed limit."""

    applied = Signal(bool, int)

    def __init__(self, parent: QWidget, enabled: bool, limit_kbps: int):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("speedLimitPopup")
        self.setFixedWidth(250)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(10)

        title = QLabel("Global Download Speed Limit")
        title.setStyleSheet("font-weight: 600; font-size: 12px;")
        lay.addWidget(title)

        self.cb_enable = QCheckBox("Enable speed limit")
        self.cb_enable.setChecked(enabled)
        lay.addWidget(self.cb_enable)

        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(QLabel("Rate:"))
        self.spin_kbps = QSpinBox()
        self.spin_kbps.setRange(50, 1000000)
        self.spin_kbps.setSingleStep(128)
        self.spin_kbps.setSuffix(" KB/s")
        self.spin_kbps.setValue(max(50, int(limit_kbps)))
        self.spin_kbps.setEnabled(enabled)
        row.addWidget(self.spin_kbps, 1)
        lay.addLayout(row)

        self.cb_enable.toggled.connect(self.spin_kbps.setEnabled)

        # Quick presets row
        presets_row = QHBoxLayout()
        presets_row.setSpacing(4)
        for label, val in [("512K", 512), ("1M", 1024), ("2M", 2048), ("5M", 5120)]:
            b = QPushButton(label)
            b.setStyleSheet("padding: 3px 6px; font-size: 11px;")
            b.clicked.connect(lambda _c=False, v=val: self._pick_preset(v))
            presets_row.addWidget(b)
        lay.addLayout(presets_row)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_apply = QPushButton("Apply")
        btn_apply.setObjectName("primaryBtn")
        btn_apply.clicked.connect(self._on_apply)
        btn_row.addWidget(btn_apply)
        lay.addLayout(btn_row)

    def _pick_preset(self, kbps: int):
        self.cb_enable.setChecked(True)
        self.spin_kbps.setValue(kbps)

    def _on_apply(self):
        self.applied.emit(self.cb_enable.isChecked(), self.spin_kbps.value())
        self.close()


class MainWindow(QMainWindow):
    COLUMNS = [
        "File Name",
        "Size",
        "Status",
        "Progress",
        "Speed",
        "Time Left",
    ]

    def __init__(self):
        super().__init__()
        self.setWindowTitle("CIDM — Internet Download Manager")
        self.resize(1100, 640)
        self.settings = QSettings("CIDM", "CIDM")
        self.app_settings = load_settings()
        self.minimize_to_tray = bool(
            self.app_settings.get("minimize_to_tray", True)
        )
        self.max_concurrent_downloads = int(
            self.app_settings.get("max_concurrent_downloads", 3)
        )
        self._current_category = "all"
        self._completed_notified_ids = set()
        self.current_theme = self.app_settings.get("theme", "Dark Grey")
        self._is_quitting = False
        self._has_shown_tray_notice = False
        self.app_icon = create_app_icon()
        self.setWindowIcon(self.app_icon)
        self._apply_windows_taskbar_icon()

        self.tasks: Dict[int, DownloadTask] = {}
        self._pending_requests: List[dict] = []
        self._dialog_active = False

        self.queues_config = dict(
            self.app_settings.get(
                "queues_config",
                {
                    "Main Download Queue": {
                        "max_concurrent": 3,
                        "start_time": None,
                        "stop_time": None,
                        "recurring": False,
                        "on_complete": "Do nothing",
                    },
                    "Synchronization Queue": {
                        "max_concurrent": 1,
                        "start_time": None,
                        "stop_time": None,
                        "recurring": False,
                        "on_complete": "Do nothing",
                    },
                },
            )
        )
        self._completed_queue_triggered = set()
        self._last_checked_minute = ""
        self._triggered_schedule_events = set()
        self._search_query = ""
        self.drop_target_widget = DropTargetWidget(self)
        self.setAcceptDrops(True)

        self._toolbar_actions: List[tuple[QAction, str]] = []
        self._build_toolbar()
        self._build_central()
        self._build_statusbar()
        self._setup_tray()
        self._setup_clipboard_monitor()
        self._load_queue()
        self.apply_theme(self.current_theme)

        self.timer = QTimer(self)
        self.timer.setInterval(300)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()

        # First-run browser extension onboarding
        if not self.app_settings.get("extension_installed_prompt_shown", False):
            QTimer.singleShot(750, self._check_first_run_extension)

# ----- theme management ------------------------------------------------- #
    def apply_theme(self, theme_name: str):
        self.current_theme = theme_name
        self.app_settings["theme"] = theme_name
        is_light = theme_name.lower().startswith("light")
        qss = LIGHT_QSS if is_light else DARK_GREY_QSS
        app = QApplication.instance()
        if app:
            app.setStyleSheet(qss)
        else:
            self.setStyleSheet(qss)

        icon_color = "#374151" if is_light else "#e6e8ec"
        for action, icon_kind in self._toolbar_actions:
            color = "#ffffff" if icon_kind == "add" else icon_color
            action.setIcon(make_vector_icon(icon_kind, color, 16))

        if hasattr(self, "sidebar"):
            sidebar_color = "#4b5563" if is_light else "#9aa0aa"
            for i in range(self.sidebar.count()):
                it = self.sidebar.item(i)
                ik = it.data(Qt.ItemDataRole.UserRole + 1)
                if ik:
                    it.setIcon(make_vector_icon(ik, sidebar_color, 14))

        if hasattr(self, "btn_sidebar_settings"):
            self.btn_sidebar_settings.setIcon(
                make_vector_icon("settings", icon_color, 15)
            )

        self.refresh()

    # ----- construction ----------------------------------------------------- #
    def _build_toolbar(self):
        tb = QToolBar("Main")
        tb.setMovable(False)
        tb.setIconSize(QSize(16, 16))
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)

        def act(text: str, icon_kind: str, slot, icon_only: bool = False):
            a = QAction(
                make_vector_icon(icon_kind, "#e6e8ec", 16), text, self
            )
            a.triggered.connect(slot)
            self._toolbar_actions.append((a, icon_kind))
            if icon_only:
                btn = QToolButton()
                btn.setDefaultAction(a)
                btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
                btn.setToolTip(text)
                tb.addWidget(btn)
            else:
                tb.addAction(a)
            return a

        self.act_toggle_sidebar = act(
            "Toggle Sidebar", "menu", self.toggle_sidebar, icon_only=True
        )
        tb.addSeparator()

        self.act_add = QAction(
            make_vector_icon("add", "#ffffff", 16), "Add URL", self
        )
        self.act_add.setToolTip("Add new download URL (Ctrl+N)")
        self.act_add.setShortcut(QKeySequence("Ctrl+N"))
        self.act_add.triggered.connect(lambda: self.add_url())
        self._toolbar_actions.append((self.act_add, "add"))

        btn_add = QToolButton()
        btn_add.setObjectName("primaryAddBtn")
        btn_add.setDefaultAction(self.act_add)
        btn_add.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        tb.addWidget(btn_add)

        tb.addSeparator()
        self.act_resume = act("Resume", "resume", self.resume_selected)
        self.act_pause = act("Pause", "pause", self.pause_selected)
        self.act_pause_all = act("Pause All", "pause_all", self.pause_all)
        self.act_delete = act("Delete", "delete", self.delete_selected)

        tb.addSeparator()
        self.act_batch = act(
            "Batch", "batch", lambda: self.open_batch_download()
        )
        self.act_grabber = act(
            "Grabber", "grabber", self.open_site_grabber
        )
        self.act_scheduler = act(
            "Scheduler", "scheduler", self.open_scheduler
        )
        self.act_drop_target = act(
            "Drop Target", "drop_target", self.toggle_drop_target
        )

        tb.addSeparator()

        self.search_edit = QLineEdit()
        self.search_edit.setObjectName("navSearchEdit")
        self.search_edit.setPlaceholderText("Search...")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setFixedWidth(150)
        self.search_edit.textChanged.connect(self._on_search_text_changed)
        tb.addWidget(self.search_edit)

        self.addToolBar(tb)

    def _build_central(self):
        # Collapsible Sidebar Container (Categories + Pinned Settings at bottom)
        self.sidebar_container = QWidget()
        self.sidebar_container.setFixedWidth(165)
        sb_lay = QVBoxLayout(self.sidebar_container)
        sb_lay.setContentsMargins(0, 0, 0, 0)
        sb_lay.setSpacing(6)

        self.sidebar = QListWidget()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setIconSize(QSize(14, 14))

        categories = [
            ("All Downloads", "all", "all"),
            ("Downloading", "downloading", "downloading"),
            ("Completed", "completed", "completed"),
            ("Videos", "videos", "videos"),
            ("Compressed", "compressed", "compressed"),
            ("Programs", "programs", "programs"),
            ("Documents", "documents", "documents"),
            ("", "sep", ""),
            ("Main Queue", "queue:Main Download Queue", "queue"),
            ("Sync Queue", "queue:Synchronization Queue", "queue"),
        ]

        for text, key, icon_kind in categories:
            if key == "sep":
                sep_item = QListWidgetItem()
                sep_item.setData(Qt.ItemDataRole.UserRole, "sep")
                sep_item.setFlags(Qt.ItemFlag.NoItemFlags)
                sep_item.setSizeHint(QSize(0, 8))
                self.sidebar.addItem(sep_item)
                line = QFrame()
                line.setFrameShape(QFrame.Shape.HLine)
                line.setStyleSheet(
                    "color: #33373e; background-color: #33373e; max-height: 1px; margin: 3px 6px;"
                )
                self.sidebar.setItemWidget(sep_item, line)
                continue

            item = QListWidgetItem(
                make_vector_icon(icon_kind, "#9aa0aa", 14), text
            )
            item.setData(Qt.ItemDataRole.UserRole, key)
            item.setData(Qt.ItemDataRole.UserRole + 1, icon_kind)
            self.sidebar.addItem(item)

        self.sidebar.setCurrentRow(0)
        self.sidebar.currentItemChanged.connect(self._on_category_changed)
        sb_lay.addWidget(self.sidebar, 1)

       # Threads / Connections control in sidebar
        threads_pill = QWidget()
        threads_pill.setObjectName("threadsPill")
        pill_lay = QHBoxLayout(threads_pill)
        pill_lay.setContentsMargins(10, 5, 8, 5)
        pill_lay.setSpacing(6)

        lbl_conns = QLabel("Threads:")
        lbl_conns.setStyleSheet(
            "font-size: 12px; font-weight: 500; color: #9aa0aa;")
        pill_lay.addWidget(lbl_conns)
        pill_lay.addStretch(1)

        self.thread_spin = QSpinBox()
        self.thread_spin.setObjectName("threadSpin")
        self.thread_spin.setRange(1, 32)
        self.thread_spin.setValue(int(self.app_settings.get("threads", 8)))
        self.thread_spin.setFixedWidth(64)
        self.thread_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thread_spin.setToolTip(
            "Connections per download (1-32).\n"
            "Used for new downloads, and for a selected download that has not started yet."
        )
        self.thread_spin.valueChanged.connect(self._threads_changed)
        pill_lay.addWidget(self.thread_spin)
        sb_lay.addWidget(threads_pill)

        # Settings button pinned at bottom of sidebar
        self.btn_sidebar_settings = QPushButton("Settings")
        self.btn_sidebar_settings.setIcon(
            make_vector_icon("settings", "#e6e8ec", 15)
        )
        self.btn_sidebar_settings.setIconSize(QSize(15, 15))
        self.btn_sidebar_settings.setStyleSheet(
            "text-align: left; padding: 7px 12px; font-weight: 600;"
        )
        self.btn_sidebar_settings.clicked.connect(self.open_settings)
        sb_lay.addWidget(self.btn_sidebar_settings)

        # Right pane: download table + empty state overlay + segment panel
        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(32)

        header = self.table.horizontalHeader()
        header.setDefaultAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        col_specs = [
            (1, 90, Qt.AlignmentFlag.AlignRight),
            (2, 105, Qt.AlignmentFlag.AlignCenter),
            (3, 195, Qt.AlignmentFlag.AlignCenter),
            (4, 95, Qt.AlignmentFlag.AlignRight),
            (5, 90, Qt.AlignmentFlag.AlignRight),
        ]
        for col, width, align in col_specs:
            header.setSectionResizeMode(
                col, QHeaderView.ResizeMode.Interactive
            )
            self.table.setColumnWidth(col, width)
            hdr_it = self.table.horizontalHeaderItem(col)
            if hdr_it:
                hdr_it.setTextAlignment(align | Qt.AlignmentFlag.AlignVCenter)

        self.table.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.table.customContextMenuRequested.connect(self._context_menu)
        self.table.itemSelectionChanged.connect(self.refresh)
        self.table.cellDoubleClicked.connect(self._on_cell_double_clicked)

        # Subtle centered empty-state hint inside the table
        self.empty_label = QLabel(
            "No downloads in this view\nClick  + Add URL  or drag & drop links anywhere here",
            self.table.viewport(),
        )
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setStyleSheet(
            "color: #6b7280; font-size: 13px; background: transparent; line-height: 1.5;"
        )
        self.empty_label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )

        self.panel = SegmentPanel()
        self.panel.setMinimumHeight(130)

        right_splitter = QSplitter(Qt.Orientation.Vertical)
        right_splitter.setHandleWidth(6)
        right_splitter.addWidget(self.table)
        right_splitter.addWidget(self.panel)
        right_splitter.setStretchFactor(0, 4)
        right_splitter.setStretchFactor(1, 1)
        right_splitter.setChildrenCollapsible(False)

        wrapper = QWidget()
        wrapper.setObjectName("centralWrapper")
        lay = QHBoxLayout(wrapper)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(6)
        lay.addWidget(self.sidebar_container)
        lay.addWidget(right_splitter, 1)
        self.setCentralWidget(wrapper)

    def toggle_sidebar(self):
        if hasattr(self, "sidebar_container"):
            self.sidebar_container.setVisible(
                not self.sidebar_container.isVisible()
            )
            self._reposition_empty_label()

    def _build_statusbar(self):
        sb = QStatusBar(self)
        self.lbl_sb_summary = QLabel("Ready  ·  0 downloads")
        self.lbl_sb_speed = QLabel("Total Speed: 0 KB/s")
        self.lbl_sb_bridge = QLabel("Bridge: 127.0.0.1:9632")

        self.btn_speed_limiter = QPushButton("Limit: OFF")
        self.btn_speed_limiter.setObjectName("speedLimiterBtn")
        self.btn_speed_limiter.setToolTip(
            "Click to configure global download speed limit"
        )
        is_sp_on = bool(self.app_settings.get("speed_limit_enabled", False))
        self._update_speed_limiter_btn_text(is_sp_on)
        self.btn_speed_limiter.clicked.connect(self._open_speed_limit_popup)

        self.cb_tray = QCheckBox("Keep in background")
        self.cb_tray.setChecked(self.minimize_to_tray)
        self.cb_tray.setToolTip(
            "When checked, closing the window keeps CIDM running in the system tray."
        )
        self.cb_tray.toggled.connect(self._on_tray_toggled)

        sb.addWidget(self.lbl_sb_summary, 1)
        sb.addPermanentWidget(self.cb_tray)
        sb.addPermanentWidget(QLabel("  |  "))
        sb.addPermanentWidget(self.btn_speed_limiter)
        sb.addPermanentWidget(QLabel("  |  "))
        sb.addPermanentWidget(self.lbl_sb_speed)
        sb.addPermanentWidget(QLabel("  |  "))
        sb.addPermanentWidget(self.lbl_sb_bridge)
        self.setStatusBar(sb)

    def _open_speed_limit_popup(self):
        enabled = bool(self.app_settings.get("speed_limit_enabled", False))
        kbps = int(self.app_settings.get("speed_limit_kbps", 1024))
        popup = SpeedLimitPopup(self, enabled=enabled, limit_kbps=kbps)
        popup.applied.connect(self._on_speed_limit_applied)

        # Position popover directly above the status bar button
        btn_global = self.btn_speed_limiter.mapToGlobal(QPoint(0, 0))
        popup.adjustSize()
        x = max(8, btn_global.x() +
                self.btn_speed_limiter.width() - popup.width())
        y = max(8, btn_global.y() - popup.height() - 6)
        popup.move(x, y)
        popup.show()

    def _on_speed_limit_applied(self, enabled: bool, kbps: int):
        self.app_settings["speed_limit_enabled"] = enabled
        self.app_settings["speed_limit_kbps"] = kbps
        save_settings(self.app_settings)
        apply_engine_settings(self.app_settings)
        self._update_speed_limiter_btn_text(enabled)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reposition_empty_label()

    def _reposition_empty_label(self):
        if hasattr(self, "empty_label") and hasattr(self, "table"):
            vp = self.table.viewport()
            self.empty_label.setGeometry(0, 0, vp.width(), vp.height())

    # ----- category filtering ----------------------------------------------- #
    def _on_search_text_changed(self, text: str):
        self._search_query = text.strip().lower()
        self._apply_category_filter()

    def _on_category_changed(
        self,
        current: Optional[QListWidgetItem],
        previous: Optional[QListWidgetItem] = None,
    ):
        if current:
            self._current_category = current.data(Qt.ItemDataRole.UserRole)
        else:
            self._current_category = "all"
        self._apply_category_filter()

    def _apply_category_filter(self):
        cat = getattr(self, "_current_category", "all")
        query = getattr(self, "_search_query", "").strip().lower()
        visible_count = 0
        for r in range(self.table.rowCount()):
            it = self.table.item(r, 0)
            if it is None:
                continue
            tid = it.data(Qt.ItemDataRole.UserRole)
            task = self.tasks.get(tid)
            if task is None:
                continue
            visible = True
            if cat == "all":
                visible = True
            elif cat == "downloading":
                visible = task.status in (
                    Status.DOWNLOADING,
                    Status.PROBING,
                    Status.MERGING,
                    Status.EMBEDDING_SUBS,
                    Status.QUEUED,
                )
            elif cat == "completed":
                visible = task.status == Status.COMPLETED
            elif cat.startswith("queue:"):
                target_q = cat.split(":", 1)[1]
                visible = (
                    getattr(task, "queue_name", "Main Download Queue")
                    == target_q
                )
            elif cat in ("videos", "compressed", "programs", "documents"):
                cname = cat.capitalize()
                file_cat = get_category_for_filename(
                    task.filename or task.url
                )
                if cat == "videos" and (
                    isinstance(task, MediaDownloadTask) or file_cat == "Videos"
                ):
                    visible = True
                else:
                    visible = file_cat == cname

            if visible and query:
                fname = (task.filename or "").lower()
                url = (task.url or "").lower()
                if query not in fname and query not in url:
                    visible = False

            self.table.setRowHidden(r, not visible)
            if visible:
                visible_count += 1

        if hasattr(self, "empty_label"):
            self._reposition_empty_label()
            self.empty_label.setVisible(visible_count == 0)

    # ----- queue scheduling ------------------------------------------------- #
    def _schedule_queue(self):
        for qname, qcfg in self.queues_config.items():
            max_active = int(qcfg.get("max_concurrent", 3))
            qtasks = [
                t
                for t in self.tasks.values()
                if getattr(t, "queue_name", "Main Download Queue") == qname
            ]
            qtasks.sort(key=lambda t: getattr(t, "queue_order", 0))

            active_count = sum(
                1
                for t in qtasks
                if t.status
                in (
                    Status.DOWNLOADING,
                    Status.PROBING,
                    Status.MERGING,
                    Status.EMBEDDING_SUBS,
                )
            )
            slots = max_active - active_count
            if slots <= 0:
                continue
            for t in qtasks:
                if slots <= 0:
                    break
                if t.status == Status.QUEUED:
                    t.start()
                    slots -= 1

    # ----- helpers ---------------------------------------------------------- #
    def _row_for(self, tid: int) -> int:
        for r in range(self.table.rowCount()):
            it = self.table.item(r, 0)
            if it is not None and it.data(Qt.ItemDataRole.UserRole) == tid:
                return r
        return -1

    def _selected_tasks(self) -> List[DownloadTask]:
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        out = []
        for r in rows:
            it = self.table.item(r, 0)
            if it is not None:
                t = self.tasks.get(it.data(Qt.ItemDataRole.UserRole))
                if t is not None:
                    out.append(t)
        return out

    def _make_bar(self) -> QProgressBar:
        bar = QProgressBar()
        bar.setRange(0, 1000)
        bar.setValue(0)
        bar.setFormat("0.0%")
        return bar

    def _add_task_row(self, task: DownloadTask):
        self.tasks[task.id] = task
        row = self.table.rowCount()
        self.table.insertRow(row)
        name = QTableWidgetItem(
            task.filename or filename_from_url(task.url) or task.url
        )
        name.setData(Qt.ItemDataRole.UserRole, task.id)
        name.setToolTip(task.url)
        self.table.setItem(row, 0, name)

        col_alignments = {
            1: Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            2: Qt.AlignmentFlag.AlignCenter,
            4: Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            5: Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        }
        for col, align in col_alignments.items():
            it = QTableWidgetItem("")
            it.setTextAlignment(align)
            self.table.setItem(row, col, it)

        wrap = QWidget()
        wl = QHBoxLayout(wrap)
        wl.setContentsMargins(6, 0, 6, 0)
        wl.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        wl.addWidget(self._make_bar())
        self.table.setCellWidget(row, 3, wrap)
        self.table.setRowHeight(row, 32)
        self._apply_category_filter()

    def _remove_task_row(self, tid: int):
        r = self._row_for(tid)
        self.tasks.pop(tid, None)
        if r >= 0:
            self.table.removeRow(r)
        self._apply_category_filter()

    @staticmethod
    def _set_text(item: Optional[QTableWidgetItem], text: str):
        if item is not None and item.text() != text:
            item.setText(text)

    # ----- periodic refresh ------------------------------------------------- #
    def refresh(self):
        is_light = self.current_theme.lower().startswith("light")
        badge_colors = {
            Status.COMPLETED: "#16a34a" if is_light else "#4ea876",
            Status.DOWNLOADING: "#2563eb" if is_light else "#4f86c6",
            Status.MERGING: "#0284c7" if is_light else "#5f96d6",
            Status.EMBEDDING_SUBS: "#0284c7" if is_light else "#4f86c6",
            Status.PAUSED: "#d97706" if is_light else "#c99a45",
            Status.PAUSING: "#d97706" if is_light else "#c99a45",
            Status.ERROR: "#dc2626" if is_light else "#cf5c5c",
            Status.QUEUED: "#6b7280" if is_light else "#9aa0aa",
        }

        notify = bool(self.app_settings.get("notify_on_complete", True))
        total_speed = 0.0
        active_downloads = 0

        for tid, task in list(self.tasks.items()):
            row = self._row_for(tid)
            if row < 0 or self.table.cellWidget(row, 3) is None:
                continue
            s = task.snapshot()
            status = s["status"]

            if status in Status.ACTIVE:
                active_downloads += 1
            if status == Status.DOWNLOADING:
                total_speed += float(s.get("speed") or 0.0)

            # Completion notification
            if status == Status.COMPLETED:
                if tid not in self._completed_notified_ids:
                    self._completed_notified_ids.add(tid)
                    if (
                        notify
                        and hasattr(self, "tray_icon")
                        and self.tray_icon.isVisible()
                    ):
                        name = task.filename or "Download"
                        self.tray_icon.showMessage(
                            "Download Complete",
                            f"{name} has finished downloading.",
                            QSystemTrayIcon.MessageIcon.Information,
                            4000,
                        )

            self._set_text(
                self.table.item(row, 0),
                s["filename"] or filename_from_url(s["url"]) or s["url"],
            )
            size_txt = format_size(s["file_size"]) if s["file_size"] else "-"
            if (
                s.get("unit") == "segments"
                and s["file_size"]
                and status != Status.COMPLETED
            ):
                size_txt = "~" + size_txt
            self._set_text(self.table.item(row, 1), size_txt)

            status_item = self.table.item(row, 2)
            self._set_text(status_item, status)
            status_item.setToolTip(
                s["error"] if status == Status.ERROR else ""
            )
            color_hex = badge_colors.get(
                status, "#1f2937" if is_light else "#e6e8ec"
            )
            status_item.setForeground(QBrush(QColor(color_hex)))

            downloading = status == Status.DOWNLOADING
            self._set_text(
                self.table.item(row, 4), s["speed_str"] if downloading else ""
            )
            self._set_text(
                self.table.item(row, 5), s["eta_str"] if downloading else ""
            )

            bar: QProgressBar = self.table.cellWidget(row, 3).findChild(
                QProgressBar
            )
            if downloading and s["file_size"] <= 0:
                bar.setRange(0, 0)
            else:
                if bar.maximum() == 0:
                    bar.setRange(0, 1000)
                bar.setValue(int(s["percent"] * 10))
                bar.setFormat(f"{s['percent']:.1f}%")
            state = {
                Status.COMPLETED: "done",
                Status.ERROR: "error",
                Status.PAUSED: "paused",
                Status.PAUSING: "paused",
            }.get(status, "")
            if bar.property("state") != state:
                bar.setProperty("state", state)
                bar.style().unpolish(bar)
                bar.style().polish(bar)

        if hasattr(self, "lbl_sb_summary"):
            total_tasks = len(self.tasks)
            self.lbl_sb_summary.setText(
                f"{total_tasks} download(s)  ·  {active_downloads} active"
            )
            self.lbl_sb_speed.setText(
                f"Total Speed: {format_speed(total_speed)}"
            )

        sel = self._selected_tasks()
        has_sel = len(sel) > 0
        has_running_sel = any(
            t.status
            in (
                Status.DOWNLOADING,
                Status.PROBING,
                Status.MERGING,
                Status.EMBEDDING_SUBS,
                Status.PAUSING,
            )
            for t in sel
        )
        has_paused_sel = any(
            t.status
            in (Status.PAUSED, Status.QUEUED, Status.ERROR, Status.PAUSING)
            for t in sel
        )
        if hasattr(self, "act_resume"):
            self.act_resume.setEnabled(has_paused_sel)
        if hasattr(self, "act_pause"):
            self.act_pause.setEnabled(has_running_sel)
        if hasattr(self, "act_delete"):
            self.act_delete.setEnabled(has_sel)
        if hasattr(self, "act_pause_all"):
            self.act_pause_all.setEnabled(active_downloads > 0)

        self._apply_category_filter()
        self._schedule_queue()
        self._check_scheduled_queues()
        self.panel.show_snapshot(sel[0].snapshot() if sel else None)

    # ----- actions ---------------------------------------------------------- #
    @property
    def save_dir(self) -> str:
        return str(
            self.app_settings.get("save_dir") or default_download_dir()
        )

    def _threads_changed(self, value: int):
        self.settings.setValue("threads", value)
        self.app_settings["threads"] = value
        save_settings(self.app_settings)
        for t in self._selected_tasks():
            if t.status == Status.QUEUED:
                t.set_threads(value)

    def open_settings(self):
        dlg = SettingsDialog(self, self.app_settings)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.apply_settings(dlg.values())
        dlg.deleteLater()

    def _check_first_run_extension(self):
        if self._is_quitting:
            return
        sync_extension_files()
        dlg = FirstRunExtensionDialog(self)
        dlg.exec()
        self.app_settings["extension_installed_prompt_shown"] = True
        save_settings(self.app_settings)

    def open_extension_setup(self):
        sync_extension_files()
        dlg = FirstRunExtensionDialog(self)
        dlg.exec()
        self.app_settings["extension_installed_prompt_shown"] = True
        save_settings(self.app_settings)

    def apply_settings(self, settings: dict):
        self.app_settings.update(settings)
        save_settings(self.app_settings)
        apply_engine_settings(self.app_settings)
        self.apply_theme(self.app_settings.get("theme", "Dark Grey"))
        self.minimize_to_tray = bool(
            self.app_settings.get("minimize_to_tray", True)
        )
        self.cb_tray.setChecked(self.minimize_to_tray)
        self.thread_spin.setValue(int(self.app_settings.get("threads", 8)))
        self._update_speed_limiter_btn_text(
            bool(self.app_settings.get("speed_limit_enabled", False))
        )
        self._schedule_queue()
        self._apply_category_filter()

    def get_enabled_ips(self) -> List[str]:
        enabled = self.app_settings.get("enabled_interfaces") or []
        ifaces = get_active_interfaces()
        if not enabled:
            return [i["ip"] for i in ifaces]
        return [
            i["ip"]
            for i in ifaces
            if i["name"] in enabled or i["ip"] in enabled
        ]

    def add_url(self, prefill: Optional[dict] = None):
        p = prefill or {}
        dlg = AddDownloadDialog(
            self,
            url=p.get("url", ""),
            filename=p.get("filename", ""),
            cookies=p.get("cookies", ""),
            user_agent=p.get("user_agent", ""),
            referer=p.get("referer", ""),
            origin=p.get("origin", ""),
            stream_type=p.get("stream_type", ""),
            save_dir=self.save_dir,
            threads=self.thread_spin.value(),
            on_top=bool(prefill),
            kind=p.get("kind", ""),
            subtitles=p.get("subtitles") or [],
            settings=self.app_settings,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.start_download(dlg.values())
        dlg.deleteLater()

    def start_download(self, v: dict):
        save_dir = v["save_dir"]
        filename = v["filename"] or None
        self.settings.setValue("save_dir", save_dir)
        self.app_settings["save_dir"] = save_dir
        save_settings(self.app_settings)
        if self.thread_spin.value() != v["threads"]:
            self.thread_spin.setValue(v["threads"])

        conflict_action = str(
            self.app_settings.get("file_conflict", "Auto-rename")
        )
        auto_categorize = bool(self.app_settings.get("auto_categorize", True))

        if filename:
            if auto_categorize:
                save_dir = resolve_destination_folder(
                    save_dir, filename, auto_categorize=True
                )
            target_path = os.path.join(save_dir, filename)
            if os.path.exists(target_path):
                if conflict_action.lower().startswith("ask"):
                    box = QMessageBox(self)
                    box.setIcon(QMessageBox.Icon.Question)
                    box.setWindowTitle("File Exists")
                    box.setText(
                        f"'{filename}' already exists in the destination folder."
                    )
                    btn_rename = box.addButton(
                        "Auto-rename", QMessageBox.ButtonRole.ActionRole
                    )
                    btn_overwrite = box.addButton(
                        "Overwrite", QMessageBox.ButtonRole.ActionRole
                    )
                    box.addButton(QMessageBox.StandardButton.Cancel)
                    box.setDefaultButton(btn_rename)
                    box.exec()
                    clicked = box.clickedButton()
                    if clicked == btn_rename:
                        conflict_action = "Auto-rename"
                    elif clicked == btn_overwrite:
                        conflict_action = "Overwrite"
                    else:
                        return

        task = create_task(
            url=v["url"],
            save_dir=save_dir,
            filename=filename,
            threads=v["threads"],
            cookies=v.get("cookies"),
            user_agent=v.get("user_agent"),
            referer=v.get("referer"),
            origin=v.get("origin"),
            kind=v.get("kind"),
            stream_type=v.get("stream_type"),
            format_id=v.get("format_id"),
            quality_label=v.get("quality_label"),
            media_title=v.get("media_title"),
            subtitle_track=v.get("subtitle_track"),
            subtitle_mode=v.get("subtitle_mode", "embed"),
            selected_ips=v.get("selected_ips"),
            proxy_pool=v.get(
                "proxy_pool", self.app_settings.get("proxy_pool", [])
            ),
            proxy_pool_enabled=v.get(
                "proxy_pool_enabled",
                self.app_settings.get("proxy_pool_enabled", False),
            ),
            proxy_pool_include_direct=v.get(
                "proxy_pool_include_direct",
                self.app_settings.get("proxy_pool_include_direct", True),
            ),
            auto_categorize=False,
            conflict_action=conflict_action,
        )
        self._add_task_row(task)
        self.table.clearSelection()
        self.table.selectRow(self.table.rowCount() - 1)

        max_active = int(
            self.app_settings.get("max_concurrent_downloads", 3)
        )
        active_count = sum(
            1
            for t in self.tasks.values()
            if t.status
            in (
                Status.DOWNLOADING,
                Status.PROBING,
                Status.MERGING,
                Status.EMBEDDING_SUBS,
            )
        )
        if active_count < max_active:
            task.start()
        else:
            task.status = Status.QUEUED

        self._save_queue()
        self._apply_category_filter()

    def resume_selected(self):
        for t in self._selected_tasks():
            if t.status in (
                Status.PAUSED,
                Status.QUEUED,
                Status.ERROR,
                Status.PAUSING,
            ):
                t.resume()
        self.refresh()

    def pause_selected(self):
        for t in self._selected_tasks():
            if t.status in (
                Status.DOWNLOADING,
                Status.PROBING,
                Status.QUEUED,
                Status.PAUSING,
            ):
                t.pause()
        self.refresh()

    def _on_cell_double_clicked(self, row: int, col: int):
        tasks = self._selected_tasks()
        if not tasks:
            return
        t = tasks[0]
        if t.status == Status.COMPLETED:
            self.open_selected_file()
        elif t.status in (Status.DOWNLOADING, Status.PROBING):
            t.pause()
            self.refresh()
        elif t.status in (
            Status.PAUSED,
            Status.QUEUED,
            Status.ERROR,
            Status.PAUSING,
        ):
            t.resume()
            self.refresh()

    def delete_selected(self):
        tasks = self._selected_tasks()
        if not tasks:
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Delete download")
        box.setText(f"Remove {len(tasks)} download(s) from the list?")
        box.setInformativeText(
            "Partial files of unfinished downloads are always removed."
        )
        cb = QCheckBox("Also delete finished file(s) from disk")
        box.setCheckBox(cb)
        box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        box.setDefaultButton(QMessageBox.StandardButton.No)
        if box.exec() != QMessageBox.StandardButton.Yes:
            return
        for t in tasks:
            if t.status == Status.COMPLETED:
                if cb.isChecked():
                    t.delete_files()
            else:
                t.cancel()
            self._remove_task_row(t.id)
        self._save_queue()
        self._schedule_queue()
        self.refresh()

    def open_selected_file(self):
        for t in self._selected_tasks():
            if t.status == Status.COMPLETED:
                p = t.path
                if not os.path.exists(p) and not os.path.splitext(p)[1]:
                    for ext in (".mp4", ".m4a", ".mkv", ".webm"):
                        if os.path.exists(p + ext):
                            p = p + ext
                            break
                if os.path.exists(p):
                    QDesktopServices.openUrl(QUrl.fromLocalFile(p))

    def open_selected_folder(self):
        tasks = self._selected_tasks()
        if not tasks:
            return
        task = tasks[0]
        p = task.path
        if not os.path.exists(p) and not os.path.splitext(p)[1]:
            for ext in (".mp4", ".m4a", ".mkv", ".webm"):
                if os.path.exists(p + ext):
                    p = p + ext
                    break
        if sys.platform == "win32" and os.path.exists(p):
            import subprocess
            subprocess.run(
                ["explorer.exe", f"/select,{os.path.abspath(p)}"], check=False
            )
        else:
            folder = (
                task.save_dir
                if os.path.isdir(task.save_dir)
                else default_download_dir()
            )
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def redownload_selected(self):
        tasks = self._selected_tasks()
        if not tasks:
            return
        for t in tasks:
            t.pause()
            t.delete_files()
            with t._lock:
                t.segments = []
                t.downloaded = 0
                setattr(t, "percent_from_hook", 0.0)
                t.error = ""
                t._file_created = False
                t.status = Status.QUEUED
            t.start()
        self.refresh()

    def _context_menu(self, pos):
        tasks = self._selected_tasks()
        if not tasks:
            return
        task = tasks[0]
        menu = QMenu(self)
        act_res = menu.addAction("Resume", self.resume_selected)
        act_pau = menu.addAction("Pause", self.pause_selected)
        act_res.setEnabled(
            task.status
            in (Status.PAUSED, Status.QUEUED, Status.ERROR, Status.PAUSING)
        )
        act_pau.setEnabled(
            task.status
            in (
                Status.DOWNLOADING,
                Status.PROBING,
                Status.MERGING,
                Status.EMBEDDING_SUBS,
                Status.PAUSING,
            )
        )
        menu.addAction("Redownload from start", self.redownload_selected)
        menu.addSeparator()
        menu.addAction(
            "Refresh Download Address",
            lambda: self.open_refresh_address(task),
        )
        menu.addAction(
            "Properties & Checksum", lambda: self.open_properties(task)
        )
        menu.addSeparator()
        m_q = menu.addMenu("Move to Queue")
        for qn in list(self.queues_config.keys()):
            m_q.addAction(
                qn, lambda q=qn: self._move_tasks_to_queue(tasks, q)
            )
        menu.addSeparator()
        menu.addAction("Open file", self.open_selected_file)
        menu.addAction("Open folder in Explorer", self.open_selected_folder)
        menu.addAction(
            "Copy URL", lambda: QApplication.clipboard().setText(task.url)
        )
        menu.addSeparator()
        menu.addAction("Delete", self.delete_selected)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    # ----- system tray integration ----------------------------------------- #
    def _setup_tray(self):
        self.tray_icon = QSystemTrayIcon(self.app_icon, self)
        self.tray_icon.setToolTip("CIDM — Internet Download Manager")

        tray_menu = QMenu()
        act_show = tray_menu.addAction("Show CIDM")
        act_show.triggered.connect(self.show_and_activate)
        tray_menu.addSeparator()

        act_pause_all = tray_menu.addAction("Pause All Downloads")
        act_pause_all.triggered.connect(self.pause_all)

        act_resume_all = tray_menu.addAction("Resume All Downloads")
        act_resume_all.triggered.connect(self.resume_all)
        tray_menu.addSeparator()

        act_quit = tray_menu.addAction("Quit CIDM")
        act_quit.triggered.connect(self.quit_app)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason):
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.show_and_activate()

    def _on_tray_toggled(self, checked: bool):
        self.minimize_to_tray = checked
        self.app_settings["minimize_to_tray"] = checked
        save_settings(self.app_settings)

    def show_and_activate(self):
        if self.isHidden():
            self.show()
        if self.isMinimized():
            self.setWindowState(
                (self.windowState() & ~Qt.WindowState.WindowMinimized)
                | Qt.WindowState.WindowActive
            )
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self._apply_windows_taskbar_icon()

    def showEvent(self, event):
        super().showEvent(event)
        self._apply_windows_taskbar_icon()

    def _apply_windows_taskbar_icon(self):
        if sys.platform != "win32":
            return
        try:
            import ctypes
            hwnd = int(self.winId())
            base_dir = getattr(
                sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))
            )
            for cand in (
                os.path.join(base_dir, "assets", "cidm.ico"),
                os.path.join(base_dir, "cidm.ico"),
                os.path.join(base_dir, "assets", "pyidm.ico"),
                os.path.join(base_dir, "pyidm.ico"),
            ):
                if os.path.exists(cand) and os.path.getsize(cand) > 0:
                    abs_path = os.path.abspath(cand)
                    IMAGE_ICON = 1
                    LR_LOADFROMFILE = 0x00000010
                    LR_SHARED = 0x00008000
                    h_small = ctypes.windll.user32.LoadImageW(
                        None,
                        abs_path,
                        IMAGE_ICON,
                        16,
                        16,
                        LR_LOADFROMFILE | LR_SHARED,
                    )
                    h_big = ctypes.windll.user32.LoadImageW(
                        None,
                        abs_path,
                        IMAGE_ICON,
                        32,
                        32,
                        LR_LOADFROMFILE | LR_SHARED,
                    )
                    WM_SETICON = 0x0080
                    ICON_SMALL = 0
                    ICON_BIG = 1
                    if h_big:
                        ctypes.windll.user32.SendMessageW(
                            hwnd, WM_SETICON, ICON_BIG, h_big
                        )
                    if h_small:
                        ctypes.windll.user32.SendMessageW(
                            hwnd, WM_SETICON, ICON_SMALL, h_small
                        )
                    break
        except Exception:
            pass

    def pause_all(self):
        for t in list(self.tasks.values()):
            t.pause()
        self.refresh()

    def resume_all(self):
        for t in list(self.tasks.values()):
            t.resume()
        self.refresh()

    def quit_app(self):
        self._is_quitting = True
        for t in list(self.tasks.values()):
            if t.is_active:
                t.pause()
        self._save_queue()
        save_settings(self.app_settings)
        deadline = time.monotonic() + 1.5
        for t in list(self.tasks.values()):
            rem = deadline - time.monotonic()
            if rem <= 0:
                break
            t.wait(timeout=max(0.05, rem))
        if hasattr(self, "tray_icon") and self.tray_icon:
            self.tray_icon.hide()
        QApplication.quit()
        os._exit(0)

    # ----- browser integration --------------------------------------------- #
    def bring_to_front(self):
        self.show_and_activate()
        QApplication.alert(self, 3000)

    def handle_intercepted_download(self, payload: dict):
        self._pending_requests.append(payload)
        self.bring_to_front()
        if not self._dialog_active:
            QTimer.singleShot(0, self._drain_pending)

    def _drain_pending(self):
        if self._dialog_active:
            return
        self._dialog_active = True
        try:
            while self._pending_requests:
                self.add_url(self._pending_requests.pop(0))
        finally:
            self._dialog_active = False

    # ----- persistence of the download list -------------------------------- #
    def _save_queue(self):
        items = [
            t.to_dict()
            for t in self.tasks.values()
            if t.status not in (Status.COMPLETED, Status.CANCELLED)
        ]
        try:
            os.makedirs(os.path.dirname(QUEUE_PATH), exist_ok=True)
            with open(QUEUE_PATH, "w", encoding="utf-8") as f:
                json.dump(items, f)
            try:
                os.chmod(QUEUE_PATH, 0o600)
            except OSError:
                pass
        except OSError:
            pass

    def _load_queue(self):
        try:
            with open(QUEUE_PATH, "r", encoding="utf-8") as f:
                items = json.load(f)
        except (OSError, ValueError):
            return
        for d in items if isinstance(items, list) else []:
            try:
                self._add_task_row(task_from_dict(d))
            except (KeyError, TypeError, ValueError):
                continue

    def closeEvent(self, event):
        if self._is_quitting or not self.minimize_to_tray:
            self.quit_app()
            event.accept()
        else:
            event.ignore()
            self.hide()
            if not self._has_shown_tray_notice:
                self._has_shown_tray_notice = True
                if (
                    hasattr(self, "tray_icon")
                    and self.tray_icon
                    and self.tray_icon.isVisible()
                ):
                    self.tray_icon.showMessage(
                        "CIDM",
                        "Running in the background to catch browser downloads.",
                        QSystemTrayIcon.MessageIcon.Information,
                        3000,
                    )

    # ----- Power-User Utilities & Features ---------------------------------- #
    def _toggle_speed_limiter(self, checked: bool):
        self.app_settings["speed_limit_enabled"] = checked
        save_settings(self.app_settings)
        apply_engine_settings(self.app_settings)
        self._update_speed_limiter_btn_text(checked)

    def _update_speed_limiter_btn_text(self, enabled: bool):
        kbps = int(self.app_settings.get("speed_limit_kbps", 1024))
        if enabled:
            self.btn_speed_limiter.setText(f"Limit: {kbps} KB/s")
        else:
            self.btn_speed_limiter.setText("Limit: OFF")
        self.btn_speed_limiter.setProperty("active", enabled)
        self.btn_speed_limiter.style().unpolish(self.btn_speed_limiter)
        self.btn_speed_limiter.style().polish(self.btn_speed_limiter)

    def toggle_drop_target(self):
        if self.drop_target_widget.isVisible():
            self.drop_target_widget.hide()
        else:
            self.drop_target_widget.show()
            self.drop_target_widget.raise_()

    def open_batch_download(
        self, prefill_urls: Optional[List[str]] = None, referer: str = ""
    ):
        dlg = BatchDownloadDialog(
            self,
            initial_urls=prefill_urls,
            referer=referer,
            save_dir=self.save_dir,
            threads=self.thread_spin.value(),
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            items = dlg.get_selected_tasks_info()
            ips = self.get_enabled_ips()
            for info in items:
                task = create_task(
                    url=info["url"],
                    save_dir=info["save_dir"],
                    filename=info["filename"],
                    threads=info["threads"],
                    referer=info.get("referer"),
                    queue_name=info.get(
                        "queue_name", "Main Download Queue"
                    ),
                    selected_ips=ips,
                    proxy_pool=self.app_settings.get("proxy_pool", []),
                    proxy_pool_enabled=bool(
                        self.app_settings.get("proxy_pool_enabled", False)
                    ),
                    proxy_pool_include_direct=bool(
                        self.app_settings.get(
                            "proxy_pool_include_direct", True
                        )
                    ),
                )
                self._add_task_row(task)
            self._save_queue()
            self._schedule_queue()
            self.refresh()
        dlg.deleteLater()

    def handle_batch_requested(self, payload: dict):
        urls = payload.get("urls") or []
        ref = payload.get("referer") or ""
        self.show_and_activate()
        self.open_batch_download(prefill_urls=urls, referer=ref)

    def open_site_grabber(self):
        dlg = SiteGrabberDialog(
            self, save_dir=self.save_dir, threads=self.thread_spin.value()
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            items = dlg.get_selected_tasks_info()
            ips = self.get_enabled_ips()
            for info in items:
                task = create_task(
                    url=info["url"],
                    save_dir=info["save_dir"],
                    filename=info["filename"],
                    threads=info["threads"],
                    queue_name=info.get(
                        "queue_name", "Main Download Queue"
                    ),
                    selected_ips=ips,
                    proxy_pool=self.app_settings.get("proxy_pool", []),
                    proxy_pool_enabled=bool(
                        self.app_settings.get("proxy_pool_enabled", False)
                    ),
                    proxy_pool_include_direct=bool(
                        self.app_settings.get(
                            "proxy_pool_include_direct", True
                        )
                    ),
                )
                self._add_task_row(task)
            self._save_queue()
            self._schedule_queue()
            self.refresh()
        dlg.deleteLater()

    def open_scheduler(self):
        dlg = SchedulerDialog(self, self.tasks, self.queues_config)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.queues_config = dlg.queues_config
            self.app_settings["queues_config"] = self.queues_config
            save_settings(self.app_settings)
            self._schedule_queue()
            self.refresh()
        dlg.deleteLater()

    def open_properties(self, task: DownloadTask):
        dlg = PropertiesDialog(self, task)
        dlg.exec()
        dlg.deleteLater()

    def open_refresh_address(self, task: DownloadTask):
        dlg = RefreshAddressDialog(self, task)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.refresh()
        dlg.deleteLater()

    def _move_tasks_to_queue(
        self, tasks: List[DownloadTask], queue_name: str
    ):
        for t in tasks:
            t.queue_name = queue_name
        self._save_queue()
        self._apply_category_filter()
        self.refresh()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() or event.mimeData().hasText():
            event.acceptProposedAction()

    def dropEvent(self, event):
        event.acceptProposedAction()
        self.handle_dropped_content(event.mimeData())

    def handle_dropped_content(self, mime_data):
        self.show_and_activate()
        urls = []
        if mime_data.hasUrls():
            for qurl in mime_data.urls():
                if qurl.isLocalFile():
                    lpath = qurl.toLocalFile()
                    if lpath.lower().endswith(".txt"):
                        try:
                            with open(
                                lpath,
                                "r",
                                encoding="utf-8",
                                errors="ignore",
                            ) as f:
                                for line in f.read().splitlines():
                                    u = line.strip()
                                    if u.startswith(("http://", "https://")):
                                        urls.append(u)
                        except Exception:
                            pass
                else:
                    u = qurl.toString().strip()
                    if u.startswith(("http://", "https://")):
                        urls.append(u)
        elif mime_data.hasText():
            for line in mime_data.text().splitlines():
                u = line.strip()
                if u.startswith(("http://", "https://")):
                    urls.append(u)

        if not urls:
            return

        if len(urls) == 1:
            self.add_url({"url": urls[0]})
        else:
            self.open_batch_download(prefill_urls=urls)

    def _setup_clipboard_monitor(self):
        cb = QApplication.clipboard()
        cb.dataChanged.connect(self._on_clipboard_changed)
        self._last_clipboard_url = ""

    def _on_clipboard_changed(self):
        if not bool(self.app_settings.get("clipboard_monitor", False)):
            return
        text = QApplication.clipboard().text().strip()
        if not text or text == getattr(self, "_last_clipboard_url", ""):
            return
        if not text.startswith(("http://", "https://")):
            return

        downloadable_exts = (
            ".zip",
            ".rar",
            ".7z",
            ".tar",
            ".gz",
            ".bz2",
            ".xz",
            ".iso",
            ".exe",
            ".msi",
            ".dmg",
            ".pkg",
            ".apk",
            ".pdf",
            ".mp4",
            ".mkv",
            ".webm",
            ".mp3",
            ".flac",
            ".m4a",
            ".doc",
            ".docx",
            ".epub",
        )
        clean_url = text.split("?")[0].lower()
        if (
            any(clean_url.endswith(ext) for ext in downloadable_exts)
            or is_media_url(text)
        ):
            self._last_clipboard_url = text
            self.add_url({"url": text})

    def _check_scheduled_queues(self):
        now_time = QTime.currentTime().toString("HH:mm")
        if getattr(self, "_last_checked_minute", "") != now_time:
            self._last_checked_minute = now_time
            if hasattr(self, "_triggered_schedule_events"):
                self._triggered_schedule_events.clear()
            else:
                self._triggered_schedule_events = set()

        cfg = getattr(self, "queues_config", {})

        for qname, qcfg in cfg.items():
            start_t = qcfg.get("start_time")
            stop_t = qcfg.get("stop_time")

            start_key = (qname, "start", now_time)
            if (
                start_t
                and start_t == now_time
                and start_key not in self._triggered_schedule_events
            ):
                self._triggered_schedule_events.add(start_key)
                max_concur = int(qcfg.get("max_concurrent", 3))
                active = sum(
                    1
                    for t in self.tasks.values()
                    if getattr(t, "queue_name", "Main Download Queue") == qname
                    and t.status
                    in (
                        Status.DOWNLOADING,
                        Status.PROBING,
                        Status.MERGING,
                        Status.EMBEDDING_SUBS,
                    )
                )
                for t in self.tasks.values():
                    if getattr(
                        t, "queue_name", "Main Download Queue"
                    ) == qname and t.status in (Status.QUEUED, Status.PAUSED):
                        if active < max_concur:
                            t.resume()
                            active += 1

            stop_key = (qname, "stop", now_time)
            if (
                stop_t
                and stop_t == now_time
                and stop_key not in self._triggered_schedule_events
            ):
                self._triggered_schedule_events.add(stop_key)
                for t in self.tasks.values():
                    if (
                        getattr(t, "queue_name", "Main Download Queue")
                        == qname
                        and t.status
                        in (
                            Status.DOWNLOADING,
                            Status.PROBING,
                            Status.MERGING,
                            Status.EMBEDDING_SUBS,
                        )
                    ):
                        t.pause()

            action = qcfg.get("on_complete", "Do nothing")
            if action and action != "Do nothing":
                qtasks = [
                    t
                    for t in self.tasks.values()
                    if getattr(t, "queue_name", "Main Download Queue") == qname
                ]
                if qtasks and all(
                    t.status == Status.COMPLETED for t in qtasks
                ):
                    if qname not in self._completed_queue_triggered:
                        self._completed_queue_triggered.add(qname)
                        if action in ("Exit CIDM", "Exit pyidm"):
                            self.quit_app()
                        elif action in ("Shut down Computer", "Sleep Computer"):
                            dlg = CountdownDialog(self, action, seconds=10)
                            dlg.exec()
