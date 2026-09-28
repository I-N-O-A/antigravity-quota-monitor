# Antigravity Quota Monitor

Ein leichtgewichtiges, modernes Windows System-Tray-Tool zur Echtzeit-Überwachung deiner Google Antigravity (`agy`) API-Quoten und Modell-Limits (Gemini Flash/Pro, Claude Sonnet/Opus, GPT-OSS).

Mit frei verschiebbarem **Floating Window**, stufenloser **Größenanpassung (Resize)**, **sekundengenauem Live-Countdown** und **automatischem Zuklappen** bei Klick außerhalb.

---

## 🤖 Installiere mit Agenten (Prompt)

Kopiere einfach den folgenden Prompt und gib ihn deinem KI-Agenten (z. B. in OpenCode, Cursor, Claude Code, Windsurf oder Antigravity CLI):

```text
Installiere und starte den Antigravity Quota Monitor für Windows:
1. Klone das Repository in mein Benutzerverzeichnis:
   git clone https://github.com/I-N-O-A/antigravity-quota-monitor.git "%USERPROFILE%\antigravity-quota-monitor"
2. Wechsle in das Verzeichnis:
   cd "%USERPROFILE%\antigravity-quota-monitor"
3. Installiere die benötigten Python-Pakete:
   pip install -r requirements.txt
4. Starte das Tool lautlos im Hintergrund:
   wscript.exe start_silent.vbs
5. Erstelle eine Verknüpfung auf dem Desktop:
   powershell -NoProfile -ExecutionPolicy Bypass -File create_desktop_shortcut.ps1
Prüfe abschließend mit 'Get-Process pythonw', ob der Prozess aktiv im Hintergrund läuft.
```

---

## 🛠️ Manuelle Installation

### Voraussetzungen
* **Betriebssystem**: Windows 10 oder Windows 11
* **Python**: Python 3.10 oder höher (im Windows-PATH)
* **Antigravity CLI**: `agy` installiert und eingeloggt (`agy -p "/usage"` liefert Quoten)

### Schritt 1: Repository klonen
Öffne PowerShell oder die Eingabeaufforderung (CMD):
```powershell
git clone https://github.com/I-N-O-A/antigravity-quota-monitor.git
cd antigravity-quota-monitor
```

### Schritt 2: Abhängigkeiten installieren
```powershell
pip install -r requirements.txt
```
*(Installiert `pystray` für das Windows-Tray-Icon und `Pillow` für die dynamische Ringanzeige).*

### Schritt 3: Starten
* **Lautlos im Hintergrund (ohne Konsolenfenster)**:
  Doppelklick auf `start_silent.vbs`
* **Alternativ mit Starter**:
  Doppelklick auf `start.bat`
* **Desktop-Verknüpfung erstellen (optional)**:
  Doppelklick auf `create_desktop_shortcut.bat`

---

## 🎮 Bedienung & Features

| Aktion | Funktion |
| :--- | :--- |
| **Linksklick auf Tray-Icon** | Öffnet oder schließt das Quota-Dashboard. |
| **Kein störender Tooltip** | Hover mit der Maus über das Icon macht bewusst gar nichts. |
| **Verschieben (Floating Window)** | Klicke auf die obere Titelleiste und ziehe das Fenster an eine beliebige Stelle auf dem Bildschirm. |
| **Größe anpassen (Resize)** | Ziehe an der rechten unteren Ecke (`◢`), um Breite und Höhe frei anzupassen. |
| **Andocken (Reset)** | Doppelklick auf die Titelleiste oder Klick auf das Symbol `⤢` oben rechts dockt das Fenster wieder über der Windows-Taskleiste an. |
| **Automatisches Zuklappen** | Ein Klick außerhalb des Fensters schließt das Dashboard sofort automatisch. |
| **Anpinnen (Sticky Mode)** | Klick auf `📌` oben rechts hält das Fenster als dauerhaftes Floating-Widget immer im Vordergrund, ohne zuzuklappen. |
| **Live Countdown** | Die Reset-Zeiten der 5-Stunden- und Wochen-Limits zählen jede Sekunde live herunter. |
| **Echtzeit-Aktualisierung** | Solange das Dashboard geöffnet ist, aktualisiert es sich alle 10 Sekunden automatisch (oder sofort per Klick auf `🔄`). |
| **Rechtsklick auf Tray-Icon** | Öffnet das Kontextmenü mit Optionen wie *Dashboard öffnen*, *Jetzt live aktualisieren*, *Autostart mit Windows* und *Beenden*. |

---

## ⚙️ Autostart mit Windows
Klicke mit der rechten Maustaste auf das Tray-Icon in der Taskleiste und wähle **🚀 Autostart mit Windows**. Das Tool startet ab dann bei jeder Windows-Anmeldung automatisch im Hintergrund.

---

## 🛑 Tool beenden
* Über das Tray-Icon: Rechtsklick -> **❌ Beenden**
* Oder über das Skript: Doppelklick auf `stop.bat`

---

## 📄 Lizenz
MIT License. Frei verwendbar.
