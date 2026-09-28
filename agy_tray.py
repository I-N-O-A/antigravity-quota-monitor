"""
Antigravity Quota Monitor - Windows System Tray Utility
Monitors API limits and quotas for Gemini and Claude/GPT model groups in real-time.
Built with PyQt5 for native Windows 11 frosted acrylic glass, smooth anti-aliased
rounded corners (radius 26px), seamless non-client edge resizing, and responsive content scaling.
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

from PyQt5.QtCore import Qt, QTimer, QPoint, QRectF, pyqtSignal, QObject, QEvent
from PyQt5.QtGui import QPainter, QColor, QPainterPath, QPen, QFont, QIcon, QPixmap
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QProgressBar, QFrame, QScrollArea, QSystemTrayIcon,
    QMenu, QAction
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

def apply_acrylic_blur(hwnd, color=0x90101524):
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

        # Do not round DWM bounding rect (DWMWCP_DONOTROUND = 1) so Qt's smooth 26px radius shines without extra outlines
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
    "win_width": 360,
    "win_height": 480,
    "pos_x": None,
    "pos_y": None
}

def load_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                # Filter out obsolete keys
                clean_cfg = {k: v for k, v in cfg.items() if k in DEFAULT_CONFIG}
                return {**DEFAULT_CONFIG, **clean_cfg}
        except Exception:
            pass
    return DEFAULT_CONFIG.copy()

def save_config(cfg):
    try:
        clean_cfg = {k: v for k, v in cfg.items() if k in DEFAULT_CONFIG}
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(clean_cfg, f, indent=2)
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
    if min_fraction > 0.5:
        color = QColor(52, 211, 153)  # Emerald green
    elif min_fraction > 0.2:
        color = QColor(251, 191, 36)  # Amber
    else:
        color = QColor(248, 113, 113) # Coral red

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

# Helper to format countdown matching reference design
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

def create_refresh_icon(color=QColor(203, 213, 225), size=18):
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(color, 1.8)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.drawArc(QRectF(3.0, 3.0, 12.0, 12.0), 35 * 16, 280 * 16)
    path = QPainterPath()
    path.moveTo(9.5, 1.5)
    path.lineTo(13.5, 3.5)
    path.lineTo(12.5, 7.5)
    p.drawPath(path)
    p.end()
    return QIcon(pix)

class SlashedPinIcon(QWidget):
    def __init__(self, pinned=False, parent=None):
        super().__init__(parent)
        self.pinned = pinned
        self.setFixedSize(18, 18)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def set_pinned(self, pinned):
        self.pinned = pinned
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor(255, 255, 255, 220), 1.6)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)

        # Pin shape
        p.drawLine(9, 3, 9, 10)
        p.drawLine(5, 7, 13, 7)
        p.drawLine(9, 10, 9, 15)

        if not self.pinned:
            pen_slash = QPen(QColor(248, 113, 113, 220), 1.6)
            pen_slash.setCapStyle(Qt.RoundCap)
            p.setPen(pen_slash)
            p.drawLine(4, 14, 14, 4)

# Modern Acrylic Quota Card
class ModernQuotaCard(QFrame):
    def __init__(self, group_name, badge_text, badge_color="#38bdf8", parent=None):
        super().__init__(parent)
        self.group_name = group_name
        self.badge_text = badge_text
        self.badge_color = badge_color
        self.setObjectName("quotaCard")
        self.setStyleSheet("""
            #quotaCard {
                background: rgba(0, 0, 0, 0.40);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 16px;
            }
        """)

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(16, 11, 16, 13)
        self.layout.setSpacing(7)

        # Header Row: [Title]   [Badge]
        self.hdr = QHBoxLayout()
        self.hdr.setSpacing(8)

        self.title = QLabel(group_name)
        self.title.setFont(QFont("Segoe UI", 11, QFont.Bold))
        self.title.setStyleSheet("color: #ffffff; letter-spacing: 0.2px;")
        self.hdr.addWidget(self.title)

        self.hdr.addStretch()

        self.badge = QLabel(badge_text)
        self.badge.setFont(QFont("Segoe UI", 8, QFont.Bold))
        self.badge.setStyleSheet(f"""
            background: rgba(255, 255, 255, 0.08);
            color: {badge_color};
            border: 1px solid rgba(255, 255, 255, 0.12);
            padding: 2px 8px;
            border-radius: 10px;
        """)
        self.hdr.addWidget(self.badge)

        self.layout.addLayout(self.hdr)

        # 5h Metric Section
        self.r_5h = QHBoxLayout()
        self.lbl_5h = QLabel("5h")
        self.lbl_5h.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self.lbl_5h.setStyleSheet("color: #ffffff;")
        self.val_5h = QLabel("--%")
        self.val_5h.setFont(QFont("Segoe UI", 11, QFont.Bold))
        self.val_5h.setStyleSheet("color: #34d399;")
        self.r_5h.addWidget(self.lbl_5h)
        self.r_5h.addStretch()
        self.r_5h.addWidget(self.val_5h)
        self.layout.addLayout(self.r_5h)

        self.bar_5h = QProgressBar()
        self.bar_5h.setFixedHeight(5)
        self.bar_5h.setTextVisible(False)
        self.bar_5h.setValue(100)
        self.set_bar_color(self.bar_5h, "#34d399")
        self.layout.addWidget(self.bar_5h)

        self.time_5h = QLabel("Loading...")
        self.time_5h.setFont(QFont("Segoe UI", 8))
        self.time_5h.setStyleSheet("color: #94a3b8;")
        self.layout.addWidget(self.time_5h)

        self.layout.addSpacing(3)

        # Weekly Metric Section
        self.r_wk = QHBoxLayout()
        self.lbl_wk = QLabel("Weekly")
        self.lbl_wk.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self.lbl_wk.setStyleSheet("color: #ffffff;")
        self.val_wk = QLabel("--%")
        self.val_wk.setFont(QFont("Segoe UI", 11, QFont.Bold))
        self.val_wk.setStyleSheet("color: #34d399;")
        self.r_wk.addWidget(self.lbl_wk)
        self.r_wk.addStretch()
        self.r_wk.addWidget(self.val_wk)
        self.layout.addLayout(self.r_wk)

        self.bar_wk = QProgressBar()
        self.bar_wk.setFixedHeight(5)
        self.bar_wk.setTextVisible(False)
        self.bar_wk.setValue(100)
        self.set_bar_color(self.bar_wk, "#34d399")
        self.layout.addWidget(self.bar_wk)

        self.time_wk = QLabel("Loading...")
        self.time_wk.setFont(QFont("Segoe UI", 8))
        self.time_wk.setStyleSheet("color: #94a3b8;")
        self.layout.addWidget(self.time_wk)

        self.bucket_5h_reset = None
        self.bucket_wk_reset = None

    def set_bar_color(self, bar, hex_color):
        bar.setStyleSheet(f"""
            QProgressBar {{
                background: rgba(255, 255, 255, 0.12);
                border-radius: 2px;
                border: none;
            }}
            QProgressBar::chunk {{
                background: {hex_color};
                border-radius: 2px;
            }}
        """)

    def update_data(self, b_5h, b_wk):
        if b_5h:
            frac = b_5h.get("remaining_fraction", 1.0)
            pct = int(round(frac * 100))
            self.val_5h.setText(f"{pct}%")
            self.bar_5h.setValue(pct)
            color = "#34d399" if frac > 0.5 else ("#fbbf24" if frac > 0.2 else "#f87171")
            self.val_5h.setStyleSheet(f"color: {color}; font-weight: bold;")
            self.set_bar_color(self.bar_5h, color)
            self.bucket_5h_reset = b_5h.get("reset_time")
            self.time_5h.setText(format_ref_countdown(self.bucket_5h_reset))

        if b_wk:
            frac = b_wk.get("remaining_fraction", 1.0)
            pct = int(round(frac * 100))
            self.val_wk.setText(f"{pct}%")
            self.bar_wk.setValue(pct)
            color = "#34d399" if frac > 0.5 else ("#fbbf24" if frac > 0.2 else "#f87171")
            self.val_wk.setStyleSheet(f"color: {color}; font-weight: bold;")
            self.set_bar_color(self.bar_wk, color)
            self.bucket_wk_reset = b_wk.get("reset_time")
            self.time_wk.setText(format_ref_countdown(self.bucket_wk_reset))

    def tick_second(self):
        if self.bucket_5h_reset:
            self.time_5h.setText(format_ref_countdown(self.bucket_5h_reset))
        if self.bucket_wk_reset:
            self.time_wk.setText(format_ref_countdown(self.bucket_wk_reset))

    def update_scaling(self, scale):
        pad_h = int(16 * scale)
        pad_v = int(11 * scale)
        spacing = int(7 * scale)
        self.layout.setContentsMargins(pad_h, pad_v, pad_h, pad_v)
        self.layout.setSpacing(spacing)

        t_pt = max(9, int(11 * scale))
        self.title.setFont(QFont("Segoe UI", t_pt, QFont.Bold))

        lbl_pt = max(8, int(10 * scale))
        val_pt = max(9, int(11 * scale))
        self.lbl_5h.setFont(QFont("Segoe UI", lbl_pt, QFont.Bold))
        self.lbl_wk.setFont(QFont("Segoe UI", lbl_pt, QFont.Bold))
        self.val_5h.setFont(QFont("Segoe UI", val_pt, QFont.Bold))
        self.val_wk.setFont(QFont("Segoe UI", val_pt, QFont.Bold))

        time_pt = max(7, int(8 * scale))
        self.time_5h.setFont(QFont("Segoe UI", time_pt))
        self.time_wk.setFont(QFont("Segoe UI", time_pt))

        bar_h = max(4, int(5 * scale))
        self.bar_5h.setFixedHeight(bar_h)
        self.bar_wk.setFixedHeight(bar_h)

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

        w = max(280, self.config.get("win_width", 360))
        h = max(320, self.config.get("win_height", 480))
        self.resize(w, h)
        self.setMinimumSize(280, 320)

        # Initial position
        if self.config.get("pos_x") is not None and self.config.get("pos_y") is not None:
            self.move(self.config["pos_x"], self.config["pos_y"])
        else:
            self.move_to_default_position()

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
        self.main_layout.setContentsMargins(18, 16, 18, 16)
        self.main_layout.setSpacing(10)

        # 1. Header Bar: [AG] Antigravity Quota   [● LIVE]       [Pin] [Close]
        self.hdr = QHBoxLayout()
        self.hdr.setSpacing(8)

        # AG Badge
        self.ag_badge = QLabel("AG")
        self.ag_badge.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self.ag_badge.setStyleSheet("""
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #3b82f6, stop:1 #1d4ed8);
            color: #ffffff;
            padding: 3px 8px;
            border-radius: 8px;
            border: 1px solid rgba(255, 255, 255, 0.25);
        """)
        self.hdr.addWidget(self.ag_badge)

        self.title_lbl = QLabel("Antigravity Quota")
        self.title_lbl.setFont(QFont("Segoe UI", 12, QFont.Bold))
        self.title_lbl.setStyleSheet("color: #ffffff; letter-spacing: 0.2px;")
        self.hdr.addWidget(self.title_lbl)

        self.live_pill = QLabel("● LIVE")
        self.live_pill.setFont(QFont("Segoe UI", 8, QFont.Bold))
        self.live_pill.setStyleSheet("""
            background: rgba(16, 185, 129, 0.18);
            color: #34d399;
            border: 1px solid rgba(52, 211, 153, 0.35);
            padding: 2px 7px;
            border-radius: 8px;
        """)
        self.hdr.addWidget(self.live_pill)

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
                background: rgba(255, 255, 255, 0.18);
            }
        """)
        pin_l = QHBoxLayout(self.btn_pin)
        pin_l.setContentsMargins(0, 0, 0, 0)
        self.pin_icon = SlashedPinIcon(self.is_pinned, self.btn_pin)
        pin_l.addWidget(self.pin_icon, 0, Qt.AlignCenter)
        self.btn_pin.clicked.connect(self.toggle_pin)
        self.hdr.addWidget(self.btn_pin)

        # Close button
        self.btn_close = QPushButton("✕")
        self.btn_close.setFixedSize(28, 28)
        self.btn_close.setToolTip("Close to system tray")
        self.btn_close.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self.btn_close.setCursor(Qt.PointingHandCursor)
        self.btn_close.setStyleSheet("""
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
        self.btn_close.clicked.connect(self.hide)
        self.hdr.addWidget(self.btn_close)

        self.main_layout.addLayout(self.hdr)

        # 2. Scroll Area with Cards
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
                width: 4px;
                margin: 0px;
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

        container = QWidget()
        container.setStyleSheet("background: transparent;")
        c_layout = QVBoxLayout(container)
        c_layout.setContentsMargins(0, 0, 0, 0)
        c_layout.setSpacing(10)

        # Gemini Card
        self.card_gemini = ModernQuotaCard("Gemini Models", "FLASH & PRO", "#38bdf8", container)
        c_layout.addWidget(self.card_gemini)

        # Claude & GPT Card
        self.card_claude = ModernQuotaCard("Claude & GPT", "OPUS & SONNET", "#fb923c", container)
        c_layout.addWidget(self.card_claude)

        c_layout.addStretch()
        self.scroll.setWidget(container)
        self.main_layout.addWidget(self.scroll)

        # 3. Footer Bar: [Status]  [Refresh Btn]
        self.footer = QHBoxLayout()
        self.footer.setContentsMargins(4, 0, 4, 0)

        self.lbl_status = QLabel("Live synchronized")
        self.lbl_status.setFont(QFont("Segoe UI", 9))
        self.lbl_status.setStyleSheet("color: #64748b;")
        self.footer.addWidget(self.lbl_status)

        self.footer.addStretch()

        self.btn_refresh = QPushButton()
        self.btn_refresh.setFixedSize(28, 28)
        self.btn_refresh.setToolTip("Refresh quotas now")
        self.btn_refresh.setCursor(Qt.PointingHandCursor)
        self.btn_refresh.setIcon(create_refresh_icon())
        self.btn_refresh.setStyleSheet("""
            QPushButton {
                background: rgba(255, 255, 255, 0.08);
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 14px;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.18);
            }
        """)
        self.btn_refresh.clicked.connect(self.app_manager.trigger_refresh)
        self.footer.addWidget(self.btn_refresh)

        self.main_layout.addLayout(self.footer)

    def toggle_pin(self):
        self.is_pinned = not self.is_pinned
        self.pin_icon.set_pinned(self.is_pinned)
        self.config["pinned"] = self.is_pinned
        save_config(self.config)

    def changeEvent(self, event):
        if event.type() == QEvent.ActivationChange:
            if self.isActiveWindow():
                self._has_been_active = True
            elif self._has_been_active and not self.is_pinned:
                self.hide()
        super().changeEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, 26, 26)

        # Acrylic dark translucent background fill
        painter.fillPath(path, QColor(14, 20, 32, 175))

        # Thin highlight border
        pen = QPen(QColor(255, 255, 255, 34), 1.0)
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

            # 4 Corners (Native cursor feedback only)
            if p.x() <= bw and p.y() <= bw:
                return True, 13  # HTTOPLEFT
            elif p.x() >= w - bw and p.y() <= bw:
                return True, 14  # HTTOPRIGHT
            elif p.x() <= bw and p.y() >= h - bw:
                return True, 16  # HTBOTTOMLEFT
            elif p.x() >= w - bw and p.y() >= h - bw:
                return True, 17  # HTBOTTOMRIGHT

            # 4 Borders
            if p.x() <= bw:
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

    def resizeEvent(self, event):
        super().resizeEvent(event)
        w = self.width()
        h = self.height()
        self.config["win_width"] = w
        self.config["win_height"] = h
        save_config(self.config)

        # Responsive scaling
        w_factor = w / 360.0
        h_factor = h / 480.0
        factor = min(w_factor, h_factor)
        scale = max(0.80, min(1.0, factor))

        margin = max(12, int(18 * scale))
        spacing = max(8, int(10 * scale))
        self.main_layout.setContentsMargins(margin, margin, margin, margin)
        self.main_layout.setSpacing(spacing)

        title_pt = max(10, int(12 * scale))
        self.title_lbl.setFont(QFont("Segoe UI", title_pt, QFont.Bold))

        self.card_gemini.update_scaling(scale)
        self.card_claude.update_scaling(scale)

    def moveEvent(self, event):
        super().moveEvent(event)
        self.config["pos_x"] = self.x()
        self.config["pos_y"] = self.y()
        save_config(self.config)

    def on_second_tick(self):
        self.card_gemini.tick_second()
        self.card_claude.tick_second()
        diff = int(time.time() - self.last_sync_ts)
        if diff < 5:
            self.lbl_status.setText("Live synchronized")
        else:
            self.lbl_status.setText(f"Updated {diff}s ago")

    def on_data_received(self, data):
        self.last_sync_ts = time.time()
        groups = data.get("groups", [])
        min_frac = 1.0

        for g in groups:
            name = g.get("name", "").lower()
            buckets = g.get("buckets", [])
            b_5h = next((b for b in buckets if b.get("window") == "5h"), None)
            b_wk = next((b for b in buckets if b.get("window") == "weekly"), None)

            for b in buckets:
                frac = b.get("remaining_fraction", 1.0)
                min_frac = min(min_frac, frac)

            if "gemini" in name:
                self.card_gemini.update_data(b_5h, b_wk)
            elif "claude" in name or "gpt" in name or "3p" in name:
                self.card_claude.update_data(b_5h, b_wk)

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
            local_bin = os.path.expanduser(r"~\AppData\Local\Programs\antigravity-cli\bin\agy.exe")
            if os.path.exists(local_bin):
                self.agy_path = local_bin
            else:
                local_bin2 = os.path.expanduser(r"~\AppData\Local\agy\bin\agy.exe")
                if os.path.exists(local_bin2):
                    self.agy_path = local_bin2
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
        self.window._has_been_active = False
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
