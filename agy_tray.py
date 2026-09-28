"""
Antigravity Quota Monitor - Windows System Tray Utility
Monitors API limits and quotas for Gemini and Claude/GPT model groups in real-time.
Built with PyQt5 for native Windows 11 frosted acrylic glass, seamless 12px DWM rounding
(zero corner artifacts), true non-scrolling fluid responsive scaling down to micro-widget sizes (170x190),
and high-end vector glass-style icons.
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
import math
import shutil
import ctypes
from ctypes import wintypes
import threading
import webbrowser
import winreg
from datetime import datetime, timezone
import subprocess

from PyQt5.QtCore import Qt, QTimer, QPoint, QPointF, QRectF, QSize, QByteArray, pyqtSignal, QObject, QEvent
from PyQt5.QtGui import (
    QPainter, QColor, QPainterPath, QPen, QFont, QIcon, QPixmap,
    QLinearGradient
)
from PyQt5.QtSvg import QSvgRenderer
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QProgressBar, QFrame, QSizePolicy, QSystemTrayIcon,
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

def apply_acrylic_glass(hwnd):
    """
    Apply native Windows 11 Acrylic blur behind window with true glass transparency
    and native DWM corner rounding (DWMWCP_ROUND = 2) so there are no square artifacts.
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

        # DWMWA_WINDOW_CORNER_PREFERENCE = 33, DWMWCP_ROUND = 2
        # Perfectly rounds the DWM acrylic backdrop to match Windows 11 (12px radius)
        val_corner = ctypes.c_int(2)
        dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(val_corner), 4)

        accent = ACCENT_POLICY()
        accent.AccentState = 4  # ACCENT_ENABLE_ACRYLICBLURBEHIND
        accent.AccentFlags = 2
        # Transparent acrylic blur with ultra-light dark tint (0x20 alpha)
        accent.GradientColor = 0x20101624
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
    "win_width": 350,
    "win_height": 450,
    "pos_x": None,
    "pos_y": None
}

def load_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
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
    font = QFont("Segoe UI Variable Display", 16, QFont.Bold)
    painter.setFont(font)
    painter.setPen(QColor(255, 255, 255))
    painter.drawText(QRectF(0, 1, size, size), Qt.AlignCenter, "AG")

    painter.end()
    return pixmap

# Helper to format countdown
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

# ----------------- HIGH-QUALITY VECTOR ICONS -----------------

SVG_GEMINI = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none">
<path d="M12 1.5C12 7.3 7.3 12 1.5 12C7.3 12 12 16.7 12 22.5C12 16.7 16.7 12 22.5 12C16.7 12 12 7.3 12 1.5Z" fill="url(#geminiGrad)" />
<defs>
<linearGradient id="geminiGrad" x1="1.5" y1="1.5" x2="22.5" y2="22.5" gradientUnits="userSpaceOnUse">
<stop offset="0%" stop-color="#38BDF8"/>
<stop offset="50%" stop-color="#818CF8"/>
<stop offset="100%" stop-color="#C084FC"/>
</linearGradient>
</defs>
</svg>"""

SVG_CLAUDE = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none">
<path d="M12 2L13.9 8.2L20.2 6.5L16.2 11.5L21.8 14L15.7 16.1L17.7 22.2L12 18.1L6.3 22.2L8.3 16.1L2.2 14L7.8 11.5L3.8 6.5L10.1 8.2L12 2Z" fill="url(#claudeGrad)"/>
<defs>
<linearGradient id="claudeGrad" x1="2" y1="2" x2="22" y2="22" gradientUnits="userSpaceOnUse">
<stop offset="0%" stop-color="#FB923C"/>
<stop offset="50%" stop-color="#F43F5E"/>
<stop offset="100%" stop-color="#E11D48"/>
</linearGradient>
</defs>
</svg>"""

SVG_CLOCK = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#94A3B8" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
<circle cx="12" cy="12" r="9"/>
<polyline points="12 7 12 12 15 14"/>
</svg>"""

SVG_CALENDAR = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#94A3B8" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
<rect width="18" height="18" x="3" y="4" rx="3.5"/>
<line x1="16" x2="16" y1="2" y2="5"/>
<line x1="8" x2="8" y1="2" y2="5"/>
<line x1="3" x2="21" y1="9" y2="9"/>
</svg>"""

SVG_PIN_ON = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#38BDF8" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
<line x1="12" x2="12" y1="17" y2="22"/>
<path d="M5 17h14v-1.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V6h1a2 2 0 0 0 0-4H8a2 2 0 0 0 0 4h1v4.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24Z"/>
</svg>"""

SVG_PIN_OFF = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#CBD5E1" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
<line x1="2" x2="22" y1="2" y2="22"/>
<path d="M9 9v1.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V17h12"/>
<path d="M15 9.34V6h1a2 2 0 0 0 0-4H7.89"/>
<line x1="12" x2="12" y1="17" y2="22"/>
</svg>"""

SVG_CLOSE = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#CBD5E1" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
<line x1="18" y1="6" x2="6" y2="18"/>
<line x1="6" y1="6" x2="18" y2="18"/>
</svg>"""

SVG_REFRESH = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#CBD5E1" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
<path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8"/>
<path d="M21 3v5h-5"/>
</svg>"""

SVG_EXTERNAL = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#CBD5E1" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
<path d="M15 3h6v6"/>
<path d="M10 14 21 3"/>
<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>
</svg>"""

def render_svg_to_pixmap(svg_str, width, height):
    renderer = QSvgRenderer(QByteArray(svg_str.encode('utf-8')))
    pix = QPixmap(int(width), int(height))
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    renderer.render(p)
    p.end()
    return pix

# ----------------- GLASS-STYLE ICON & MEDALLION RENDERERS -----------------

def create_glass_brand_medallion(svg_str, size=30, icon_size=17, glow_color="#38bdf8"):
    size = max(14, int(size))
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)

    rect = QRectF(1.0, 1.0, size - 2.0, size - 2.0)
    radius = (size - 2.0) / 2.0

    # Backlight ambient glow
    glow = QColor(glow_color)
    glow.setAlpha(35)
    p.setPen(Qt.NoPen)
    p.setBrush(glow)
    p.drawRoundedRect(rect, radius, radius)

    # Frosted glass background
    bg_grad = QLinearGradient(0, 0, 0, size)
    bg_grad.setColorAt(0.0, QColor(255, 255, 255, 32))
    bg_grad.setColorAt(1.0, QColor(255, 255, 255, 8))
    p.setBrush(bg_grad)
    p.drawRoundedRect(rect, radius, radius)

    # Top specular reflection highlight
    shine = QLinearGradient(0, 0, 0, size * 0.55)
    shine.setColorAt(0.0, QColor(255, 255, 255, 60))
    shine.setColorAt(1.0, QColor(255, 255, 255, 0))
    p.setBrush(shine)
    p.drawRoundedRect(rect, radius, radius)

    # Glass rim border
    rim_grad = QLinearGradient(0, 0, 0, size)
    rim_grad.setColorAt(0.0, QColor(255, 255, 255, 110))
    rim_grad.setColorAt(0.5, QColor(255, 255, 255, 30))
    rim_grad.setColorAt(1.0, QColor(255, 255, 255, 15))
    p.setPen(QPen(rim_grad, 1.0))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(rect, radius, radius)

    # Render inner SVG glyph
    offset = (size - icon_size) / 2.0
    renderer = QSvgRenderer(QByteArray(svg_str.encode('utf-8')))
    renderer.render(p, QRectF(offset, offset, icon_size, icon_size))

    p.end()
    return pix

def create_glass_icon_pixmap(svg_str, size=32, inner_size=16, is_hover=False, is_active=False):
    size = max(16, int(size))
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)

    rect = QRectF(1.0, 1.0, size - 2.0, size - 2.0)
    radius = (size - 2.0) / 2.0

    if is_active:
        bg_color = QColor(56, 189, 248, 55)
        border_top = QColor(56, 189, 248, 160)
        border_bot = QColor(56, 189, 248, 60)
    elif is_hover:
        bg_color = QColor(255, 255, 255, 38)
        border_top = QColor(255, 255, 255, 120)
        border_bot = QColor(255, 255, 255, 35)
    else:
        bg_color = QColor(255, 255, 255, 16)
        border_top = QColor(255, 255, 255, 65)
        border_bot = QColor(255, 255, 255, 18)

    p.setPen(Qt.NoPen)
    p.setBrush(bg_color)
    p.drawRoundedRect(rect, radius, radius)

    grad_shine = QLinearGradient(0, 0, 0, size * 0.6)
    grad_shine.setColorAt(0.0, QColor(255, 255, 255, 45 if not is_hover else 75))
    grad_shine.setColorAt(1.0, QColor(255, 255, 255, 0))
    p.setBrush(grad_shine)
    p.drawRoundedRect(rect, radius, radius)

    grad_border = QLinearGradient(0, 0, 0, size)
    grad_border.setColorAt(0.0, border_top)
    grad_border.setColorAt(1.0, border_bot)
    pen = QPen(grad_border, 1.0)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(rect, radius, radius)

    offset = (size - inner_size) / 2.0
    renderer = QSvgRenderer(QByteArray(svg_str.encode('utf-8')))
    renderer.render(p, QRectF(offset, offset, inner_size, inner_size))

    p.end()
    return pix

def create_antigravity_glass_logo(size=32):
    size = max(16, int(size))
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)

    rect = QRectF(1.0, 1.0, size - 2.0, size - 2.0)
    radius = (size - 2.0) / 2.0

    grad_bg = QLinearGradient(0, 0, size, size)
    grad_bg.setColorAt(0.0, QColor(56, 189, 248, 50))
    grad_bg.setColorAt(0.7, QColor(99, 102, 241, 35))
    grad_bg.setColorAt(1.0, QColor(168, 85, 247, 20))
    p.setPen(Qt.NoPen)
    p.setBrush(grad_bg)
    p.drawRoundedRect(rect, radius, radius)

    grad_shine = QLinearGradient(0, 0, 0, size * 0.55)
    grad_shine.setColorAt(0.0, QColor(255, 255, 255, 60))
    grad_shine.setColorAt(1.0, QColor(255, 255, 255, 0))
    p.setBrush(grad_shine)
    p.drawRoundedRect(rect, radius, radius)

    pen_rim = QPen(QColor(255, 255, 255, 90), 1.0)
    p.setPen(pen_rim)
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(rect, radius, radius)

    cx, cy = size / 2.0, size / 2.0
    scale_f = size / 32.0
    pen_glyph = QPen(QColor(255, 255, 255, 250), max(1.0, 1.8 * scale_f))
    pen_glyph.setCapStyle(Qt.RoundCap)
    pen_glyph.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen_glyph)

    path = QPainterPath()
    path.moveTo(cx, cy + 6.8 * scale_f)
    path.lineTo(cx - 6.2 * scale_f, cy - 4.2 * scale_f)
    path.lineTo(cx + 6.2 * scale_f, cy - 4.2 * scale_f)
    path.closeSubpath()
    p.drawPath(path)

    p.setPen(Qt.NoPen)
    p.setBrush(QColor(56, 189, 248, 255))
    p.drawEllipse(QPointF(cx, cy - 0.5 * scale_f), 2.2 * scale_f, 2.2 * scale_f)

    p.end()
    return pix

# ----------------- CUSTOM GLASS BUTTON -----------------

class GlassButton(QPushButton):
    def __init__(self, svg_str, size=30, inner_size=15, is_active=False, parent=None):
        super().__init__(parent)
        self.svg_str = svg_str
        self.btn_size = int(size)
        self.inner_size = int(inner_size)
        self.is_active = is_active
        self.setFixedSize(self.btn_size, self.btn_size)
        self.setCursor(Qt.PointingHandCursor)
        self.update_icons()

    def set_svg(self, svg_str, is_active=False):
        self.svg_str = svg_str
        self.is_active = is_active
        self.update_icons()

    def set_button_size(self, size, inner_size):
        self.btn_size = int(size)
        self.inner_size = int(inner_size)
        self.setFixedSize(self.btn_size, self.btn_size)
        self.update_icons()

    def update_icons(self):
        icon = QIcon()
        pix_normal = create_glass_icon_pixmap(self.svg_str, self.btn_size, self.inner_size, False, self.is_active)
        pix_hover = create_glass_icon_pixmap(self.svg_str, self.btn_size, self.inner_size, True, self.is_active)
        icon.addPixmap(pix_normal, QIcon.Normal)
        icon.addPixmap(pix_hover, QIcon.Active)
        self.setIcon(icon)
        self.setIconSize(QSize(self.btn_size, self.btn_size))
        self.setStyleSheet("QPushButton { background: transparent; border: none; padding: 0px; }")

# ----------------- ADAPTIVE NON-SCROLLING GLASS QUOTA CARD -----------------

class AdaptiveGlassQuotaCard(QFrame):
    def __init__(self, group_name, badge_text, brand_svg, accent_color="#38bdf8", parent=None):
        super().__init__(parent)
        self.brand_svg = brand_svg
        self.accent_color = accent_color
        self.setObjectName("adaptiveGlassCard")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.set_card_style(14)

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(14, 10, 14, 10)
        self.layout.setSpacing(4)

        # Header Row: [Glass Medallion] Title      [Glass Badge]
        self.hdr = QHBoxLayout()
        self.hdr.setSpacing(6)

        self.brand_icon = QLabel()
        self.brand_icon.setFixedSize(26, 26)
        self.brand_icon.setPixmap(create_glass_brand_medallion(brand_svg, 26, 15, accent_color))
        self.hdr.addWidget(self.brand_icon)

        self.title = QLabel(group_name)
        self.title.setFont(QFont("Segoe UI Variable Display", 11, QFont.Bold))
        self.title.setStyleSheet("color: #ffffff;")
        self.hdr.addWidget(self.title)

        self.hdr.addStretch()

        self.badge = QLabel(badge_text)
        self.set_badge_style(2, 7, 8, 8)
        self.hdr.addWidget(self.badge)
        self.layout.addLayout(self.hdr)

        # 5h Metric Row
        self.r_5h = QHBoxLayout()
        self.r_5h.setSpacing(5)

        self.icon_5h = QLabel()
        self.icon_5h.setFixedSize(13, 13)
        self.icon_5h.setPixmap(render_svg_to_pixmap(SVG_CLOCK, 13, 13))
        self.r_5h.addWidget(self.icon_5h)

        self.lbl_5h = QLabel("5h Window")
        self.lbl_5h.setFont(QFont("Segoe UI Variable Text", 9, QFont.DemiBold))
        self.lbl_5h.setStyleSheet("color: rgba(255, 255, 255, 0.85);")
        self.r_5h.addWidget(self.lbl_5h)

        self.time_5h_inline = QLabel("Loading...")
        self.time_5h_inline.setFont(QFont("Segoe UI Variable Small", 8))
        self.time_5h_inline.setStyleSheet("color: rgba(255, 255, 255, 0.45);")
        self.r_5h.addWidget(self.time_5h_inline)

        self.r_5h.addStretch()

        self.val_5h = QLabel("--%")
        self.val_5h.setFont(QFont("Segoe UI Variable Display", 11, QFont.Bold))
        self.val_5h.setStyleSheet("color: #34d399;")
        self.r_5h.addWidget(self.val_5h)
        self.layout.addLayout(self.r_5h)

        # 5h Progress Bar
        self.bar_5h = QProgressBar()
        self.bar_5h.setFixedHeight(4)
        self.bar_5h.setTextVisible(False)
        self.bar_5h.setValue(100)
        self.set_neon_bar(self.bar_5h, 1.0)
        self.layout.addWidget(self.bar_5h)

        # 5h separate time label (visible in spacious mode)
        self.time_5h_bottom = QLabel("Loading...")
        self.time_5h_bottom.setFont(QFont("Segoe UI Variable Small", 8))
        self.time_5h_bottom.setStyleSheet("color: rgba(255, 255, 255, 0.45); margin-left: 2px;")
        self.layout.addWidget(self.time_5h_bottom)

        # Weekly Metric Row
        self.r_wk = QHBoxLayout()
        self.r_wk.setSpacing(5)

        self.icon_wk = QLabel()
        self.icon_wk.setFixedSize(13, 13)
        self.icon_wk.setPixmap(render_svg_to_pixmap(SVG_CALENDAR, 13, 13))
        self.r_wk.addWidget(self.icon_wk)

        self.lbl_wk = QLabel("Weekly Limit")
        self.lbl_wk.setFont(QFont("Segoe UI Variable Text", 9, QFont.DemiBold))
        self.lbl_wk.setStyleSheet("color: rgba(255, 255, 255, 0.85);")
        self.r_wk.addWidget(self.lbl_wk)

        self.time_wk_inline = QLabel("Loading...")
        self.time_wk_inline.setFont(QFont("Segoe UI Variable Small", 8))
        self.time_wk_inline.setStyleSheet("color: rgba(255, 255, 255, 0.45);")
        self.r_wk.addWidget(self.time_wk_inline)

        self.r_wk.addStretch()

        self.val_wk = QLabel("--%")
        self.val_wk.setFont(QFont("Segoe UI Variable Display", 11, QFont.Bold))
        self.val_wk.setStyleSheet("color: #34d399;")
        self.r_wk.addWidget(self.val_wk)
        self.layout.addLayout(self.r_wk)

        # Weekly Progress Bar
        self.bar_wk = QProgressBar()
        self.bar_wk.setFixedHeight(4)
        self.bar_wk.setTextVisible(False)
        self.bar_wk.setValue(100)
        self.set_neon_bar(self.bar_wk, 1.0)
        self.layout.addWidget(self.bar_wk)

        # Weekly separate time label
        self.time_wk_bottom = QLabel("Loading...")
        self.time_wk_bottom.setFont(QFont("Segoe UI Variable Small", 8))
        self.time_wk_bottom.setStyleSheet("color: rgba(255, 255, 255, 0.45); margin-left: 2px;")
        self.layout.addWidget(self.time_wk_bottom)

        self.bucket_5h_reset = None
        self.bucket_wk_reset = None

    def set_card_style(self, radius):
        self.setStyleSheet(f"""
            #adaptiveGlassCard {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 rgba(255, 255, 255, 0.08), 
                    stop:0.1 rgba(255, 255, 255, 0.02), 
                    stop:1 rgba(0, 0, 0, 0.22));
                border: 1px solid rgba(255, 255, 255, 0.09);
                border-top: 1px solid rgba(255, 255, 255, 0.24);
                border-radius: {radius}px;
            }}
        """)

    def set_badge_style(self, pad_v, pad_h, radius, font_pt):
        self.badge.setFont(QFont("Segoe UI Variable Small", font_pt, QFont.Bold))
        self.badge.setStyleSheet(f"""
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                stop:0 rgba(255, 255, 255, 0.09), 
                stop:1 rgba(255, 255, 255, 0.03));
            color: {self.accent_color};
            border: 1px solid rgba(255, 255, 255, 0.12);
            border-top: 1px solid rgba(255, 255, 255, 0.25);
            padding: {pad_v}px {pad_h}px;
            border-radius: {radius}px;
        """)

    def set_neon_bar(self, bar, frac):
        if frac > 0.5:
            grad = "qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #059669, stop:0.5 #10b981, stop:1 #34d399)"
        elif frac > 0.2:
            grad = "qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #d97706, stop:0.5 #f59e0b, stop:1 #fbbf24)"
        else:
            grad = "qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #dc2626, stop:0.5 #ef4444, stop:1 #f87171)"

        bar.setStyleSheet(f"""
            QProgressBar {{
                background: rgba(0, 0, 0, 0.35);
                border: 1px solid rgba(255, 255, 255, 0.06);
                border-radius: 2px;
            }}
            QProgressBar::chunk {{
                background: {grad};
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
            self.set_neon_bar(self.bar_5h, frac)
            self.bucket_5h_reset = b_5h.get("reset_time")
            t_str = format_ref_countdown(self.bucket_5h_reset)
            self.time_5h_inline.setText(t_str)
            self.time_5h_bottom.setText(t_str)

        if b_wk:
            frac = b_wk.get("remaining_fraction", 1.0)
            pct = int(round(frac * 100))
            self.val_wk.setText(f"{pct}%")
            self.bar_wk.setValue(pct)
            color = "#34d399" if frac > 0.5 else ("#fbbf24" if frac > 0.2 else "#f87171")
            self.val_wk.setStyleSheet(f"color: {color}; font-weight: bold;")
            self.set_neon_bar(self.bar_wk, frac)
            self.bucket_wk_reset = b_wk.get("reset_time")
            t_str = format_ref_countdown(self.bucket_wk_reset)
            self.time_wk_inline.setText(t_str)
            self.time_wk_bottom.setText(t_str)

    def tick_second(self):
        if self.bucket_5h_reset:
            t_str = format_ref_countdown(self.bucket_5h_reset)
            self.time_5h_inline.setText(t_str)
            self.time_5h_bottom.setText(t_str)
        if self.bucket_wk_reset:
            t_str = format_ref_countdown(self.bucket_wk_reset)
            self.time_wk_inline.setText(t_str)
            self.time_wk_bottom.setText(t_str)

    def update_scaling(self, scale, win_h):
        pad_h = max(6, int(14 * scale))
        pad_v = max(3, int(10 * scale))
        spacing = max(2, int(4 * scale))
        self.layout.setContentsMargins(pad_h, pad_v, pad_h, pad_v)
        self.layout.setSpacing(spacing)

        card_radius = max(8, int(14 * scale))
        self.set_card_style(card_radius)

        # Brand medallion
        med_sz = max(16, int(26 * scale))
        in_sz = max(9, int(15 * scale))
        self.brand_icon.setFixedSize(med_sz, med_sz)
        self.brand_icon.setPixmap(create_glass_brand_medallion(self.brand_svg, med_sz, in_sz, self.accent_color))

        # Title
        t_pt = max(7, int(11 * scale))
        self.title.setFont(QFont("Segoe UI Variable Display", t_pt, QFont.Bold))

        # Badge
        b_pad_v = max(1, int(2 * scale))
        b_pad_h = max(3, int(7 * scale))
        b_rad = max(5, int(8 * scale))
        b_pt = max(6, int(8 * scale))
        self.set_badge_style(b_pad_v, b_pad_h, b_rad, b_pt)

        # Metric icons
        icon_sz = max(9, int(13 * scale))
        self.icon_5h.setFixedSize(icon_sz, icon_sz)
        self.icon_5h.setPixmap(render_svg_to_pixmap(SVG_CLOCK, icon_sz, icon_sz))
        self.icon_wk.setFixedSize(icon_sz, icon_sz)
        self.icon_wk.setPixmap(render_svg_to_pixmap(SVG_CALENDAR, icon_sz, icon_sz))

        # Metric labels & values
        lbl_pt = max(6, int(9 * scale))
        val_pt = max(7, int(11 * scale))
        self.lbl_5h.setFont(QFont("Segoe UI Variable Text", lbl_pt, QFont.DemiBold))
        self.lbl_wk.setFont(QFont("Segoe UI Variable Text", lbl_pt, QFont.DemiBold))
        self.val_5h.setFont(QFont("Segoe UI Variable Display", val_pt, QFont.Bold))
        self.val_wk.setFont(QFont("Segoe UI Variable Display", val_pt, QFont.Bold))

        # Adaptive time display:
        # If height >= 380px: Show spacious layout with time under the bar
        # If height < 380px: Show inline time right next to "5h Window", saving full rows so window can shrink!
        time_pt = max(5, int(8 * scale))
        self.time_5h_inline.setFont(QFont("Segoe UI Variable Small", time_pt))
        self.time_5h_bottom.setFont(QFont("Segoe UI Variable Small", time_pt))
        self.time_wk_inline.setFont(QFont("Segoe UI Variable Small", time_pt))
        self.time_wk_bottom.setFont(QFont("Segoe UI Variable Small", time_pt))

        if win_h >= 380:
            self.time_5h_inline.setVisible(False)
            self.time_wk_inline.setVisible(False)
            self.time_5h_bottom.setVisible(True)
            self.time_wk_bottom.setVisible(True)
        else:
            self.time_5h_inline.setVisible(True)
            self.time_wk_inline.setVisible(True)
            self.time_5h_bottom.setVisible(False)
            self.time_wk_bottom.setVisible(False)

        # Progress bars
        bar_h = max(2, int(4 * scale))
        self.bar_5h.setFixedHeight(bar_h)
        self.bar_wk.setFixedHeight(bar_h)

# ----------------- MAIN GLASS FLOATING WINDOW (ZERO SCROLLING) -----------------

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

        w = max(180, self.config.get("win_width", 350))
        h = max(200, self.config.get("win_height", 450))
        self.resize(w, h)
        # Allows user to freely shrink to micro-widget (e.g. 180x210) without scrollbar!
        self.setMinimumSize(170, 190)

        # Initial position clamped to visible screen workspace
        screen = QApplication.primaryScreen().availableGeometry()
        if self.config.get("pos_x") is not None and self.config.get("pos_y") is not None:
            px = max(screen.left() + 10, min(screen.right() - w - 10, self.config["pos_x"]))
            py = max(screen.top() + 10, min(screen.bottom() - h - 10, self.config["pos_y"]))
            self.move(px, py)
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
        self.main_layout.setContentsMargins(12, 10, 12, 10)
        self.main_layout.setSpacing(6)

        # 1. Header Bar: [Logo Orb]   Antigravity Quota   [Glass Pin] [Glass Close]
        self.hdr = QHBoxLayout()
        self.hdr.setSpacing(6)

        # Glass Logo Orb
        self.logo_lbl = QLabel()
        self.logo_lbl.setPixmap(create_antigravity_glass_logo(size=28))
        self.hdr.addWidget(self.logo_lbl)

        self.title_lbl = QLabel("Antigravity Quota")
        self.title_lbl.setFont(QFont("Segoe UI Variable Display", 11, QFont.Bold))
        self.title_lbl.setStyleSheet("color: #ffffff;")
        self.hdr.addWidget(self.title_lbl)

        self.hdr.addStretch()

        # Glass Pin Button
        pin_svg = SVG_PIN_ON if self.is_pinned else SVG_PIN_OFF
        self.btn_pin = GlassButton(pin_svg, size=28, inner_size=14, is_active=self.is_pinned)
        self.btn_pin.setToolTip("Pin window (keep visible)")
        self.btn_pin.clicked.connect(self.toggle_pin)
        self.hdr.addWidget(self.btn_pin)

        # Glass Close Button
        self.btn_close = GlassButton(SVG_CLOSE, size=28, inner_size=13)
        self.btn_close.setToolTip("Close to system tray")
        self.btn_close.clicked.connect(self.hide)
        self.hdr.addWidget(self.btn_close)

        self.main_layout.addLayout(self.hdr)

        # 2. CARDS DIRECTLY IN MAIN LAYOUT - ABSOLUTELY ZERO SCROLLING!
        # Both Gemini and Claude cards always fit and scale fluidly to the window
        self.card_gemini = AdaptiveGlassQuotaCard("Gemini Models", "FLASH & PRO", SVG_GEMINI, "#38bdf8", self)
        self.main_layout.addWidget(self.card_gemini)

        self.card_claude = AdaptiveGlassQuotaCard("Claude & GPT", "OPUS & SONNET", SVG_CLAUDE, "#fb923c", self)
        self.main_layout.addWidget(self.card_claude)

        # 3. Footer Bar: [● Live synchronized]      [Refresh] [External]
        self.footer = QHBoxLayout()
        self.footer.setContentsMargins(2, 0, 2, 0)
        self.footer.setSpacing(6)

        self.live_dot = QLabel("●")
        self.live_dot.setStyleSheet("color: #34d399; font-size: 10px;")
        self.footer.addWidget(self.live_dot)

        self.lbl_status = QLabel("Live synchronized")
        self.lbl_status.setFont(QFont("Segoe UI Variable Text", 8, QFont.Medium))
        self.lbl_status.setStyleSheet("color: rgba(255, 255, 255, 0.45);")
        self.footer.addWidget(self.lbl_status)

        self.footer.addStretch()

        # Glass Refresh Button
        self.btn_refresh = GlassButton(SVG_REFRESH, size=28, inner_size=14)
        self.btn_refresh.setToolTip("Refresh quotas now")
        self.btn_refresh.clicked.connect(self.app_manager.trigger_refresh)
        self.footer.addWidget(self.btn_refresh)

        # Glass External Link Button
        self.btn_ext = GlassButton(SVG_EXTERNAL, size=28, inner_size=14)
        self.btn_ext.setToolTip("Open GitHub Repository")
        self.btn_ext.clicked.connect(self.open_repo)
        self.footer.addWidget(self.btn_ext)

        self.main_layout.addLayout(self.footer)

    def open_repo(self):
        webbrowser.open("https://github.com/I-N-O-A/antigravity-quota-monitor")

    def toggle_pin(self):
        self.is_pinned = not self.is_pinned
        self.btn_pin.set_svg(SVG_PIN_ON if self.is_pinned else SVG_PIN_OFF, is_active=self.is_pinned)
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
        # Radius 12.0 perfectly matches Windows 11 DWMWCP_ROUND (2)
        path.addRoundedRect(rect, 12.0, 12.0)

        # 1. Dark glass tint: alpha 45 gives high-end smoked glass contrast with acrylic blur
        painter.fillPath(path, QColor(14, 20, 32, 45))

        # 2. Specular glass reflection gradient at top edge
        grad = QLinearGradient(0, 0, 0, min(100, int(self.height() * 0.4)))
        grad.setColorAt(0.0, QColor(255, 255, 255, 28))
        grad.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.fillPath(path, grad)

        # 3. Delicate glass border highlight
        grad_border = QLinearGradient(0, 0, 0, self.height())
        grad_border.setColorAt(0.0, QColor(255, 255, 255, 60))
        grad_border.setColorAt(0.5, QColor(255, 255, 255, 25))
        grad_border.setColorAt(1.0, QColor(255, 255, 255, 12))
        pen = QPen(grad_border, 1.0)
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

            # 4 Corners (Native cursor feedback and resizing)
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

            # Top header bar (Drag to move, excluding buttons)
            header_h = min(40, max(24, int(h * 0.14)))
            btn_clearance = min(75, max(45, int(w * 0.28)))
            if p.y() <= header_h and p.x() < (w - btn_clearance):
                return True, 2   # HTCAPTION

        return super().nativeEvent(eventType, message)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        w = self.width()
        h = self.height()
        self.config["win_width"] = w
        self.config["win_height"] = h
        save_config(self.config)

        # Fluid responsive scaling based on dimensions
        w_factor = w / 350.0
        h_factor = h / 450.0
        factor = min(w_factor, h_factor)
        scale = max(0.45, min(1.15, factor))

        m_h = max(6, int(12 * scale))
        m_v = max(3, int(10 * scale))
        sp = max(2, int(6 * scale))
        self.main_layout.setContentsMargins(m_h, m_v, m_h, m_v)
        self.main_layout.setSpacing(sp)

        # Header elements scaling
        logo_sz = max(16, int(28 * scale))
        self.logo_lbl.setPixmap(create_antigravity_glass_logo(logo_sz))

        t_pt = max(7, int(11 * scale))
        self.title_lbl.setFont(QFont("Segoe UI Variable Display", t_pt, QFont.Bold))

        btn_sz = max(18, int(28 * scale))
        btn_inner = max(9, int(14 * scale))
        self.btn_pin.set_button_size(btn_sz, btn_inner)
        self.btn_close.set_button_size(btn_sz, btn_inner)
        self.btn_refresh.set_button_size(btn_sz, btn_inner)
        self.btn_ext.set_button_size(btn_sz, btn_inner)

        status_pt = max(6, int(8 * scale))
        self.lbl_status.setFont(QFont("Segoe UI Variable Text", status_pt, QFont.Medium))

        # Cards scaling
        self.card_gemini.update_scaling(scale, h)
        self.card_claude.update_scaling(scale, h)

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

# ----------------- APPLICATION CONTROLLER -----------------

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

        # Create Glass Window
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
        if reason == QSystemTrayIcon.Trigger:  # Left click
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
        apply_acrylic_glass(int(self.window.winId()))
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

# ----------------- SINGLE INSTANCE -----------------

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
