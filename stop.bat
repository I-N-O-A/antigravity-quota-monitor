@echo off
echo Stopping Antigravity Quota Monitor...
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"CommandLine LIKE '%%agy_tray.py%%'\" | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
echo Stopped.
