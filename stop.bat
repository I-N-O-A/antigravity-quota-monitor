@echo off
echo Stopping Antigravity Quota Tray...
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*agy_tray.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
echo Stopped.
