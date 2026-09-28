"""
Antigravity Quota Monitor - Windows System Tray Utility
Monitors API limits and usage for Gemini and Claude/GPT model groups in real-time.
Features floating, multi-border resizable glassmorphic window, real-time second-by-second countdowns,
Windows 11 acrylic styling, anti-aliased rounded corners, and centered tray icon.
"""

import os
import sys

APP_DIR = os.path.dirname(os.path.abspath(__file__))

# Under pythonw.exe on Windows, sys.stdout and sys.stderr are None.
# Redirect them so print() or library errors never crash the application.
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
import threading
from ctypes import wintypes
import queue
import winreg
from datetime import datetime, timezone
import subprocess
import tkinter as tk
from PIL import Image, ImageDraw, ImageFont
import pystray
from pystray import MenuItem as item, Menu

# Attach thread to interactive user desktop
def ensure_default_desktop():
    try:
        user32 = ctypes.windll.user32
        hDesk = user32.OpenDesktopW("Default", 0, False, 0x01FF)
        if hDesk:
            user32.SetThreadDesktop(hDesk)
            orig_run = threading.Thread.run
            def desktop_thread_run(self):
                try:
                    user32.SetThreadDesktop(hDesk)
                except Exception:
                    pass
                return orig_run(self)
            threading.Thread.run = desktop_thread_run
    except Exception:
        pass

ensure_default_desktop()

# DPI Awareness for crisp rendering on Windows High-DPI screens
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

# Paths & Settings
CONFIG_PATH = os.path.join(APP_DIR, "config.json")
REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
REG_NAME = "AntigravityQuotaTray"
MUTEX_NAME = "AntigravityQuotaTray_SingleInstance_Mutex"
_mutex_handle = None

DEFAULT_CONFIG = {
    "background_refresh_seconds": 60,
    "live_refresh_seconds": 10,
    "pinned": False,
    "theme": "dark",
    "win_width": 390,
    "win_height": 520,
    "custom_pos": False,
    "pos_x": None,
    "pos_y": None
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

# Work Area helper for screen positioning
class RECT(ctypes.Structure):
    _fields_ = [
        ('left', wintypes.LONG),
        ('top', wintypes.LONG),
        ('right', wintypes.LONG),
        ('bottom', wintypes.LONG),
    ]

def get_work_area():
    SPI_GETWORKAREA = 0x0030
    rect = RECT()
    ctypes.windll.user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0)
    return rect.left, rect.top, rect.right, rect.bottom

# Windows 11 DWM Styling: Dark Mode & Acrylic Backdrop
def apply_dwm_styling(root):
    try:
        root.update_idletasks()
        hwnd = root.winfo_id()
        top_hwnd = ctypes.windll.user32.GetParent(hwnd) or hwnd
        
        # 1. Dark Mode
        val_dark = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            top_hwnd, 20, ctypes.byref(val_dark), ctypes.sizeof(val_dark)
        )
        # 2. Rounded Corners (DWMWCP_ROUND = 2)
        val_round = ctypes.c_int(2)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            top_hwnd, 33, ctypes.byref(val_round), ctypes.sizeof(val_round)
        )
        # 3. Acrylic / Mica backdrop
        val_acrylic = ctypes.c_int(3)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            top_hwnd, 38, ctypes.byref(val_acrylic), ctypes.sizeof(val_acrylic)
        )
    except Exception:
        pass

# Autostart Helpers
def is_autostart_enabled():
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_READ)
        val, _ = winreg.QueryValueEx(key, REG_NAME)
        winreg.CloseKey(key)
        return bool(val)
    except FileNotFoundError:
        return False
    except Exception:
        return False

def set_autostart(enable: bool):
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_SET_VALUE)
        if enable:
            vbs_path = os.path.join(APP_DIR, "start_silent.vbs")
            if os.path.exists(vbs_path):
                cmd = f'wscript.exe "{vbs_path}"'
            else:
                pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
                if not os.path.exists(pythonw):
                    pythonw = sys.executable
                script_path = os.path.abspath(__file__)
                cmd = f'"{pythonw}" "{script_path}"'
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

# Ensure Tray Icon is Promoted (Visible on Taskbar in Windows 11)
def ensure_promoted_in_tray():
    try:
        base_key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\NotifyIconSettings", 0, winreg.KEY_READ | winreg.KEY_WRITE)
        i = 0
        while True:
            try:
                subkey_name = winreg.EnumKey(base_key, i)
                i += 1
                subkey = winreg.OpenKey(base_key, subkey_name, 0, winreg.KEY_READ | winreg.KEY_WRITE)
                try:
                    exe_val, _ = winreg.QueryValueEx(subkey, "ExecutablePath")
                    if any(p in exe_val.lower() for p in ("python", "agy_tray")):
                        winreg.SetValueEx(subkey, "IsPromoted", 0, winreg.REG_DWORD, 1)
                except Exception:
                    pass
                finally:
                    winreg.CloseKey(subkey)
            except OSError:
                break
        winreg.CloseKey(base_key)
    except Exception:
        pass

# Locate agy.exe
def get_agy_path():
    path = shutil.which("agy")
    if path and os.path.exists(path):
        return path
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    candidate = os.path.join(local_app_data, "agy", "bin", "agy.exe")
    if os.path.exists(candidate):
        return candidate
    candidate2 = os.path.expanduser(r"~\AppData\Local\agy\bin\agy.exe")
    if os.path.exists(candidate2):
        return candidate2
    return "agy"

# Data Fetcher
def fetch_usage_data():
    agy_path = get_agy_path()
    creationflags = 0
    startupinfo = None
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NO_WINDOW
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0
    
    try:
        proc = subprocess.run(
            [agy_path, "-p", "/usage", "--output-format", "json"],
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=creationflags,
            startupinfo=startupinfo
        )
        if proc.returncode != 0:
            return None, f"Exit-Code {proc.returncode}: {proc.stderr.strip() or 'Fehler beim Abruf'}"
        
        stdout = proc.stdout.strip()
        s_idx = stdout.find("{")
        e_idx = stdout.rfind("}")
        if s_idx != -1 and e_idx != -1:
            data = json.loads(stdout[s_idx:e_idx+1])
        else:
            data = json.loads(stdout)
            
        cmd_data = data.get("command", {}).get("data", {})
        return cmd_data, None
    except subprocess.TimeoutExpired:
        return None, "Zeitüberschreitung beim Abruf der Daten"
    except Exception as e:
        return None, str(e)

def format_countdown_seconds(target_dt, fraction=1.0):
    if not target_dt:
        return "Reset: --"
    try:
        now_dt = datetime.now(timezone.utc)
        diff = int((target_dt - now_dt).total_seconds())
        if diff <= 0:
            if fraction >= 0.999:
                return "100% bereit"
            return "Reset fällig • lädt nach"
        
        days = diff // 86400
        rem = diff % 86400
        hours = rem // 3600
        mins = (rem % 3600) // 60
        secs = rem % 60
        
        if days > 0:
            return f"Reset in {days}T {hours}Std"
        elif hours > 0:
            return f"Reset in {hours}h {mins:02d}m {secs:02d}s"
        elif mins > 0:
            return f"Reset in {mins}m {secs:02d}s"
        else:
            return f"Reset in {secs}s"
    except Exception:
        return "Reset: --"

def get_color_for_fraction(fraction):
    if fraction >= 0.50:
        return "#10b981"  # Emerald Green
    elif fraction >= 0.20:
        return "#f59e0b"  # Amber Orange
    else:
        return "#ef4444"  # Rose Red

# Modern Windows 11 Tray Icon Generator (Supersampled & Mathematically Centered)
def create_tray_image(min_fraction=1.0):
    canvas_size = 256
    img = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    pad = 12
    draw.ellipse(
        (pad, pad, canvas_size - pad, canvas_size - pad),
        fill=(18, 24, 38, 255),
        outline=(55, 65, 81, 255),
        width=4
    )
    
    track_pad = 24
    draw.ellipse(
        (track_pad, track_pad, canvas_size - track_pad, canvas_size - track_pad),
        outline=(40, 50, 68, 255),
        width=18
    )
    
    sweep = max(18, int(min_fraction * 360))
    if min_fraction >= 0.50:
        color = (16, 185, 129, 255)
    elif min_fraction >= 0.20:
        color = (245, 158, 11, 255)
    else:
        color = (239, 68, 68, 255)
        
    draw.arc(
        (track_pad, track_pad, canvas_size - track_pad, canvas_size - track_pad),
        start=-90,
        end=-90 + sweep,
        fill=color,
        width=18
    )
    
    try:
        font = ImageFont.truetype("segoeuib.ttf", 92)
    except Exception:
        font = ImageFont.load_default()
        
    bbox = draw.textbbox((0, 0), "AG", font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    tx = (canvas_size - tw) / 2.0 - bbox[0]
    ty = (canvas_size - th) / 2.0 - bbox[1]
    draw.text((tx, ty), "AG", fill=(255, 255, 255, 255), font=font)
    
    return img.resize((64, 64), Image.Resampling.LANCZOS)

# QuotaApp with True Canvas-based Glassmorphism UI
TRANSPARENT_KEY = "#010203"

class QuotaApp:
    def __init__(self):
        self.config = load_config()
        self.latest_data = None
        self.is_fetching = False
        self.last_successful_fetch = 0
        self.last_fetch_start = 0
        self.pinned = self.config.get("pinned", False)
        self.msg_queue = queue.Queue()
        
        # Reset target cache for live 1-second countdowns
        self.bucket_reset_targets = {}
        
        # Window & Interaction State
        self.is_open = False
        self.open_timestamp = 0
        self.last_hide_time = 0
        self.last_interaction_time = 0
        self.mouse_is_down_inside = False
        
        self.is_dragging = False
        self.drag_start_x = 0
        self.drag_start_y = 0
        self.win_start_x = 0
        self.win_start_y = 0
        
        self.is_resizing = False
        self.resize_direction = ""
        self.resize_start_x = 0
        self.resize_start_y = 0
        self.resize_start_win_x = 0
        self.resize_start_win_y = 0
        self.resize_start_w = 0
        self.resize_start_h = 0
        
        self.win_width = max(310, min(900, self.config.get("win_width", 390)))
        self.win_height = max(360, min(1000, self.config.get("win_height", 520)))
        
        # Tkinter Root Setup
        self.root = tk.Tk()
        self.root.title("Antigravity Quota")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        
        # Windows transparent colorkey for smooth anti-aliased rounded glass curves
        try:
            self.root.wm_attributes("-transparentcolor", TRANSPARENT_KEY)
        except Exception:
            pass
        self.root.configure(bg=TRANSPARENT_KEY)
        
        ico_path = os.path.join(APP_DIR, "icon.ico")
        if os.path.exists(ico_path):
            try:
                self.root.iconbitmap(ico_path)
            except Exception:
                pass
        
        # Main Canvas for high-performance Glassmorphic drawing
        self.canvas = tk.Canvas(
            self.root,
            width=self.win_width,
            height=self.win_height,
            bg=TRANSPARENT_KEY,
            highlightthickness=0,
            bd=0
        )
        self.canvas.pack(fill="both", expand=True)
        
        self.setup_resize_borders()
        self.bind_events()
        
        # Initial glass render
        self.render_glass_ui()
        
        # Start queue poller
        self._process_queue()
        
        # Tray Icon setup
        self.tray_icon = None
        self.init_tray_icon()
        
        # Promote icon in Windows 11 taskbar
        self.root.after(1000, ensure_promoted_in_tray)
        
        # Fast click-outside polling loop (runs every 30ms)
        self._poll_click_outside()
        
        # 1-second live ticker
        self._tick_live()
        
        # Single instance show event listener
        self._poll_show_event()
        
        # Initial data fetch
        self.trigger_refresh(silent=True)

        # Show window on launch
        if "--minimized" not in sys.argv and "--silent" not in sys.argv:
            self.root.after(200, self.show_window)

    def post(self, callback, *args, **kwargs):
        self.msg_queue.put((callback, args, kwargs))

    def _process_queue(self):
        try:
            while True:
                cb, args, kwargs = self.msg_queue.get_nowait()
                try:
                    cb(*args, **kwargs)
                except Exception as e:
                    print(f"Callback error: {e}")
        except queue.Empty:
            pass
        self.root.after(40, self._process_queue)

    def round_poly(self, x1, y1, x2, y2, r=16, **kwargs):
        """Draws a smooth anti-aliased rounded polygon on the canvas."""
        points = [
            x1+r, y1, x2-r, y1, x2, y1,
            x2, y1+r, x2, y2-r, x2, y2,
            x2-r, y2, x1+r, y2, x1, y2,
            x1, y2-r, x1, y1+r, x1, y1
        ]
        return self.canvas.create_polygon(points, smooth=True, **kwargs)

    def render_glass_ui(self):
        """Renders the complete Glassmorphism UI with cards, specular highlights, and neon progress bars."""
        self.canvas.delete("all")
        w = self.win_width
        h = self.win_height
        
        # 1. Main outer glass body (deep translucent obsidian with luminous 1px border)
        self.round_poly(4, 4, w - 4, h - 4, r=20, fill="#0c111e", outline="#2c3a54", width=1, tags="bg_poly")
        # Specular light refraction line at top of glass window
        self.canvas.create_line(24, 5, w - 24, 5, fill="#485c7f", width=1)
        self.canvas.create_line(28, 6, w - 28, 6, fill="#202c42", width=1)
        
        # 2. Header
        # Electric Blue Glass Logo Pill
        self.round_poly(18, 16, 52, 40, r=8, fill="#2563eb", outline="#3b82f6", width=1)
        self.canvas.create_text(35, 28, text="AG", fill="#ffffff", font=("Segoe UI", 10, "bold"))
        
        # Window Title
        self.canvas.create_text(60, 28, text="Antigravity Quota", anchor="w", fill="#f8fafc", font=("Segoe UI", 13, "bold"), tags="header_drag")
        
        # LIVE Glass Badge
        live_badge_fill = "#064e3b" if (time.time() - self.last_successful_fetch <= 15 and self.last_successful_fetch > 0) else ("#450a0a" if self.last_successful_fetch > 0 else "#064e3b")
        live_badge_border = "#10b981" if (time.time() - self.last_successful_fetch <= 15 and self.last_successful_fetch > 0) else ("#ef4444" if self.last_successful_fetch > 0 else "#10b981")
        live_text = "● LIVE" if (time.time() - self.last_successful_fetch <= 15 or self.last_successful_fetch == 0) else "● OFFLINE"
        live_text_col = "#10b981" if (time.time() - self.last_successful_fetch <= 15 or self.last_successful_fetch == 0) else "#ef4444"
        
        self.round_poly(206, 18, 268, 38, r=9, fill=live_badge_fill, outline=live_badge_border, width=1, tags="live_badge_bg")
        self.canvas.create_text(237, 28, text=live_text, fill=live_text_col, font=("Segoe UI", 9, "bold"), tags="live_badge_txt")
        
        # Header Action Buttons: Pin & Close
        # Pin Button
        pin_bg = "#1e293b" if self.pinned else "#141c2c"
        pin_col = "#38bdf8" if self.pinned else "#94a3b8"
        self.round_poly(w - 76, 17, w - 46, 39, r=6, fill=pin_bg, outline="#2b3b55", width=1, tags="btn_pin")
        self.canvas.create_text(w - 61, 28, text="📌", fill=pin_col, font=("Segoe UI Emoji", 10), tags="btn_pin")
        
        # Close Button
        self.round_poly(w - 40, 17, w - 16, 39, r=6, fill="#141c2c", outline="#2b3b55", width=1, tags="btn_close")
        self.canvas.create_text(w - 28, 28, text="✕", fill="#94a3b8", font=("Segoe UI", 10, "bold"), tags="btn_close")
        
        # Subtitle
        sub_text = "Angepinnt • Bleibt als Widget offen" if self.pinned else "Floating Glass Widget • Multi-Border Resizable"
        self.canvas.create_text(20, 48, text=sub_text, anchor="w", fill="#94a3b8", font=("Segoe UI", 8), tags="sub_lbl")
        
        # 3. Model Cards
        card_h = max(160, int((h - 130) / 2))
        y_card1 = 66
        y_card2 = y_card1 + card_h + 10
        
        self.render_card(y_card1, card_h, "gemini", "Gemini Models", "Gemini Flash, Gemini Pro", "#38bdf8")
        self.render_card(y_card2, card_h, "claude", "Claude & GPT Models", "Claude Opus, Claude Sonnet, GPT-OSS", "#f59e0b")
        
        # 4. Footer
        y_footer = h - 26
        status_txt = "Live synchronisiert" if (time.time() - self.last_successful_fetch <= 15 or self.last_successful_fetch == 0) else "Kein Signal (>15s)"
        status_col = "#94a3b8" if (time.time() - self.last_successful_fetch <= 15 or self.last_successful_fetch == 0) else "#ef4444"
        self.canvas.create_text(20, y_footer, text=status_txt, anchor="w", fill=status_col, font=("Segoe UI", 9), tags="status_txt")
        
        # Refresh Glass Button
        self.round_poly(w - 128, y_footer - 16, w - 18, y_footer + 14, r=7, fill="#162032", outline="#2d3f5c", width=1, tags="btn_refresh")
        self.canvas.create_line(w - 120, y_footer - 15, w - 26, y_footer - 15, fill="#3b5278", width=1)
        refresh_label = "⌛ Lade..." if self.is_fetching else "Aktualisieren"
        self.canvas.create_text(w - 73, y_footer, text=refresh_label, fill="#f8fafc", font=("Segoe UI", 9, "bold"), tags="btn_refresh")

    def render_card(self, y, card_h, group_key, title, subtitle, badge_col):
        w = self.win_width
        
        # Frosted glass card surface
        self.round_poly(16, y, w - 16, y + card_h, r=16, fill="#131b2c", outline="#25354e", width=1, tags=f"card_{group_key}")
        # Top glass reflection line
        self.canvas.create_line(30, y + 1, w - 30, y + 1, fill="#334768", width=1)
        
        # Group Header
        self.round_poly(28, y + 14, 38, y + 24, r=4, fill=badge_col)
        self.canvas.create_text(46, y + 18, text=title, anchor="w", fill="#f8fafc", font=("Segoe UI", 11, "bold"))
        self.canvas.create_text(46, y + 33, text=subtitle, anchor="w", fill="#94a3b8", font=("Segoe UI", 8))
        
        # Proportional vertical spacing
        spacing_unit = (card_h - 40) / 4.0
        
        # --- 5h Limit ---
        y_5h_lbl = int(y + 40 + spacing_unit * 0.4)
        self.canvas.create_text(28, y_5h_lbl, text="5-Stunden-Limit", anchor="w", fill="#cbd5e1", font=("Segoe UI", 9, "bold"))
        
        # Cached values or placeholders
        pct_5h = self.bucket_reset_targets.get(f"{group_key}_5h", {}).get("pct_str", "--%")
        frac_5h = self.bucket_reset_targets.get(f"{group_key}_5h", {}).get("fraction", 1.0)
        col_5h = get_color_for_fraction(frac_5h)
        self.canvas.create_text(w - 28, y_5h_lbl, text=pct_5h, anchor="e", fill=col_5h, font=("Segoe UI", 13, "bold"), tags=f"{group_key}_5h_pct")
        
        # 5h Progress Bar (glowing pill)
        y_5h_bar = int(y_5h_lbl + 16)
        bar_w = w - 56
        self.round_poly(28, y_5h_bar, w - 28, y_5h_bar + 8, r=4, fill="#0a0e18", outline="#1e2a3e", width=1)
        fill_5h = max(4, int(bar_w * frac_5h))
        self.round_poly(28, y_5h_bar, 28 + fill_5h, y_5h_bar + 8, r=4, fill=col_5h, tags=f"{group_key}_5h_bar")
        
        # 5h Reset countdown text
        y_5h_rst = int(y_5h_bar + 18)
        rst_5h = self.bucket_reset_targets.get(f"{group_key}_5h", {}).get("last_text", "Reset: --")
        self.canvas.create_text(28, y_5h_rst, text=rst_5h, anchor="w", fill="#94a3b8", font=("Segoe UI", 9), tags=f"{group_key}_5h_rst")
        
        # Divider Line
        y_div = int(y_5h_rst + 16)
        self.canvas.create_line(28, y_div, w - 28, y_div, fill="#1c2638", width=1)
        
        # --- Weekly Limit ---
        y_w_lbl = int(y_div + 16)
        self.canvas.create_text(28, y_w_lbl, text="Wöchentliches Limit", anchor="w", fill="#cbd5e1", font=("Segoe UI", 9, "bold"))
        
        pct_w = self.bucket_reset_targets.get(f"{group_key}_weekly", {}).get("pct_str", "--%")
        frac_w = self.bucket_reset_targets.get(f"{group_key}_weekly", {}).get("fraction", 1.0)
        col_w = get_color_for_fraction(frac_w)
        self.canvas.create_text(w - 28, y_w_lbl, text=pct_w, anchor="e", fill=col_w, font=("Segoe UI", 13, "bold"), tags=f"{group_key}_w_pct")
        
        # Weekly Progress Bar
        y_w_bar = int(y_w_lbl + 16)
        self.round_poly(28, y_w_bar, w - 28, y_w_bar + 8, r=4, fill="#0a0e18", outline="#1e2a3e", width=1)
        fill_w = max(4, int(bar_w * frac_w))
        self.round_poly(28, y_w_bar, 28 + fill_w, y_w_bar + 8, r=4, fill=col_w, tags=f"{group_key}_w_bar")
        
        # Weekly Reset countdown text
        y_w_rst = int(y_w_bar + 18)
        rst_w = self.bucket_reset_targets.get(f"{group_key}_weekly", {}).get("last_text", "Reset: --")
        self.canvas.create_text(28, y_w_rst, text=rst_w, anchor="w", fill="#94a3b8", font=("Segoe UI", 9), tags=f"{group_key}_w_rst")

    def setup_resize_borders(self):
        """Creates 8 border resize handles along all edges and corners."""
        bs = 6
        cs = 14
        color = "#182234"
        hover_color = "#38bdf8"
        
        self.resize_handles = []
        
        b_n = tk.Frame(self.root, bg=color, cursor="size_ns")
        b_n.place(x=cs, y=0, relwidth=1.0, width=-(cs * 2), height=bs)
        
        b_s = tk.Frame(self.root, bg=color, cursor="size_ns")
        b_s.place(x=cs, rely=1.0, y=-bs, relwidth=1.0, width=-(cs * 2), height=bs)
        
        b_w = tk.Frame(self.root, bg=color, cursor="size_we")
        b_w.place(x=0, y=cs, relheight=1.0, height=-(cs * 2), width=bs)
        
        b_e = tk.Frame(self.root, bg=color, cursor="size_we")
        b_e.place(relx=1.0, x=-bs, y=cs, relheight=1.0, height=-(cs * 2), width=bs)
        
        b_nw = tk.Frame(self.root, bg=color, cursor="size_nw_se")
        b_nw.place(x=0, y=0, width=cs, height=cs)
        
        b_ne = tk.Frame(self.root, bg=color, cursor="size_ne_sw")
        b_ne.place(relx=1.0, x=-cs, y=0, width=cs, height=cs)
        
        b_sw = tk.Frame(self.root, bg=color, cursor="size_ne_sw")
        b_sw.place(x=0, rely=1.0, y=-cs, width=cs, height=cs)
        
        b_se = tk.Frame(self.root, bg=color, cursor="size_nw_se")
        b_se.place(relx=1.0, x=-cs, rely=1.0, y=-cs, width=cs, height=cs)
        
        handles = [
            (b_n, "n"), (b_s, "s"), (b_w, "w"), (b_e, "e"),
            (b_nw, "nw"), (b_ne, "ne"), (b_sw, "sw"), (b_se, "se")
        ]
        
        for widget, direction in handles:
            widget.lift()
            widget.bind("<Button-1>", lambda e, d=direction: self.start_resize(e, d))
            widget.bind("<B1-Motion>", self.do_resize)
            widget.bind("<ButtonRelease-1>", self.stop_resize)
            widget.bind("<Enter>", lambda e, w=widget: w.config(bg=hover_color))
            widget.bind("<Leave>", lambda e, w=widget: w.config(bg=color))
            self.resize_handles.append(widget)

    def start_resize(self, event, direction):
        self.is_resizing = True
        self.mouse_is_down_inside = True
        self.resize_direction = direction
        self.resize_start_x = event.x_root
        self.resize_start_y = event.y_root
        self.resize_start_win_x = self.root.winfo_x()
        self.resize_start_win_y = self.root.winfo_y()
        self.resize_start_w = self.root.winfo_width()
        self.resize_start_h = self.root.winfo_height()

    def do_resize(self, event):
        if not self.is_resizing:
            return
        dx = event.x_root - self.resize_start_x
        dy = event.y_root - self.resize_start_y
        
        new_w = self.resize_start_w
        new_h = self.resize_start_h
        new_x = self.resize_start_win_x
        new_y = self.resize_start_win_y
        
        if "e" in self.resize_direction:
            new_w = max(310, min(900, self.resize_start_w + dx))
        elif "w" in self.resize_direction:
            target_w = self.resize_start_w - dx
            new_w = max(310, min(900, target_w))
            new_x = self.resize_start_win_x + (self.resize_start_w - new_w)
            
        if "s" in self.resize_direction:
            new_h = max(360, min(1000, self.resize_start_h + dy))
        elif "n" in self.resize_direction:
            target_h = self.resize_start_h - dy
            new_h = max(360, min(1000, target_h))
            new_y = self.resize_start_win_y + (self.resize_start_h - new_h)
            
        self.win_width = new_w
        self.win_height = new_h
        self.root.geometry(f"{new_w}x{new_h}+{new_x}+{new_y}")
        self.canvas.config(width=new_w, height=new_h)
        self.render_glass_ui()

    def stop_resize(self, event):
        if self.is_resizing:
            self.is_resizing = False
            self.mouse_is_down_inside = False
            self.last_interaction_time = time.time()
            self.config["win_width"] = self.win_width
            self.config["win_height"] = self.win_height
            save_config(self.config)

    def bind_events(self):
        # Window moving
        def start_move(event):
            # Check if clicked on interactive buttons
            tags = self.canvas.gettags("current")
            if "btn_close" in tags:
                self.hide_window()
                return
            if "btn_pin" in tags:
                self.toggle_pin()
                return
            if "btn_refresh" in tags:
                self.trigger_refresh(silent=False)
                return
                
            self.is_dragging = True
            self.mouse_is_down_inside = True
            self.drag_start_x = event.x_root
            self.drag_start_y = event.y_root
            self.win_start_x = self.root.winfo_x()
            self.win_start_y = self.root.winfo_y()

        def do_move(event):
            if not self.is_dragging:
                return
            dx = event.x_root - self.drag_start_x
            dy = event.y_root - self.drag_start_y
            new_x = self.win_start_x + dx
            new_y = self.win_start_y + dy
            self.root.geometry(f"{self.win_width}x{self.win_height}+{new_x}+{new_y}")

        def stop_move(event):
            if self.is_dragging:
                self.is_dragging = False
                self.mouse_is_down_inside = False
                self.last_interaction_time = time.time()
                self.config["custom_pos"] = True
                self.config["pos_x"] = self.root.winfo_x()
                self.config["pos_y"] = self.root.winfo_y()
                save_config(self.config)

        self.canvas.bind("<Button-1>", start_move)
        self.canvas.bind("<B1-Motion>", do_move)
        self.canvas.bind("<ButtonRelease-1>", stop_move)
        self.canvas.bind("<Double-Button-1>", lambda e: self.reset_to_tray())

        # Escape closes window
        self.root.bind("<Escape>", lambda e: self.hide_window())

    # Reliable check for clicking outside the window (30ms interval)
    def _poll_click_outside(self):
        if self.is_open and not self.pinned:
            if self.is_dragging or self.is_resizing or self.mouse_is_down_inside:
                self.root.after(30, self._poll_click_outside)
                return
            
            if time.time() - self.open_timestamp < 0.3:
                self.root.after(30, self._poll_click_outside)
                return
            if time.time() - self.last_interaction_time < 0.35:
                self.root.after(30, self._poll_click_outside)
                return

            l_down = ctypes.windll.user32.GetAsyncKeyState(0x01) & 0x8000
            r_down = ctypes.windll.user32.GetAsyncKeyState(0x02) & 0x8000
            
            if l_down or r_down:
                pt = wintypes.POINT()
                ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
                wx = self.root.winfo_x()
                wy = self.root.winfo_y()
                ww = self.root.winfo_width()
                wh = self.root.winfo_height()
                
                margin = 25
                is_inside = (wx - margin <= pt.x <= wx + ww + margin) and (wy - margin <= pt.y <= wy + wh + margin)
                
                if is_inside:
                    self.mouse_is_down_inside = True
                else:
                    self.hide_window()
                    self.root.after(30, self._poll_click_outside)
                    return
            else:
                self.mouse_is_down_inside = False

        self.root.after(30, self._poll_click_outside)

    # Listen for show event from second instance
    def _poll_show_event(self):
        global _show_event_handle
        if _show_event_handle:
            if ctypes.windll.kernel32.WaitForSingleObject(_show_event_handle, 0) == 0:
                self.show_window()
        self.root.after(100, self._poll_show_event)

    # 1-second live ticker
    def _tick_live(self):
        now_ts = time.time()
        
        # 1. Update live countdown labels in real-time
        if self.is_open:
            self._update_countdown_labels()
        
        # 2. Check signal freshness
        if self.last_successful_fetch > 0:
            elapsed = now_ts - self.last_successful_fetch
            if elapsed > 15:
                try:
                    self.canvas.itemconfigure("live_badge_bg", fill="#450a0a", outline="#ef4444")
                    self.canvas.itemconfigure("live_badge_txt", text="● OFFLINE", fill="#ef4444")
                    self.canvas.itemconfigure("status_txt", text="Kein Signal (>15s)", fill="#ef4444")
                except Exception:
                    pass
            else:
                try:
                    self.canvas.itemconfigure("live_badge_bg", fill="#064e3b", outline="#10b981")
                    self.canvas.itemconfigure("live_badge_txt", text="● LIVE", fill="#10b981")
                    self.canvas.itemconfigure("status_txt", text="Live synchronisiert", fill="#94a3b8")
                except Exception:
                    pass
        
        # 3. Live Auto-Refresh logic:
        interval = self.config.get("live_refresh_seconds", 10) if self.is_open else self.config.get("background_refresh_seconds", 60)
        if not self.is_fetching and (now_ts - self.last_fetch_start >= interval):
            self.trigger_refresh(silent=True)
            
        self.root.after(1000, self._tick_live)

    def _update_countdown_labels(self):
        for key, target_info in self.bucket_reset_targets.items():
            target_dt = target_info.get("target_dt")
            fraction = target_info.get("fraction", 1.0)
            tag_name = target_info.get("tag")
            if tag_name and target_dt:
                countdown_text = format_countdown_seconds(target_dt, fraction)
                target_info["last_text"] = countdown_text
                try:
                    self.canvas.itemconfigure(tag_name, text=countdown_text)
                except Exception:
                    pass

    def toggle_pin(self):
        self.pinned = not self.pinned
        self.config["pinned"] = self.pinned
        save_config(self.config)
        self.render_glass_ui()

    def reset_to_tray(self):
        """Docks the window back above the system tray and restores standard size."""
        self.config["custom_pos"] = False
        self.config["pos_x"] = None
        self.config["pos_y"] = None
        self.win_width = 390
        self.win_height = 520
        self.config["win_width"] = 390
        self.config["win_height"] = 520
        save_config(self.config)
        self.position_window()
        self.render_glass_ui()

    def position_window(self):
        left, top, right, bottom = get_work_area()
        if self.config.get("custom_pos") and self.config.get("pos_x") is not None and self.config.get("pos_y") is not None:
            x = int(self.config["pos_x"])
            y = int(self.config["pos_y"])
            x = max(left, min(right - self.win_width, x))
            y = max(top, min(bottom - self.win_height, y))
        else:
            x = right - self.win_width - 12
            y = bottom - self.win_height - 10
        self.root.geometry(f"{self.win_width}x{self.win_height}+{x}+{y}")

    def show_window(self):
        self.position_window()
        apply_dwm_styling(self.root)
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        self.is_open = True
        self.open_timestamp = time.time()
        
        try:
            top_hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id()) or self.root.winfo_id()
            ctypes.windll.user32.SetForegroundWindow(top_hwnd)
        except Exception:
            pass
        
        if self.last_successful_fetch == 0 or (time.time() - self.last_fetch_start > 5):
            self.trigger_refresh(silent=True)

    def hide_window(self):
        self.is_open = False
        self.mouse_is_down_inside = False
        self.is_resizing = False
        self.is_dragging = False
        self.last_hide_time = time.time()
        self.root.withdraw()

    def toggle_window(self):
        if time.time() - self.last_hide_time < 0.35:
            return
        if self.is_open:
            self.hide_window()
        else:
            self.show_window()

    # Background Fetching & Updates
    def trigger_refresh(self, silent=True):
        if self.is_fetching:
            return
        self.is_fetching = True
        self.last_fetch_start = time.time()
        
        if not silent:
            try:
                self.canvas.itemconfigure("btn_refresh", text="⌛ Lade...")
            except Exception:
                pass
            
        threading.Thread(target=self._fetch_worker, daemon=True).start()

    def _fetch_worker(self):
        data, err = fetch_usage_data()
        self.post(self._on_fetch_complete, data, err)

    def _on_fetch_complete(self, data, err):
        self.is_fetching = False
        
        if err or not data:
            if time.time() - self.last_successful_fetch > 15:
                try:
                    self.canvas.itemconfigure("live_badge_bg", fill="#450a0a", outline="#ef4444")
                    self.canvas.itemconfigure("live_badge_txt", text="● OFFLINE", fill="#ef4444")
                    self.canvas.itemconfigure("status_txt", text="Kein Signal • Timeout", fill="#ef4444")
                except Exception:
                    pass
            print(f"Fetch error: {err}")
            return
        
        self.latest_data = data
        self.last_successful_fetch = time.time()
        
        self.update_data_state(data)
        self.render_glass_ui()
        self.update_tray_state(data)

    def update_data_state(self, data):
        groups = data.get("groups", [])
        for group in groups:
            g_name = group.get("name", "")
            buckets = group.get("buckets", [])
            
            group_key = ""
            if "Gemini" in g_name:
                group_key = "gemini"
            elif "Claude" in g_name or "GPT" in g_name:
                group_key = "claude"
            
            if not group_key:
                continue
            
            for b in buckets:
                b_id = b.get("id", "")
                frac = b.get("remaining_fraction", 1.0)
                reset_iso = b.get("reset_time", "")
                
                target_dt = None
                if reset_iso:
                    try:
                        clean_str = reset_iso.replace("Z", "+00:00")
                        target_dt = datetime.fromisoformat(clean_str)
                    except Exception:
                        pass
                
                pct_str = f"{frac * 100:.1f}%"
                
                if "5h" in b_id:
                    self.bucket_reset_targets[f"{group_key}_5h"] = {
                        "tag": f"{group_key}_5h_rst",
                        "pct_str": pct_str,
                        "fraction": frac,
                        "target_dt": target_dt,
                        "last_text": format_countdown_seconds(target_dt, frac)
                    }
                elif "weekly" in b_id:
                    self.bucket_reset_targets[f"{group_key}_weekly"] = {
                        "tag": f"{group_key}_w_rst",
                        "pct_str": pct_str,
                        "fraction": frac,
                        "target_dt": target_dt,
                        "last_text": format_countdown_seconds(target_dt, frac)
                    }

    def update_tray_state(self, data):
        if not self.tray_icon:
            return
        
        min_frac = 1.0
        groups = data.get("groups", [])
        for group in groups:
            for b in group.get("buckets", []):
                frac = b.get("remaining_fraction", 1.0)
                min_frac = min(min_frac, frac)
        
        self.tray_icon.title = "Antigravity Quota Monitor"
        new_icon_img = create_tray_image(min_frac)
        self.tray_icon.icon = new_icon_img

    # Tray Menu (Right-Click Menu)
    def create_tray_menu(self):
        menu_items = [
            item("📊 Dashboard öffnen", lambda *a: self.post(self.toggle_window), default=True),
            item("🔄 Jetzt live aktualisieren", lambda *a: self.post(lambda: self.trigger_refresh(silent=False))),
            item("📍 An Taskleiste andocken (Reset)", lambda *a: self.post(self.reset_to_tray)),
            Menu.SEPARATOR,
            item("🚀 Autostart mit Windows", self.toggle_autostart, checked=lambda item: is_autostart_enabled()),
            Menu.SEPARATOR,
            item("❌ Beenden", lambda *a: self.post(self.quit_app))
        ]
        return Menu(*menu_items)

    def toggle_autostart(self, *args):
        now_enabled = is_autostart_enabled()
        set_autostart(not now_enabled)

    def init_tray_icon(self):
        initial_img = create_tray_image(1.0)
        self.tray_icon = pystray.Icon(
            "AntigravityQuota",
            initial_img,
            title="Antigravity Quota Monitor",
            menu=self.create_tray_menu()
        )
        self.tray_icon.run_detached()

    def quit_app(self):
        global _show_event_handle, _mutex_handle
        if self.tray_icon:
            self.tray_icon.stop()
        if _show_event_handle:
            try:
                ctypes.windll.kernel32.CloseHandle(_show_event_handle)
            except Exception:
                pass
            _show_event_handle = None
        if _mutex_handle:
            try:
                ctypes.windll.kernel32.CloseHandle(_mutex_handle)
            except Exception:
                pass
            _mutex_handle = None
        self.root.after(0, self.root.destroy)

    def run(self):
        self.root.mainloop()

# Single Instance Check via Windows Mutex + Show Event IPC
SHOW_EVENT_NAME = "AntigravityQuotaTray_ShowEvent"
_show_event_handle = None

def check_single_instance():
    global _mutex_handle, _show_event_handle
    ERROR_ALREADY_EXISTS = 183
    _mutex_handle = ctypes.windll.kernel32.CreateMutexW(None, False, MUTEX_NAME)
    last_error = ctypes.windll.kernel32.GetLastError()
    if last_error == ERROR_ALREADY_EXISTS:
        evt = ctypes.windll.kernel32.OpenEventW(0x0002, False, SHOW_EVENT_NAME)
        if evt:
            ctypes.windll.kernel32.SetEvent(evt)
            ctypes.windll.kernel32.CloseHandle(evt)
        return False
    
    _show_event_handle = ctypes.windll.kernel32.CreateEventW(None, False, False, SHOW_EVENT_NAME)
    return True

def main():
    try:
        ok = check_single_instance()
        if not ok:
            with open(os.path.join(APP_DIR, "agy_tray.log"), "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now().isoformat()}] Bereits eine Instanz aktiv.\n")
            sys.exit(0)
        
        with open(os.path.join(APP_DIR, "agy_tray.log"), "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().isoformat()}] App wird gestartet...\n")
            
        app = QuotaApp()
        app.run()
    except Exception as e:
        import traceback
        with open(os.path.join(APP_DIR, "agy_tray.log"), "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().isoformat()}] Fehler:\n{traceback.format_exc()}\n")

if __name__ == "__main__":
    main()
