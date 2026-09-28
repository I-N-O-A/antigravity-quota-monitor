$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ws = New-Object -ComObject WScript.Shell
$desk = [System.Environment]::GetFolderPath('Desktop')
$shortcutPath = Join-Path $desk "Antigravity Quota Monitor.lnk"

$s = $ws.CreateShortcut($shortcutPath)
$s.TargetPath = "wscript.exe"
$s.Arguments = "`"$scriptDir\start_silent.vbs`""
$s.WorkingDirectory = $scriptDir
$s.Description = "Live API Usage & Quota Tray Monitor for Antigravity"
$s.IconLocation = "$scriptDir\icon.ico"
$s.Save()

Write-Host "Desktop shortcut created successfully: $shortcutPath"
