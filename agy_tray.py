"""
Antigravity Quota Monitor - Windows System Tray Utility
Monitors API limits and usage for Gemini and Claude/GPT model groups in real-time.
Features floating, multi-border resizable window, real-time second-by-second countdowns,
Windows 11 glassmorphism/acrylic styling, and crisp centered tray icon.
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

# DPI Awareness for crisp fonts on Windows High-DPI screens
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
    "win_height": 510,
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

# Windows 11 DWM Styling: Rounded Corners, Dark Mode, Acrylic
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
        startupinfo.wShowWindow = 0  # SW_HIDE
    
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
                return "⚡ 100% bereit"
            return "⏳ Reset fällig • lädt nach"
        
        days = diff // 86400
        rem = diff % 86400
        hours = rem // 3600
        mins = (rem % 3600) // 60
        secs = rem % 60
        
        if days > 0:
            return f"⏱ Reset in {days}T {hours}Std"
        elif hours > 0:
            return f"⏱ Reset in {hours}h {mins:02d}m {secs:02d}s"
        elif mins > 0:
            return f"⏱ Reset in {mins}m {secs:02d}s"
        else:
            return f"⏱ Reset in {secs}s"
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
    
    # Outer dark glass background circle
    pad = 12
    draw.ellipse(
        (pad, pad, canvas_size - pad, canvas_size - pad),
        fill=(18, 24, 38, 255),
        outline=(55, 65, 81, 255),
        width=4
    )
    
    # Ring track
    track_pad = 24
    draw.ellipse(
        (track_pad, track_pad, canvas_size - track_pad, canvas_size - track_pad),
        outline=(40, 50, 68, 255),
        width=18
    )
    
    # Progress Arc
    sweep = max(18, int(min_fraction * 360))
    if min_fraction >= 0.50:
        color = (16, 185, 129, 255)  # Emerald
    elif min_fraction >= 0.20:
        color = (245, 158, 11, 255)  # Amber
    else:
        color = (239, 68, 68, 255)   # Rose Red
        
    draw.arc(
        (track_pad, track_pad, canvas_size - track_pad, canvas_size - track_pad),
        start=-90,
        end=-90 + sweep,
        fill=color,
        width=18
    )
    
    # Centered 'AG' Monogram (exact bounding box offset centering)
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
    
    # High-quality downsampling to 64x64 for Windows System Tray
    return img.resize((64, 64), Image.Resampling.LANCZOS)

# UI Components: Rounded Pill Progress Bar
class RoundedProgressBar(tk.Canvas):
    def __init__(self, parent, height=8, bg_color="#182234", trough_color="#26344d", **kwargs):
        super().__init__(parent, height=height, bg=bg_color, highlightthickness=0, bd=0, **kwargs)
        self.w = 320
        self.h = height
        self.bg_color = bg_color
        self.trough_color = trough_color
        self.fraction = 1.0
        self.bar_color = "#10b981"
        self.bind("<Configure>", self.on_resize)
    
    def on_resize(self, event):
        if event.width > 10:
            self.w = event.width
            self.draw_bar()
    
    def set_value(self, fraction):
        self.fraction = max(0.0, min(1.0, fraction))
        self.bar_color = get_color_for_fraction(self.fraction)
        self.draw_bar()
    
    def set_height(self, h):
        self.h = h
        self.config(height=h)
        self.draw_bar()
        
    def draw_bar(self):
        self.delete("all")
        h = self.h
        w = self.w
        r = h / 2.0
        if w <= 0 or h <= 0:
            return
        
        # Trough (Pill shape)
        self.create_arc(0, 0, h, h, start=90, extent=180, fill=self.trough_color, outline="")
        self.create_rectangle(r, 0, max(r, w - r), h, fill=self.trough_color, outline="")
        self.create_arc(max(0, w - h), 0, w, h, start=-90, extent=180, fill=self.trough_color, outline="")
        
        # Progress fill
        fill_w = int(w * self.fraction)
        if fill_w > h:
            self.create_arc(0, 0, h, h, start=90, extent=180, fill=self.bar_color, outline="")
            self.create_rectangle(r, 0, fill_w - r, h, fill=self.bar_color, outline="")
            self.create_arc(fill_w - h, 0, fill_w, h, start=-90, extent=180, fill=self.bar_color, outline="")
        elif fill_w > 0:
            self.create_oval(0, 0, max(fill_w, h), h, fill=self.bar_color, outline="")

class QuotaApp:
    def __init__(self):
        self.config = load_config()
        self.latest_data = None
        self.is_fetching = False
        self.last_successful_fetch = 0
        self.last_fetch_start = 0
        self.pinned = self.config.get("pinned", False)
        self.msg_queue = queue.Queue()
        
        # Target reset datetimes for real-time live ticking
        self.bucket_reset_targets = {}
        
        # Window & Drag / Resize State
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
        self.win_height = max(360, min(1000, self.config.get("win_height", 510)))
        
        # Init Tkinter Root
        self.root = tk.Tk()
        self.root.title("Antigravity Quota")
        self.root.configure(bg="#0c101a")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        # Frosted glass soft transparency
        try:
            self.root.attributes("-alpha", 0.95)
        except Exception:
            pass
        self.root.withdraw()  # Hidden on launch
        
        ico_path = os.path.join(APP_DIR, "icon.ico")
        if os.path.exists(ico_path):
            try:
                self.root.iconbitmap(ico_path)
            except Exception:
                pass
        
        self.setup_ui()
        self.setup_resize_borders()
        self.bind_events()
        
        # Start queue poller
        self._process_queue()
        
        # Tray Icon setup
        self.tray_icon = None
        self.init_tray_icon()
        
        # Ensure icon is pinned to visible taskbar in Windows 11
        self.root.after(1000, ensure_promoted_in_tray)
        
        # Fast click-outside polling loop (runs every 30ms)
        self._poll_click_outside()
        
        # 1-second live ticker
        self._tick_live()
        
        # Show Event IPC listener (allows desktop shortcut or start.bat to bring window to front)
        self._poll_show_event()
        
        # Initial data fetch
        self.trigger_refresh(silent=True)

        # Open floating window on launch
        if "--minimized" not in sys.argv and "--silent" not in sys.argv:
            self.root.after(300, self.show_window)

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

    def setup_ui(self):
        # Outer Glass Border Container
        self.border_frame = tk.Frame(self.root, bg="#253246", bd=0)
        self.border_frame.pack(fill="both", expand=True, padx=6, pady=6)
        
        # Main interior container (Deep Slate Glass)
        self.main_container = tk.Frame(self.border_frame, bg="#0f1422", padx=14, pady=12)
        self.main_container.pack(fill="both", expand=True, padx=1, pady=1)
        
        # Header (Draggable Floating Window Bar)
        self.header = tk.Frame(self.main_container, bg="#0f1422", cursor="fleur")
        self.header.pack(fill="x", pady=(0, 10))
        
        # Title Box
        self.title_box = tk.Frame(self.header, bg="#0f1422", cursor="fleur")
        self.title_box.pack(side="left", fill="x", expand=True)
        
        title_row = tk.Frame(self.title_box, bg="#0f1422", cursor="fleur")
        title_row.pack(anchor="w")
        
        # Logo badge
        self.logo_lbl = tk.Label(
            title_row,
            text="AG",
            font=("Segoe UI", 9, "bold"),
            fg="#ffffff",
            bg="#2563eb",
            padx=5,
            pady=1
        )
        self.logo_lbl.pack(side="left", padx=(0, 8))
        
        self.title_lbl = tk.Label(
            title_row,
            text="Antigravity Quota",
            font=("Segoe UI", 12, "bold"),
            fg="#f8fafc",
            bg="#0f1422",
            cursor="fleur"
        )
        self.title_lbl.pack(side="left")
        
        # Live Indicator in Header
        self.live_badge = tk.Label(
            title_row,
            text="● LIVE",
            font=("Segoe UI", 8, "bold"),
            fg="#10b981",
            bg="#064e3b",
            padx=6,
            pady=1
        )
        self.live_badge.pack(side="left", padx=(8, 0))
        
        self.sub_lbl = tk.Label(
            self.title_box,
            text="Floating Window • An Rändern skalierbar",
            font=("Segoe UI", 8),
            fg="#94a3b8",
            bg="#0f1422",
            cursor="fleur"
        )
        self.sub_lbl.pack(anchor="w", pady=(2, 0))
        
        # Header action buttons (Pin, Close)
        actions_box = tk.Frame(self.header, bg="#0f1422")
        actions_box.pack(side="right", anchor="n")
        
        # Pin button
        self.pin_btn = tk.Label(
            actions_box,
            text="📌" if self.pinned else "📍",
            font=("Segoe UI", 11),
            fg="#38bdf8" if self.pinned else "#94a3b8",
            bg="#0f1422",
            cursor="hand2",
            padx=4
        )
        self.pin_btn.pack(side="left", padx=(0, 2))
        self.pin_btn.bind("<Button-1>", lambda e: self.toggle_pin())
        
        # Close button
        close_btn = tk.Label(
            actions_box,
            text="✕",
            font=("Segoe UI", 11, "bold"),
            fg="#94a3b8",
            bg="#0f1422",
            cursor="hand2",
            padx=4
        )
        close_btn.pack(side="left", padx=(2, 0))
        close_btn.bind("<Button-1>", lambda e: self.hide_window())
        close_btn.bind("<Enter>", lambda e: close_btn.config(fg="#ef4444"))
        close_btn.bind("<Leave>", lambda e: close_btn.config(fg="#94a3b8"))
        
        # Cards Container (dynamically adapts when resized)
        self.cards_frame = tk.Frame(self.main_container, bg="#0f1422")
        self.cards_frame.pack(fill="both", expand=True)
        
        # Build Model Group Cards
        self.build_cards()
        
        # Footer
        self.footer = tk.Frame(self.main_container, bg="#0f1422")
        self.footer.pack(fill="x", pady=(10, 0))
        
        self.status_lbl = tk.Label(
            self.footer,
            text="Live synchronisiert",
            font=("Segoe UI", 9),
            fg="#94a3b8",
            bg="#0f1422"
        )
        self.status_lbl.pack(side="left")
        
        self.refresh_btn = tk.Label(
            self.footer,
            text="🔄 Aktualisieren",
            font=("Segoe UI", 9, "bold"),
            fg="#f8fafc",
            bg="#1e293b",
            cursor="hand2",
            padx=10,
            pady=4
        )
        self.refresh_btn.pack(side="right")
        self.refresh_btn.bind("<Button-1>", lambda e: self.trigger_refresh(silent=False))
        self.refresh_btn.bind("<Enter>", lambda e: self.refresh_btn.config(bg="#334155"))
        self.refresh_btn.bind("<Leave>", lambda e: self.refresh_btn.config(bg="#1e293b"))

    def setup_resize_borders(self):
        """Creates 8 border resize handles along all edges and corners."""
        bs = 6   # border thickness
        cs = 12  # corner dimension
        color = "#253246"
        hover_color = "#38bdf8"
        
        self.resize_handles = []
        
        # North
        b_n = tk.Frame(self.root, bg=color, cursor="size_ns")
        b_n.place(x=cs, y=0, relwidth=1.0, width=-(cs * 2), height=bs)
        
        # South
        b_s = tk.Frame(self.root, bg=color, cursor="size_ns")
        b_s.place(x=cs, rely=1.0, y=-bs, relwidth=1.0, width=-(cs * 2), height=bs)
        
        # West (Left)
        b_w = tk.Frame(self.root, bg=color, cursor="size_we")
        b_w.place(x=0, y=cs, relheight=1.0, height=-(cs * 2), width=bs)
        
        # East (Right)
        b_e = tk.Frame(self.root, bg=color, cursor="size_we")
        b_e.place(relx=1.0, x=-bs, y=cs, relheight=1.0, height=-(cs * 2), width=bs)
        
        # Top-Left Corner
        b_nw = tk.Frame(self.root, bg=color, cursor="size_nw_se")
        b_nw.place(x=0, y=0, width=cs, height=cs)
        
        # Top-Right Corner
        b_ne = tk.Frame(self.root, bg=color, cursor="size_ne_sw")
        b_ne.place(relx=1.0, x=-cs, y=0, width=cs, height=cs)
        
        # Bottom-Left Corner
        b_sw = tk.Frame(self.root, bg=color, cursor="size_ne_sw")
        b_sw.place(x=0, rely=1.0, y=-cs, width=cs, height=cs)
        
        # Bottom-Right Corner
        b_se = tk.Frame(self.root, bg=color, cursor="size_nw_se")
        b_se.place(relx=1.0, x=-cs, rely=1.0, y=-cs, width=cs, height=cs)
        
        # Map handles to directions
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
        
        # Horizontal resizing
        if "e" in self.resize_direction:
            new_w = max(310, min(900, self.resize_start_w + dx))
        elif "w" in self.resize_direction:
            target_w = self.resize_start_w - dx
            new_w = max(310, min(900, target_w))
            new_x = self.resize_start_win_x + (self.resize_start_w - new_w)
            
        # Vertical resizing
        if "s" in self.resize_direction:
            new_h = max(360, min(1000, self.resize_start_h + dy))
        elif "n" in self.resize_direction:
            target_h = self.resize_start_h - dy
            new_h = max(360, min(1000, target_h))
            new_y = self.resize_start_win_y + (self.resize_start_h - new_h)
            
        self.win_width = new_w
        self.win_height = new_h
        self.root.geometry(f"{new_w}x{new_h}+{new_x}+{new_y}")

    def stop_resize(self, event):
        if self.is_resizing:
            self.is_resizing = False
            self.mouse_is_down_inside = False
            self.last_interaction_time = time.time()
            self.config["win_width"] = self.win_width
            self.config["win_height"] = self.win_height
            save_config(self.config)

    def build_cards(self):
        # Card 1: Gemini Models
        self.gemini_card, self.gemini_widgets = self.create_group_card(
            title="Gemini Models",
            subtitle="Gemini Flash, Gemini Pro",
            badge_color="#38bdf8"
        )
        self.gemini_card.pack(fill="both", expand=True, pady=(0, 10))
        
        # Card 2: Claude & GPT Models
        self.claude_card, self.claude_widgets = self.create_group_card(
            title="Claude & GPT Models",
            subtitle="Claude Opus, Claude Sonnet, GPT-OSS",
            badge_color="#f59e0b"
        )
        self.claude_card.pack(fill="both", expand=True)

    def create_group_card(self, title, subtitle, badge_color):
        # Card container with glass acrylic styling
        card = tk.Frame(self.cards_frame, bg="#182234", padx=12, pady=10)
        
        # Header row
        head_row = tk.Frame(card, bg="#182234")
        head_row.pack(fill="x", pady=(0, 6))
        
        badge = tk.Frame(head_row, bg=badge_color, width=9, height=9)
        badge.pack(side="left", padx=(0, 7), pady=(3, 0))
        
        t_box = tk.Frame(head_row, bg="#182234")
        t_box.pack(side="left")
        
        t_lbl = tk.Label(t_box, text=title, font=("Segoe UI", 11, "bold"), fg="#f8fafc", bg="#182234")
        t_lbl.pack(anchor="w")
        s_lbl = tk.Label(t_box, text=subtitle, font=("Segoe UI", 8), fg="#94a3b8", bg="#182234")
        s_lbl.pack(anchor="w")
        
        # 5-Hour Bucket
        b5_row = tk.Frame(card, bg="#182234")
        b5_row.pack(fill="x", pady=(3, 2))
        b5_title = tk.Label(b5_row, text="5-Stunden-Limit", font=("Segoe UI", 10, "bold"), fg="#cbd5e1", bg="#182234")
        b5_title.pack(side="left")
        b5_pct = tk.Label(b5_row, text="--%", font=("Segoe UI", 13, "bold"), fg="#f8fafc", bg="#182234")
        b5_pct.pack(side="right")
        
        b5_bar = RoundedProgressBar(card, height=8, bg_color="#182234", trough_color="#26344d")
        b5_bar.pack(fill="x", pady=(0, 2))
        
        b5_reset = tk.Label(card, text="Reset: --", font=("Segoe UI", 9), fg="#94a3b8", bg="#182234")
        b5_reset.pack(anchor="w", pady=(0, 5))
        
        # Separator line
        sep = tk.Frame(card, bg="#26344d", height=1)
        sep.pack(fill="x", pady=(0, 5))
        
        # Weekly Bucket
        bw_row = tk.Frame(card, bg="#182234")
        bw_row.pack(fill="x", pady=(2, 2))
        bw_title = tk.Label(bw_row, text="Wöchentliches Limit", font=("Segoe UI", 10, "bold"), fg="#cbd5e1", bg="#182234")
        bw_title.pack(side="left")
        bw_pct = tk.Label(bw_row, text="--%", font=("Segoe UI", 13, "bold"), fg="#f8fafc", bg="#182234")
        bw_pct.pack(side="right")
        
        bw_bar = RoundedProgressBar(card, height=8, bg_color="#182234", trough_color="#26344d")
        bw_bar.pack(fill="x", pady=(0, 2))
        
        bw_reset = tk.Label(card, text="Reset: --", font=("Segoe UI", 9), fg="#94a3b8", bg="#182234")
        bw_reset.pack(anchor="w")
        
        widgets = {
            "card": card,
            "title": t_lbl,
            "sub": s_lbl,
            "5h_title": b5_title,
            "5h_pct": b5_pct,
            "5h_bar": b5_bar,
            "5h_reset": b5_reset,
            "w_title": bw_title,
            "w_pct": bw_pct,
            "w_bar": bw_bar,
            "w_reset": bw_reset,
        }
        return card, widgets

    def bind_events(self):
        # Drag window anywhere by header or title
        def start_move(event):
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

        for w in (self.header, self.title_box, self.title_lbl, self.sub_lbl):
            w.bind("<Button-1>", start_move)
            w.bind("<B1-Motion>", do_move)
            w.bind("<ButtonRelease-1>", stop_move)
            w.bind("<Double-Button-1>", lambda e: self.reset_to_tray())

        # Responsive scaling on resize
        self.root.bind("<Configure>", self.on_window_configure)

        # Escape key closes window
        self.root.bind("<Escape>", lambda e: self.hide_window())

    def on_window_configure(self, event):
        """Dynamically scales paddings and font sizes so nothing is ever cropped."""
        if event.widget != self.root:
            return
        
        w = event.width
        h = event.height
        compact = h < 440 or w < 350
        
        if compact:
            t_font = ("Segoe UI", 10, "bold")
            s_font = ("Segoe UI", 8)
            bt_font = ("Segoe UI", 9, "bold")
            pct_font = ("Segoe UI", 11, "bold")
            rst_font = ("Segoe UI", 8)
            bar_h = 6
        else:
            t_font = ("Segoe UI", 12, "bold")
            s_font = ("Segoe UI", 9)
            bt_font = ("Segoe UI", 10, "bold")
            pct_font = ("Segoe UI", 13, "bold")
            rst_font = ("Segoe UI", 9)
            bar_h = 8
            
        for card_widgets in (self.gemini_widgets, self.claude_widgets):
            try:
                card_widgets["title"].config(font=t_font)
                card_widgets["sub"].config(font=s_font)
                card_widgets["5h_title"].config(font=bt_font)
                card_widgets["5h_pct"].config(font=pct_font)
                card_widgets["5h_reset"].config(font=rst_font)
                card_widgets["5h_bar"].set_height(bar_h)
                card_widgets["w_title"].config(font=bt_font)
                card_widgets["w_pct"].config(font=pct_font)
                card_widgets["w_reset"].config(font=rst_font)
                card_widgets["w_bar"].set_height(bar_h)
            except Exception:
                pass

    # Reliable check for clicking outside the window (30ms interval)
    def _poll_click_outside(self):
        if self.is_open and not self.pinned:
            # Under NO circumstance close while dragging, resizing, or when mouse was pressed inside
            if self.is_dragging or self.is_resizing or self.mouse_is_down_inside:
                self.root.after(30, self._poll_click_outside)
                return
            
            # Debounce right after opening
            if time.time() - self.open_timestamp < 0.3:
                self.root.after(30, self._poll_click_outside)
                return
            if time.time() - self.last_interaction_time < 0.35:
                self.root.after(30, self._poll_click_outside)
                return

            # Check mouse button states: 0x01 = VK_LBUTTON, 0x02 = VK_RBUTTON
            l_down = ctypes.windll.user32.GetAsyncKeyState(0x01) & 0x8000
            r_down = ctypes.windll.user32.GetAsyncKeyState(0x02) & 0x8000
            
            if l_down or r_down:
                pt = wintypes.POINT()
                ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
                wx = self.root.winfo_x()
                wy = self.root.winfo_y()
                ww = self.root.winfo_width()
                wh = self.root.winfo_height()
                
                # 20px margin around window bounds ensures all border resize handles are safe
                margin = 20
                is_inside = (wx - margin <= pt.x <= wx + ww + margin) and (wy - margin <= pt.y <= wy + wh + margin)
                
                if is_inside:
                    self.mouse_is_down_inside = True
                else:
                    # User clicked outside!
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
        
        # 1. Update countdown labels in real-time down to the second
        if self.latest_data and self.is_open:
            self._update_countdown_labels()
        
        # 2. Seamless status handling:
        # Live badge stays ● LIVE as long as data was received in the last 15s.
        # Only switch to ● OFFLINE if no signal for > 15 seconds!
        if self.last_successful_fetch > 0:
            elapsed = now_ts - self.last_successful_fetch
            if elapsed > 15:
                self.live_badge.config(text="● OFFLINE", fg="#ef4444", bg="#450a0a")
                self.status_lbl.config(text="Kein Signal (>15s)", fg="#ef4444")
            else:
                self.live_badge.config(text="● LIVE", fg="#10b981", bg="#064e3b")
                self.status_lbl.config(text="Live synchronisiert", fg="#94a3b8")
        
        # 3. Live Auto-Refresh logic:
        # When window is open: silent background refresh every 10 seconds.
        # When window is closed: background refresh every 60 seconds.
        interval = self.config.get("live_refresh_seconds", 10) if self.is_open else self.config.get("background_refresh_seconds", 60)
        if not self.is_fetching and (now_ts - self.last_fetch_start >= interval):
            self.trigger_refresh(silent=True)
            
        self.root.after(1000, self._tick_live)

    def _update_countdown_labels(self):
        for key, target_info in self.bucket_reset_targets.items():
            widget = target_info.get("widget")
            target_dt = target_info.get("target_dt")
            fraction = target_info.get("fraction", 1.0)
            if widget and target_dt:
                countdown_text = format_countdown_seconds(target_dt, fraction)
                widget.config(text=countdown_text)

    def toggle_pin(self):
        self.pinned = not self.pinned
        self.config["pinned"] = self.pinned
        save_config(self.config)
        self.pin_btn.config(
            text="📌" if self.pinned else "📍",
            fg="#38bdf8" if self.pinned else "#94a3b8"
        )
        if self.pinned:
            self.sub_lbl.config(text="Angepinnt • Bleibt als Floating-Widget offen")
        else:
            self.sub_lbl.config(text="Floating Window • An Rändern skalierbar")

    def reset_to_tray(self):
        """Docks the window back above the system tray and restores standard size."""
        self.config["custom_pos"] = False
        self.config["pos_x"] = None
        self.config["pos_y"] = None
        self.win_width = 390
        self.win_height = 510
        self.config["win_width"] = 390
        self.config["win_height"] = 510
        save_config(self.config)
        self.position_window()

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
        
        # Only change refresh button text if user clicked manually
        if not silent:
            self.refresh_btn.config(text="⌛ Lade...", fg="#94a3b8")
            
        threading.Thread(target=self._fetch_worker, daemon=True).start()

    def _fetch_worker(self):
        data, err = fetch_usage_data()
        self.post(self._on_fetch_complete, data, err)

    def _on_fetch_complete(self, data, err):
        self.is_fetching = False
        self.refresh_btn.config(text="🔄 Aktualisieren", fg="#f8fafc")
        
        if err or not data:
            if time.time() - self.last_successful_fetch > 15:
                self.status_lbl.config(text="Kein Signal • Timeout", fg="#ef4444")
                self.live_badge.config(text="● OFFLINE", fg="#ef4444", bg="#450a0a")
            print(f"Fetch error: {err}")
            return
        
        self.latest_data = data
        self.last_successful_fetch = time.time()
        self.status_lbl.config(text="Live synchronisiert", fg="#94a3b8")
        self.live_badge.config(text="● LIVE", fg="#10b981", bg="#064e3b")
        
        self.update_ui_cards(data)
        self.update_tray_state(data)

    def update_ui_cards(self, data):
        groups = data.get("groups", [])
        for group in groups:
            g_name = group.get("name", "")
            buckets = group.get("buckets", [])
            
            target_widgets = None
            group_key = ""
            if "Gemini" in g_name:
                target_widgets = self.gemini_widgets
                group_key = "gemini"
            elif "Claude" in g_name or "GPT" in g_name:
                target_widgets = self.claude_widgets
                group_key = "claude"
            
            if not target_widgets:
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
                color = get_color_for_fraction(frac)
                
                if "5h" in b_id:
                    target_widgets["5h_pct"].config(text=pct_str, fg=color)
                    target_widgets["5h_bar"].set_value(frac)
                    self.bucket_reset_targets[f"{group_key}_5h"] = {
                        "widget": target_widgets["5h_reset"],
                        "target_dt": target_dt,
                        "fraction": frac
                    }
                    target_widgets["5h_reset"].config(text=format_countdown_seconds(target_dt, frac))
                elif "weekly" in b_id:
                    target_widgets["w_pct"].config(text=pct_str, fg=color)
                    target_widgets["w_bar"].set_value(frac)
                    self.bucket_reset_targets[f"{group_key}_weekly"] = {
                        "widget": target_widgets["w_reset"],
                        "target_dt": target_dt,
                        "fraction": frac
                    }
                    target_widgets["w_reset"].config(text=format_countdown_seconds(target_dt, frac))

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

    # Tray Menu (Right-Click Menu, while Left-Click opens/closes flyout)
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
