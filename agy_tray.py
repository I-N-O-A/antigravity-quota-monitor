"""
Antigravity Quota Monitor - Windows System Tray Utility
Monitors API limits and quotas for Gemini and Claude/GPT model groups in real-time.
1:1 Pixel-Perfect Replica of the Dark Frosted Acrylic Glass UI with smooth 26px rounded corners,
interactive instance switching, real-time live countdowns, seamless non-client resizing,
responsive typography, and system tray integration.
"""

import os
import sys

APP_DIR = os.path.dirname(os.path.abspath(__file__))

# Redirect stdout/stderr when running via pythonw.exe
if sys.stdout is None:
    try:
        sys.stdout = open(os.path.join(APP_DIR, "agy_tray_stdout.log"), "a", encoding="utf-8")
    except Exception:
        sys.stdout = open(os.devnull, "w")

if sys.stderr is None:
    try:
        sys.stderr = open(os.path.join(APP_DIR, "agy_tray_stderr.log"), "a", encoding="utf-8")
    except Exception:
        sys.stderr = open(os.devnull, "w")

import json
import time
import shutil
import ctypes
from ctypes import wintypes
import threading
import winreg
from datetime import datetime, timezone
import subprocess
import webbrowser

from PyQt5.QtCore import Qt, QTimer, QPoint, QRectF, QSize, pyqtSignal, QObject
from PyQt5.QtGui import QPainter, QColor, QPainterPath, QPen, QFont, QIcon, QPixmap, QCursor, QLinearGradient
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QProgressBar, QFrame, QScrollArea, QSystemTrayIcon,
    QMenu, QAction, QSizePolicy
)

# Ensure interactive desktop access
def ensure_default_desktop():
    try:
        user32 = ctypes.windll.user32
        hDesk = user32.OpenDesktopW("Default", 0, False, 0x01FF)
        if hDesk:
            user32.SetThreadDesktop(hDesk)
    except Exception:
        pass

ensure_default_desktop()

# Windows 11 DWM and Composition Structures
class ACCENT_POLICY(ctypes.Structure):
    _fields_ = [
        ("AccentState", ctypes.c_int),
        ("AccentFlags", ctypes.c_int),
        ("GradientColor", ctypes.c_uint32),
        ("AnimationId", ctypes.c_int),
    ]

class WINDOWCOMPOSITIONATTRIBDATA(ctypes.Structure):
    _fields_ = [
        ("Attribute", ctypes.c_int),
        ("Data", ctypes.c_void_p),
        ("SizeOfData", ctypes.c_size_t),
    ]

def apply_acrylic_blur(hwnd, color=0x6018120B):
    """
    Apply native Windows 11 Acrylic blur behind window.
    GradientColor is 0xAABBGGRR.
    """
    try:
        user32 = ctypes.windll.user32
        dwmapi = ctypes.windll.dwmapi

        # Dark mode (DWMWA_USE_IMMERSIVE_DARK_MODE = 20)
        val_dark = ctypes.c_int(1)
        dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(val_dark), 4)

        # Disable DWM outer border (DWMWA_BORDER_COLOR = 34, DWMWA_COLOR_NONE = 0xFFFFFFFE)
        val_border = ctypes.c_uint32(0xFFFFFFFE)
        dwmapi.DwmSetWindowAttribute(hwnd, 34, ctypes.byref(val_border), 4)

        # Do not round DWM bounding rect (DWMWCP_DONOTROUND = 1) so Qt's smooth rounded corners shine
        val_corner = ctypes.c_int(1)
        dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(val_corner), 4)

        accent = ACCENT_POLICY()
        accent.AccentState = 4  # ACCENT_ENABLE_ACRYLICBLURBEHIND
        accent.AccentFlags = 2
        accent.GradientColor = color
        accent.AnimationId = 0

        data = WINDOWCOMPOSITIONATTRIBDATA()
        data.Attribute = 19  # WCA_ACCENT_POLICY
        data.Data = ctypes.cast(ctypes.byref(accent), ctypes.c_void_p)
        data.SizeOfData = ctypes.sizeof(accent)

        user32.SetWindowCompositionAttribute(hwnd, ctypes.byref(data))
    except Exception:
        pass

# Paths & Settings
CONFIG_PATH = os.path.join(APP_DIR, "config.json")
REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
REG_NAME = "AntigravityQuotaTray"
MUTEX_NAME = "AntigravityQuotaTray_SingleInstance_Mutex"
SHOW_EVENT_NAME = "AntigravityQuotaTray_ShowEvent"
_mutex_handle = None
_show_event_handle = None

DEFAULT_CONFIG = {
    "background_refresh_seconds": 60,
    "live_refresh_seconds": 10,
    "pinned": False,
    "win_width": 390,
    "win_height": 485,
    "pos_x": None,
    "pos_y": None,
    "account_email": "ka***e@g***l.com",
    "tier_badge": "PLUS"
}

def load_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                return {**DEFAULT_CONFIG, **cfg}
        except Exception:
            pass
    return DEFAULT_CONFIG.copy()

def save_config(cfg):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass

# Autostart Helpers
def is_autostart_enabled():
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_READ)
        try:
            winreg.QueryValueEx(key, REG_NAME)
            return True
        except FileNotFoundError:
            return False
        finally:
            winreg.CloseKey(key)
    except Exception:
        return False

def set_autostart(enable: bool):
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_SET_VALUE)
        if enable:
            pythonw = shutil.which("pythonw.exe") or sys.executable.replace("python.exe", "pythonw.exe")
            script_path = os.path.abspath(__file__)
            cmd = f'"{pythonw}" "{script_path}" --minimized'
            winreg.SetValueEx(key, REG_NAME, 0, winreg.REG_SZ, cmd)
        else:
            try:
                winreg.DeleteValue(key, REG_NAME)
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
        return True
    except Exception as e:
        print(f"Autostart Error: {e}")
        return False

# High-DPI Tray Icon Generator
def create_tray_pixmap(min_fraction=1.0):
    size = 64
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    # Outer circle background: Deep slate (#0f172a)
    path_bg = QPainterPath()
    path_bg.addEllipse(3, 3, 58, 58)
    painter.fillPath(path_bg, QColor(15, 23, 42, 255))
    painter.strokePath(path_bg, QPen(QColor(51, 65, 85, 255), 1.5))

    # Track ring
    path_track = QPainterPath()
    path_track.addEllipse(5, 5, 54, 54)
    painter.strokePath(path_track, QPen(QColor(51, 65, 85, 180), 3.5))

    # Color for quota
    if min_fraction >= 0.8:
        color = QColor(52, 211, 153)  # Emerald green
    elif min_fraction >= 0.25:
        color = QColor(245, 158, 11)  # Warm Amber
    else:
        color = QColor(239, 68, 68)   # Coral red

    # Progress Arc
    span_angle = int(max(0.04, min(1.0, min_fraction)) * 360 * 16)
    pen_arc = QPen(color, 4.0)
    pen_arc.setCapStyle(Qt.RoundCap)
    painter.setPen(pen_arc)
    painter.drawArc(5, 5, 54, 54, 90 * 16, -span_angle)

    # Center text "AG"
    font = QFont("Segoe UI", 16, QFont.Bold)
    painter.setFont(font)
    painter.setPen(QColor(255, 255, 255))
    painter.drawText(QRectF(0, 1, size, size), Qt.AlignCenter, "AG")

    painter.end()
    return pixmap

# Helper to format countdown exactly matching reference
def format_ref_countdown(reset_time_str):
    if not reset_time_str:
        return "100% available"
    try:
        t_clean = reset_time_str.replace("Z", "+00:00")
        target = datetime.fromisoformat(t_clean)
        now = datetime.now(timezone.utc)
        diff = (target - now).total_seconds()
        local_time = target.astimezone()
        local_str = local_time.strftime("%m/%d %H:%M")
        if diff <= 0:
            return f"100% refreshed ({local_str})"
        d = int(diff // 86400)
        h = int((diff % 86400) // 3600)
        m = int((diff % 3600) // 60)
        s = int(diff % 60)
        if d > 0:
            return f"{d}d {h}h {m}m ({local_str})"
        elif h > 0:
            return f"{h}h {m}m ({local_str})"
        else:
            return f"{m}m {s:02d}s ({local_str})"
    except Exception:
        return reset_time_str

# Clean Vector Logo Widget
class ReferenceLogo(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(28, 28)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor(255, 255, 255, 225), 1.5)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)

        cx, cy = 14.0, 14.0
        p.translate(cx, cy)
        
        for i in range(6):
            p.save()
            p.rotate(i * 60)
            path = QPainterPath()
            path.moveTo(0, -11)
            path.cubicTo(4.5, -11, 7.5, -7.5, 7.5, -3)
            path.cubicTo(7.5, 1.5, 4.0, 4.5, 0, 4.5)
            p.drawPath(path)
            p.restore()

# Slashed Pin Icon Widget
class SlashedPinIcon(QWidget):
    def __init__(self, pinned=False, parent=None):
        super().__init__(parent)
        self.pinned = pinned
        self.setFixedSize(18, 18)

    def setPinned(self, p):
        self.pinned = p
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor(255, 255, 255, 210), 1.6)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)

        p.drawLine(9, 3, 9, 9)
        p.drawLine(5, 9, 13, 9)
        p.drawLine(9, 9, 9, 15)

        if not self.pinned:
            pen_slash = QPen(QColor(255, 255, 255, 190), 1.6)
            pen_slash.setCapStyle(Qt.RoundCap)
            p.setPen(pen_slash)
            p.drawLine(4, 14, 14, 4)

def create_back_icon(color=QColor(255, 255, 255), size=18):
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(color, 1.8)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)

    path = QPainterPath()
    path.moveTo(6.5, 2.0)
    path.lineTo(3.0, 5.0)
    path.lineTo(6.5, 8.0)
    
    path.moveTo(3.5, 5.0)
    path.cubicTo(6.5, 1.5, 14.0, 1.5, 14.0, 6.5)
    path.cubicTo(14.0, 10.5, 11.5, 10.5, 7.5, 10.5)
    p.drawPath(path)
    p.end()
    return QIcon(pix)

def create_refresh_icon(color=QColor(203, 213, 225), size=18):
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(color, 1.8)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)

    p.drawArc(QRectF(3.0, 3.0, 12.0, 12.0), 30 * 16, 280 * 16)
    path = QPainterPath()
    path.moveTo(9.5, 1.5)
    path.lineTo(13.5, 3.5)
    path.lineTo(12.5, 7.5)
    p.drawPath(path)
    p.end()
    return QIcon(pix)

def create_external_icon(color=QColor(203, 213, 225), size=18):
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(color, 1.8)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)

    path_box = QPainterPath()
    path_box.moveTo(9.0, 4.0)
    path_box.lineTo(4.0, 4.0)
    path_box.lineTo(4.0, 14.0)
    path_box.lineTo(14.0, 14.0)
    path_box.lineTo(14.0, 9.0)
    p.drawPath(path_box)

    p.drawLine(8, 10, 14, 4)
    path_head = QPainterPath()
    path_head.moveTo(10.5, 4.0)
    path_head.lineTo(14.0, 4.0)
    path_head.lineTo(14.0, 7.5)
    p.drawPath(path_head)
    p.end()
    return QIcon(pix)

# Main Glass Floating Window
class GlassWindow(QWidget):
    BORDER_WIDTH = 9
    data_received = pyqtSignal(dict)

    def __init__(self, app_manager):
        super().__init__()
        self.app_manager = app_manager
        self.config = load_config()
        self.is_pinned = self.config.get("pinned", False)
        self._has_been_active = False

        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setWindowTitle("Antigravity Quota Monitor")
        self.setAttribute(Qt.WA_TranslucentBackground)

        w = max(310, self.config.get("win_width", 390))
        h = max(380, self.config.get("win_height", 485))
        self.resize(w, h)
        self.setMinimumSize(300, 360)

        # Initial position
        if self.config.get("pos_x") is not None and self.config.get("pos_y") is not None:
            self.move(self.config["pos_x"], self.config["pos_y"])
        else:
            self.move_to_default_position()

        # Instances model list
        self.instances = [
            {
                "id": "gemini",
                "name": "Gemini Models",
                "tag": "Cod",
                "account": self.config.get("account_email", "ka***e@g***l.com"),
                "tier": self.config.get("tier_badge", "PLUS"),
                "5h": {"pct": 100, "frac": 1.0, "time": "Loading...", "reset_time": None},
                "weekly": {"pct": 100, "frac": 1.0, "time": "Loading...", "reset_time": None}
            },
            {
                "id": "3p",
                "name": "Claude and GPT models",
                "tag": "3P",
                "account": self.config.get("account_email", "ka***e@g***l.com"),
                "tier": self.config.get("tier_badge", "PLUS"),
                "5h": {"pct": 100, "frac": 1.0, "time": "Loading...", "reset_time": None},
                "weekly": {"pct": 100, "frac": 1.0, "time": "Loading...", "reset_time": None}
            }
        ]
        self.current_idx = 0
        self.overview_mode = False

        self.init_ui()

        # Connect data signal
        self.data_received.connect(self.on_data_received)

        # 1-second countdown ticker
        self.ticker = QTimer(self)
        self.ticker.timeout.connect(self.on_second_tick)
        self.ticker.start(1000)

        self.last_sync_ts = time.time()

    def move_to_default_position(self):
        screen = QApplication.primaryScreen().availableGeometry()
        x = screen.right() - self.width() - 20
        y = screen.bottom() - self.height() - 20
        self.move(x, y)

    def init_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(18, 16, 18, 18)
        self.main_layout.setSpacing(12)

        # 1. Header Bar: [Logo]      Default Instance      [Pin] [Close]
        self.hdr = QHBoxLayout()
        self.hdr.setContentsMargins(2, 2, 2, 2)
        self.hdr.setSpacing(8)

        self.logo = ReferenceLogo(self)
        self.hdr.addWidget(self.logo)

        self.hdr.addStretch()

        self.title_lbl = QLabel("Default Instance")
        self.title_lbl.setFont(QFont("Segoe UI", 13, QFont.Bold))
        self.title_lbl.setStyleSheet("color: #ffffff; letter-spacing: 0.2px;")
        self.hdr.addWidget(self.title_lbl)

        self.hdr.addStretch()

        # Pin button
        self.btn_pin = QPushButton()
        self.btn_pin.setFixedSize(28, 28)
        self.btn_pin.setToolTip("Pin window (keep visible)")
        self.btn_pin.setCursor(Qt.PointingHandCursor)
        self.btn_pin.setStyleSheet("""
            QPushButton {
                background: rgba(255, 255, 255, 0.08);
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 14px;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.16);
            }
        """)
        pin_layout = QHBoxLayout(self.btn_pin)
        pin_layout.setContentsMargins(0, 0, 0, 0)
        self.pin_icon = SlashedPinIcon(self.is_pinned, self.btn_pin)
        pin_layout.addWidget(self.pin_icon, 0, Qt.AlignCenter)
        self.btn_pin.clicked.connect(self.toggle_pin)
        self.hdr.addWidget(self.btn_pin)

        # Close button
        btn_close = QPushButton("✕")
        btn_close.setFixedSize(28, 28)
        btn_close.setToolTip("Close to system tray")
        btn_close.setFont(QFont("Segoe UI", 10, QFont.Bold))
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.setStyleSheet("""
            QPushButton {
                background: rgba(255, 255, 255, 0.08);
                color: #cbd5e1;
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 14px;
                padding-bottom: 2px;
            }
            QPushButton:hover {
                background: rgba(239, 68, 68, 0.35);
                color: #ffffff;
                border-color: rgba(239, 68, 68, 0.50);
            }
        """)
        btn_close.clicked.connect(self.hide)
        self.hdr.addWidget(btn_close)

        self.main_layout.addLayout(self.hdr)

        # 2. Sub-header Navigation Pill Row: [Cod ⌵]   <   1 / 2   >   [Account preview]
        self.sub_hdr = QHBoxLayout()
        self.sub_hdr.setSpacing(8)

        self.btn_model = QPushButton("Cod  ⌵")
        self.btn_model.setFixedHeight(28)
        self.btn_model.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self.btn_model.setCursor(Qt.PointingHandCursor)
        self.btn_model.setStyleSheet("""
            QPushButton {
                background: rgba(0, 0, 0, 0.38);
                color: #ffffff;
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 14px;
                padding: 0 14px;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.12);
            }
        """)
        self.btn_model.clicked.connect(self.show_model_menu)
        self.sub_hdr.addWidget(self.btn_model)

        self.sub_hdr.addStretch()

        # Center nav [<  1 / 2  >]
        self.btn_prev = QPushButton("<")
        self.btn_prev.setFixedSize(26, 26)
        self.btn_prev.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self.btn_prev.setCursor(Qt.PointingHandCursor)
        self.btn_prev.setStyleSheet("""
            QPushButton {
                background: rgba(0, 0, 0, 0.32);
                color: #94a3b8;
                border: 1px solid rgba(255, 255, 255, 0.10);
                border-radius: 13px;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.15);
                color: #ffffff;
            }
        """)
        self.btn_prev.clicked.connect(self.prev_instance)
        self.sub_hdr.addWidget(self.btn_prev)

        self.lbl_counter = QLabel("1 / 2")
        self.lbl_counter.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self.lbl_counter.setStyleSheet("color: #e2e8f0; padding: 0 4px;")
        self.sub_hdr.addWidget(self.lbl_counter)

        self.btn_next = QPushButton(">")
        self.btn_next.setFixedSize(26, 26)
        self.btn_next.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self.btn_next.setCursor(Qt.PointingHandCursor)
        self.btn_next.setStyleSheet("""
            QPushButton {
                background: rgba(0, 0, 0, 0.32);
                color: #94a3b8;
                border: 1px solid rgba(255, 255, 255, 0.10);
                border-radius: 13px;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.15);
                color: #ffffff;
            }
        """)
        self.btn_next.clicked.connect(self.next_instance)
        self.sub_hdr.addWidget(self.btn_next)

        self.sub_hdr.addStretch()

        # Account preview pill
        self.btn_preview = QPushButton("Account preview")
        self.btn_preview.setFixedHeight(28)
        self.btn_preview.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self.btn_preview.setCursor(Qt.PointingHandCursor)
        self.btn_preview.setStyleSheet("""
            QPushButton {
                background: rgba(0, 0, 0, 0.38);
                color: #e2e8f0;
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 14px;
                padding: 0 13px;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.12);
            }
        """)
        self.btn_preview.clicked.connect(self.toggle_overview)
        self.sub_hdr.addWidget(self.btn_preview)

        self.main_layout.addLayout(self.sub_hdr)

        # 3. Account ID & Tier Badge Row: [ka***e@g***l.com]      [PLUS]
        self.acc_row = QHBoxLayout()
        self.acc_row.setContentsMargins(4, 4, 4, 0)
        self.acc_lbl = QLabel(self.config.get("account_email", "ka***e@g***l.com"))
        self.acc_lbl.setFont(QFont("Segoe UI", 16, QFont.Bold))
        self.acc_lbl.setStyleSheet("color: #ffffff; letter-spacing: 0.2px;")
        self.acc_row.addWidget(self.acc_lbl)

        self.acc_row.addStretch()

        self.badge_tier = QLabel(self.config.get("tier_badge", "PLUS"))
        self.badge_tier.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self.badge_tier.setAlignment(Qt.AlignCenter)
        self.badge_tier.setFixedSize(58, 24)
        self.badge_tier.setStyleSheet("""
            background: #7ae3b5;
            color: #042f2e;
            border-radius: 12px;
            font-weight: 800;
            letter-spacing: 0.6px;
        """)
        self.acc_row.addWidget(self.badge_tier)

        self.main_layout.addLayout(self.acc_row)

        # 4. Scrollable Container for Quota Card(s)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll.setStyleSheet("""
            QScrollArea {
                background: transparent;
                border: none;
            }
            QScrollBar:vertical {
                border: none;
                background: transparent;
                width: 5px;
                margin: 2px 0px 2px 0px;
            }
            QScrollBar::handle:vertical {
                background: rgba(255, 255, 255, 0.20);
                border-radius: 2px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(255, 255, 255, 0.35);
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: transparent;
            }
        """)

        self.card_container = QWidget()
        self.card_container.setStyleSheet("background: transparent;")
        self.card_cont_layout = QVBoxLayout(self.card_container)
        self.card_cont_layout.setContentsMargins(0, 0, 0, 0)
        self.card_cont_layout.setSpacing(10)

        # Main Single Quota Card
        self.card_frame = QFrame()
        self.card_frame.setStyleSheet("""
            QFrame#mainCard {
                background: rgba(0, 0, 0, 0.36);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 16px;
            }
        """)
        self.card_frame.setObjectName("mainCard")
        card_layout = QVBoxLayout(self.card_frame)
        card_layout.setContentsMargins(18, 16, 18, 16)
        card_layout.setSpacing(6)

        # 5h section
        row_5h = QHBoxLayout()
        self.lbl_5h_title = QLabel("5h")
        self.lbl_5h_title.setFont(QFont("Segoe UI", 11, QFont.Bold))
        self.lbl_5h_title.setStyleSheet("color: #ffffff; border: none; background: transparent;")
        row_5h.addWidget(self.lbl_5h_title)

        row_5h.addStretch()

        self.val_5h = QLabel("100%")
        self.val_5h.setFont(QFont("Segoe UI", 11, QFont.Bold))
        self.val_5h.setStyleSheet("color: #34d399; border: none; background: transparent;")
        row_5h.addWidget(self.val_5h)
        card_layout.addLayout(row_5h)

        self.bar_5h = QProgressBar()
        self.bar_5h.setFixedHeight(5)
        self.bar_5h.setTextVisible(False)
        self.bar_5h.setValue(100)
        self.set_bar_chunk_color(self.bar_5h, "#34d399")
        card_layout.addWidget(self.bar_5h)

        self.time_5h = QLabel("4h 56m (09/29 00:05)")
        self.time_5h.setFont(QFont("Segoe UI", 9))
        self.time_5h.setStyleSheet("color: #64748b; border: none; background: transparent;")
        card_layout.addWidget(self.time_5h)

        # Divider line
        self.div = QFrame()
        self.div.setFixedHeight(1)
        self.div.setStyleSheet("background: rgba(255, 255, 255, 0.05); border: none;")
        card_layout.addSpacing(6)
        card_layout.addWidget(self.div)
        card_layout.addSpacing(6)

        # Weekly section
        row_wk = QHBoxLayout()
        self.lbl_wk_title = QLabel("Weekly")
        self.lbl_wk_title.setFont(QFont("Segoe UI", 11, QFont.Bold))
        self.lbl_wk_title.setStyleSheet("color: #ffffff; border: none; background: transparent;")
        row_wk.addWidget(self.lbl_wk_title)

        row_wk.addStretch()

        self.val_wk = QLabel("73%")
        self.val_wk.setFont(QFont("Segoe UI", 11, QFont.Bold))
        self.val_wk.setStyleSheet("color: #f59e0b; border: none; background: transparent;")
        row_wk.addWidget(self.val_wk)
        card_layout.addLayout(row_wk)

        self.bar_wk = QProgressBar()
        self.bar_wk.setFixedHeight(5)
        self.bar_wk.setTextVisible(False)
        self.bar_wk.setValue(73)
        self.set_bar_chunk_color(self.bar_wk, "#f59e0b")
        card_layout.addWidget(self.bar_wk)

        self.time_wk = QLabel("6d 13h 55m (10/05 09:04)")
        self.time_wk.setFont(QFont("Segoe UI", 9))
        self.time_wk.setStyleSheet("color: #64748b; border: none; background: transparent;")
        card_layout.addWidget(self.time_wk)

        self.card_cont_layout.addWidget(self.card_frame)

        self.scroll.setWidget(self.card_container)
        self.main_layout.addWidget(self.scroll)

        self.main_layout.addStretch()

        # 5. Bottom Action Bar: [Back]  [Switch]             [↻]  [↗]
        self.footer = QHBoxLayout()
        self.footer.setContentsMargins(4, 2, 4, 2)
        self.footer.setSpacing(8)

        self.btn_back = QPushButton(" Back")
        self.btn_back.setIcon(create_back_icon())
        self.btn_back.setIconSize(QSize(16, 16))
        self.btn_back.setFixedHeight(34)
        self.btn_back.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self.btn_back.setCursor(Qt.PointingHandCursor)
        self.btn_back.setStyleSheet("""
            QPushButton {
                background: rgba(0, 0, 0, 0.40);
                color: #ffffff;
                border: 1px solid rgba(255, 255, 255, 0.14);
                border-radius: 17px;
                padding: 0 14px;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.12);
            }
        """)
        self.btn_back.clicked.connect(self.prev_instance)
        self.footer.addWidget(self.btn_back)

        self.btn_switch = QPushButton("Switch")
        self.btn_switch.setFixedHeight(34)
        self.btn_switch.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self.btn_switch.setCursor(Qt.PointingHandCursor)
        self.btn_switch.setStyleSheet("""
            QPushButton {
                background: #f59e0b;
                color: #000000;
                border: none;
                border-radius: 17px;
                padding: 0 16px;
                font-weight: 800;
            }
            QPushButton:hover {
                background: #fbbf24;
            }
            QPushButton:pressed {
                background: #d97706;
            }
        """)
        self.btn_switch.clicked.connect(self.next_instance)
        self.footer.addWidget(self.btn_switch)

        self.footer.addStretch()

        # Circular Refresh button
        self.btn_refresh = QPushButton()
        self.btn_refresh.setIcon(create_refresh_icon())
        self.btn_refresh.setIconSize(QSize(16, 16))
        self.btn_refresh.setFixedSize(34, 34)
        self.btn_refresh.setCursor(Qt.PointingHandCursor)
        self.btn_refresh.setStyleSheet("""
            QPushButton {
                background: rgba(0, 0, 0, 0.40);
                border: 1px solid rgba(255, 255, 255, 0.14);
                border-radius: 17px;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.15);
            }
        """)
        self.btn_refresh.clicked.connect(self.app_manager.trigger_refresh)
        self.footer.addWidget(self.btn_refresh)

        # Circular Link button
        self.btn_link = QPushButton()
        self.btn_link.setIcon(create_external_icon())
        self.btn_link.setIconSize(QSize(16, 16))
        self.btn_link.setFixedSize(34, 34)
        self.btn_link.setCursor(Qt.PointingHandCursor)
        self.btn_link.setStyleSheet("""
            QPushButton {
                background: rgba(0, 0, 0, 0.40);
                border: 1px solid rgba(255, 255, 255, 0.14);
                border-radius: 17px;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.15);
            }
        """)
        self.btn_link.clicked.connect(self.open_web_dashboard)
        self.footer.addWidget(self.btn_link)

        self.main_layout.addLayout(self.footer)

        self.update_display()

    def set_bar_chunk_color(self, bar, hex_color):
        bar.setStyleSheet(f"""
            QProgressBar {{
                background: rgba(255, 255, 255, 0.09);
                border-radius: 2.5px;
                border: none;
            }}
            QProgressBar::chunk {{
                background: {hex_color};
                border-radius: 2.5px;
            }}
        """)

    def update_display(self):
        total = len(self.instances)
        if total == 0:
            return

        self.current_idx = self.current_idx % total
        inst = self.instances[self.current_idx]

        self.lbl_counter.setText(f"{self.current_idx + 1} / {total}")
        self.btn_model.setText(f"{inst['tag']}  ⌵")
        self.acc_lbl.setText(inst.get("account", "ka***e@g***l.com"))
        self.badge_tier.setText(inst.get("tier", "PLUS"))

        pct_5h = inst["5h"]["pct"]
        self.val_5h.setText(f"{pct_5h}%")
        self.bar_5h.setValue(pct_5h)
        col_5h = "#34d399" if pct_5h >= 80 else ("#f59e0b" if pct_5h >= 25 else "#ef4444")
        self.val_5h.setStyleSheet(f"color: {col_5h}; font-weight: bold; border: none; background: transparent;")
        self.set_bar_chunk_color(self.bar_5h, col_5h)
        self.time_5h.setText(inst["5h"]["time"])

        pct_wk = inst["weekly"]["pct"]
        self.val_wk.setText(f"{pct_wk}%")
        self.bar_wk.setValue(pct_wk)
        col_wk = "#34d399" if pct_wk >= 80 else ("#f59e0b" if pct_wk >= 25 else "#ef4444")
        self.val_wk.setStyleSheet(f"color: {col_wk}; font-weight: bold; border: none; background: transparent;")
        self.set_bar_chunk_color(self.bar_wk, col_wk)
        self.time_wk.setText(inst["weekly"]["time"])

    def show_model_menu(self):
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background: #182030;
                color: #f1f5f9;
                border: 1px solid rgba(255, 255, 255, 0.15);
                border-radius: 8px;
                padding: 4px;
            }
            QMenu::item {
                padding: 6px 18px 6px 12px;
                border-radius: 4px;
                font-weight: 600;
            }
            QMenu::item:selected {
                background: #3b82f6;
                color: #ffffff;
            }
        """)
        for idx, inst in enumerate(self.instances):
            act = QAction(f"{inst['name']} ({inst['tag']})", menu)
            act.triggered.connect(lambda checked, i=idx: self.select_instance(i))
            menu.addAction(act)

        menu.exec_(self.btn_model.mapToGlobal(QPoint(0, self.btn_model.height() + 4)))

    def select_instance(self, idx):
        self.current_idx = idx
        self.update_display()

    def cycle_instance(self):
        self.current_idx = (self.current_idx + 1) % len(self.instances)
        self.update_display()

    def next_instance(self):
        self.current_idx = (self.current_idx + 1) % len(self.instances)
        self.update_display()

    def prev_instance(self):
        self.current_idx = (self.current_idx - 1) % len(self.instances)
        self.update_display()

    def toggle_overview(self):
        self.cycle_instance()

    def open_web_dashboard(self):
        webbrowser.open("https://aistudio.google.com")

    def toggle_pin(self):
        self.is_pinned = not self.is_pinned
        self.pin_icon.setPinned(self.is_pinned)
        self.config["pinned"] = self.is_pinned
        save_config(self.config)

    def showEvent(self, event):
        super().showEvent(event)
        apply_acrylic_blur(int(self.winId()))
        self._has_been_active = False

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        path = QPainterPath()
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path.addRoundedRect(rect, 26, 26)

        # Translucent dark frosted background fill
        painter.fillPath(path, QColor(11, 17, 28, 145))

        # Specular light highlight gradient at the very top
        top_grad = QLinearGradient(0, 1, 0, 42)
        top_grad.setColorAt(0, QColor(255, 255, 255, 18))
        top_grad.setColorAt(1, QColor(255, 255, 255, 0))
        painter.fillPath(path, top_grad)

        # Thin elegant highlight border
        pen = QPen(QColor(255, 255, 255, 34), 1.2)
        painter.setPen(pen)
        painter.drawPath(path)

    def nativeEvent(self, eventType, message):
        msg = wintypes.MSG.from_address(message.__int__())
        WM_NCHITTEST = 0x0084

        if msg.message == WM_NCHITTEST:
            x = ctypes.c_short(msg.lParam & 0xFFFF).value
            y = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value
            
            p = self.mapFromGlobal(QPoint(x, y))
            w = self.width()
            h = self.height()
            bw = self.BORDER_WIDTH

            # 4 Corners (Completely invisible - native cursor feedback only)
            if p.x() <= bw and p.y() <= bw:
                return True, 13  # HTTOPLEFT
            elif p.x() >= w - bw and p.y() <= bw:
                return True, 14  # HTTOPRIGHT
            elif p.x() <= bw and p.y() >= h - bw:
                return True, 16  # HTBOTTOMLEFT
            elif p.x() >= w - bw and p.y() >= h - bw:
                return True, 17  # HTBOTTOMRIGHT
            
            # 4 Edges
            elif p.x() <= bw:
                return True, 10  # HTLEFT
            elif p.x() >= w - bw:
                return True, 11  # HTRIGHT
            elif p.y() <= bw:
                return True, 12  # HTTOP
            elif p.y() >= h - bw:
                return True, 15  # HTBOTTOM

            # Top header bar (Drag to move, except buttons)
            if p.y() <= 48 and p.x() < (w - 75):
                return True, 2   # HTCAPTION

        return super().nativeEvent(eventType, message)

    def changeEvent(self, event):
        super().changeEvent(event)
        # If user clicked outside and window lost activation, close automatically unless pinned
        if event.type() == event.ActivationChange:
            if self.isActiveWindow():
                self._has_been_active = True
            elif self._has_been_active and not self.is_pinned:
                self.hide()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.hide()
        else:
            super().keyPressEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        w = self.width()
        h = self.height()

        self.config["win_width"] = w
        self.config["win_height"] = h
        save_config(self.config)

        # Responsive scale calculation:
        # Base width is 390, base height is 485
        w_factor = w / 390.0
        h_factor = h / 485.0
        factor = min(w_factor, h_factor)
        scale = max(0.80, min(1.0, factor))

        # Update layouts
        margin = max(12, int(18 * scale))
        spacing = max(8, int(12 * scale))
        self.main_layout.setContentsMargins(margin, margin, margin, margin)
        self.main_layout.setSpacing(spacing)

        title_pt = max(10, int(13 * scale))
        self.title_lbl.setFont(QFont("Segoe UI", title_pt, QFont.Bold))

        acc_pt = max(12, int(16 * scale))
        self.acc_lbl.setFont(QFont("Segoe UI", acc_pt, QFont.Bold))

    def moveEvent(self, event):
        super().moveEvent(event)
        self.config["pos_x"] = self.x()
        self.config["pos_y"] = self.y()
        save_config(self.config)

    def on_second_tick(self):
        for inst in self.instances:
            if inst["5h"].get("reset_time"):
                inst["5h"]["time"] = format_ref_countdown(inst["5h"]["reset_time"])
            if inst["weekly"].get("reset_time"):
                inst["weekly"]["time"] = format_ref_countdown(inst["weekly"]["reset_time"])
        self.update_display()

    def on_data_received(self, data):
        self.last_sync_ts = time.time()
        groups = data.get("groups", [])
        min_frac = 1.0

        for g in groups:
            name = g.get("name", "")
            name_lower = name.lower()
            buckets = g.get("buckets", [])
            b_5h = next((b for b in buckets if b.get("window") == "5h"), None)
            b_wk = next((b for b in buckets if b.get("window") == "weekly"), None)

            for b in buckets:
                frac = b.get("remaining_fraction", 1.0)
                min_frac = min(min_frac, frac)

            # Match instance
            target_inst = None
            if "gemini" in name_lower:
                target_inst = next((i for i in self.instances if i["id"] == "gemini"), None)
            elif "claude" in name_lower or "gpt" in name_lower or "3p" in name_lower:
                target_inst = next((i for i in self.instances if i["id"] == "3p"), None)

            if target_inst:
                if b_5h:
                    frac_5h = b_5h.get("remaining_fraction", 1.0)
                    target_inst["5h"]["frac"] = frac_5h
                    target_inst["5h"]["pct"] = int(round(frac_5h * 100))
                    target_inst["5h"]["reset_time"] = b_5h.get("reset_time")
                    target_inst["5h"]["time"] = format_ref_countdown(b_5h.get("reset_time"))

                if b_wk:
                    frac_wk = b_wk.get("remaining_fraction", 1.0)
                    target_inst["weekly"]["frac"] = frac_wk
                    target_inst["weekly"]["pct"] = int(round(frac_wk * 100))
                    target_inst["weekly"]["reset_time"] = b_wk.get("reset_time")
                    target_inst["weekly"]["time"] = format_ref_countdown(b_wk.get("reset_time"))

        self.update_display()
        self.app_manager.update_tray_icon(min_frac)

# Main Application Controller
class AppManager(QObject):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.config = load_config()

        # Locate agy.exe
        self.agy_path = shutil.which("agy") or shutil.which("agy.exe")
        if not self.agy_path:
            local_bin = os.path.expanduser(r"~\AppData\Local\agy\bin\agy.exe")
            if os.path.exists(local_bin):
                self.agy_path = local_bin
            else:
                self.agy_path = "agy"

        # Setup System Tray Icon
        self.tray = QSystemTrayIcon()
        self.update_tray_icon(1.0)
        self.tray.setToolTip("Antigravity Quota Monitor")
        self.tray.activated.connect(self.on_tray_activated)

        # Context Menu
        self.menu = QMenu()
        self.menu.setStyleSheet("""
            QMenu {
                background: #182030;
                color: #f1f5f9;
                border: 1px solid rgba(255, 255, 255, 0.15);
                border-radius: 8px;
                padding: 4px;
            }
            QMenu::item {
                padding: 6px 20px 6px 12px;
                border-radius: 4px;
                font-weight: 500;
            }
            QMenu::item:selected {
                background: #3b82f6;
                color: #ffffff;
            }
            QMenu::separator {
                height: 1px;
                background: rgba(255, 255, 255, 0.10);
                margin: 4px 6px;
            }
        """)

        act_open = QAction("Open Dashboard", self.menu)
        act_open.triggered.connect(self.show_window)
        self.menu.addAction(act_open)

        act_refresh = QAction("Refresh Now", self.menu)
        act_refresh.triggered.connect(self.trigger_refresh)
        self.menu.addAction(act_refresh)

        self.menu.addSeparator()

        self.act_autostart = QAction("Start with Windows", self.menu)
        self.act_autostart.setCheckable(True)
        self.act_autostart.setChecked(is_autostart_enabled())
        self.act_autostart.triggered.connect(self.toggle_autostart)
        self.menu.addAction(self.act_autostart)

        self.menu.addSeparator()

        act_quit = QAction("Exit", self.menu)
        act_quit.triggered.connect(self.quit_app)
        self.menu.addAction(act_quit)

        self.tray.setContextMenu(self.menu)
        self.tray.show()

        # Create Window
        self.window = GlassWindow(self)

        # Background Fetch Timer
        self.bg_timer = QTimer(self)
        self.bg_timer.timeout.connect(self.on_bg_timer)
        self.bg_timer.start(self.config.get("background_refresh_seconds", 60) * 1000)

        # Initial fetch
        self.trigger_refresh()

        # If not minimized on launch, show
        if "--minimized" not in sys.argv:
            self.show_window()

    def update_tray_icon(self, fraction):
        pixmap = create_tray_pixmap(fraction)
        self.tray.setIcon(QIcon(pixmap))

    def on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger: # Left click
            if self.window.isVisible():
                self.window.hide()
            else:
                self.show_window()

    def show_window(self):
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()
        try:
            hwnd = int(self.window.winId())
            ctypes.windll.user32.SetForegroundWindow(hwnd)
        except Exception:
            pass
        apply_acrylic_blur(int(self.window.winId()))
        self.trigger_refresh()

    def toggle_autostart(self):
        current = self.act_autostart.isChecked()
        success = set_autostart(current)
        if not success:
            self.act_autostart.setChecked(not current)

    def trigger_refresh(self):
        threading.Thread(target=self._fetch_worker, daemon=True).start()

    def on_bg_timer(self):
        self.trigger_refresh()

    def _fetch_worker(self):
        try:
            CREATE_NO_WINDOW = 0x08000000
            res = subprocess.run(
                [self.agy_path, "-p", "/usage", "--output-format", "json"],
                capture_output=True,
                text=True,
                timeout=12,
                creationflags=CREATE_NO_WINDOW
            )
            if res.returncode == 0 and res.stdout:
                parsed = json.loads(res.stdout)
                cmd_data = parsed.get("command", {}).get("data", {})
                if cmd_data:
                    self.window.data_received.emit(cmd_data)
        except Exception:
            pass

    def quit_app(self):
        self.tray.hide()
        self.app.quit()

# Single Instance Check
def check_single_instance():
    global _mutex_handle, _show_event_handle
    kernel32 = ctypes.windll.kernel32
    ERROR_ALREADY_EXISTS = 183

    _mutex_handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    last_err = kernel32.GetLastError()
    if last_err == ERROR_ALREADY_EXISTS:
        # Signal existing instance to show
        event_handle = kernel32.OpenEventW(0x0002, False, SHOW_EVENT_NAME)
        if event_handle:
            kernel32.SetEvent(event_handle)
            kernel32.CloseHandle(event_handle)
        return False

    _show_event_handle = kernel32.CreateEventW(None, False, False, SHOW_EVENT_NAME)
    return True

def start_show_event_listener(app_manager):
    def listener():
        kernel32 = ctypes.windll.kernel32
        while True:
            res = kernel32.WaitForSingleObject(_show_event_handle, 0xFFFFFFFF)
            if res == 0:  # WAIT_OBJECT_0
                QTimer.singleShot(0, app_manager.show_window)
    t = threading.Thread(target=listener, daemon=True)
    t.start()

def main():
    if not check_single_instance():
        sys.exit(0)

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    manager = AppManager(app)
    start_show_event_listener(manager)

    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
