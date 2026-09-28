@echo off
setlocal
cd /d "%~dp0"

:: 1. Try pythonw in PATH
where pythonw >nul 2>nul
if %errorlevel% equ 0 (
    start "" pythonw "%~dp0agy_tray.py"
    exit /b 0
)

:: 2. Try py -3w
where py >nul 2>nul
if %errorlevel% equ 0 (
    start "" py -3w "%~dp0agy_tray.py"
    exit /b 0
)

:: 3. Try standard Windows LocalAppData Python paths
if exist "%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe" (
    start "" "%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe" "%~dp0agy_tray.py"
    exit /b 0
)
if exist "%LOCALAPPDATA%\Programs\Python\Python311\pythonw.exe" (
    start "" "%LOCALAPPDATA%\Programs\Python\Python311\pythonw.exe" "%~dp0agy_tray.py"
    exit /b 0
)
if exist "%LOCALAPPDATA%\Programs\Python\Python313\pythonw.exe" (
    start "" "%LOCALAPPDATA%\Programs\Python\Python313\pythonw.exe" "%~dp0agy_tray.py"
    exit /b 0
)

:: 4. Fallback to python in PATH
where python >nul 2>nul
if %errorlevel% equ 0 (
    start "" python "%~dp0agy_tray.py"
    exit /b 0
)

echo [ERROR] Python was not found! Please install Python 3.10+ and add it to PATH.
pause
exit /b 1
