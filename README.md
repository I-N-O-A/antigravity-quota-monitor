# Antigravity Quota Monitor

A lightweight, modern Windows System Tray utility for real-time monitoring of your Google Antigravity (`agy`) API quotas and model group limits (Gemini Flash/Pro, Claude Sonnet/Opus, GPT-OSS).

Featuring a heavily curved Windows 11 **Glassmorphism / Acrylic UI**, draggable **Floating Window**, seamless multi-border resizing, **real-time second-by-second countdowns**, and **auto-close on click-outside**.

---

## 🤖 Install with Agent (Prompt)

Copy the following prompt and hand it directly to your AI agent (in OpenCode, Cursor, Claude Code, Windsurf, or Antigravity CLI):

```text
Install and start the Antigravity Quota Monitor for Windows:
1. Clone the repository into my user profile directory:
   git clone https://github.com/I-N-O-A/antigravity-quota-monitor.git "%USERPROFILE%\antigravity-quota-monitor"
2. Switch to the directory:
   cd "%USERPROFILE%\antigravity-quota-monitor"
3. Install required Python packages:
   pip install -r requirements.txt
4. Start the tool silently in the background:
   wscript.exe start_silent.vbs
5. Create a desktop shortcut:
   powershell -NoProfile -ExecutionPolicy Bypass -File create_desktop_shortcut.ps1
Finally, verify that the process is running in the background with 'Get-Process pythonw'.
```

---

## 🛠️ Manual Installation

### Requirements
* **Operating System**: Windows 10 or Windows 11
* **Python**: Python 3.10 or higher (added to Windows PATH)
* **Antigravity CLI**: `agy` installed and logged in (`agy -p "/usage"` returns quotas)

### Step 1: Clone Repository
Open PowerShell or Command Prompt (CMD):
```powershell
git clone https://github.com/I-N-O-A/antigravity-quota-monitor.git
cd antigravity-quota-monitor
```

### Step 2: Install Dependencies
```powershell
pip install -r requirements.txt
```
*(Installs `PyQt5` for native Windows 11 frosted acrylic glass with smooth rounded corners, and `Pillow` for dynamic high-DPI tray icon generation).*

### Step 3: Start Application
* **Silently in the background (no console window)**:
  Double-click `start_silent.vbs`
* **Or with starter script**:
  Double-click `start.bat`
* **Create Desktop Shortcut (Optional)**:
  Double-click `create_desktop_shortcut.bat`

---

## 🎮 Controls & Features

| Action | Feature |
| :--- | :--- |
| **Left-click on Tray Icon** | Toggles the quota dashboard open or closed. |
| **No Intrusive Tooltip** | Hovering mouse over the icon does not show annoying tooltips. |
| **Windows 11 Glass UI** | Heavily rounded frosted glass aesthetics with centered AG monogram ring icon. |
| **Floating Window Drag** | Click and drag anywhere on the header bar to position the window freely. |
| **Seamless Border Resizing** | Drag any of the 4 borders or 4 corners to resize smoothly (no indicator lines/boxes). |
| **Dynamic Responsive Scaling & Scroll** | Font sizes scale adaptively with an integrated scrollbar when the window is compact. |
| **Auto-Close on Click Outside** | Clicking anywhere outside the window closes the dashboard automatically. |
| **Pin / Sticky Mode** | Click `📌` in the header to pin the window as a persistent floating widget. |
| **Live Countdowns** | 5-hour and weekly reset countdowns tick every second with exact local reset timestamps. |
| **Real-time Live Sync** | Seamless live polling every 10s while open, displaying a calm `● LIVE` badge. |
| **Right-click on Tray Icon** | Context menu with options: *Open Dashboard*, *Refresh Now*, *Dock to Tray*, *Start with Windows*, *Exit*. |

> **💡 Windows 11 Tray Tip:** If the tray icon is placed in the hidden notification area by default, click the upward arrow (`^`) next to the clock and drag the `AG` icon onto your visible taskbar.
>
> **💡 Desktop Shortcut Tip:** Double-clicking the "Antigravity Quota Monitor" desktop shortcut instantly brings the dashboard into view, even when running silently in the background.

---

## ⚙️ Windows Autostart
Right-click the tray icon in your taskbar and select **Start with Windows**. The tool will launch automatically on login.

---

## 🛑 Exit Application
* Via Tray Icon: Right-click -> **Exit**
* Or via script: Double-click `stop.bat`

---

## 📄 License
MIT License. Free to use and modify.
