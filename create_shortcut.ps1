# Create desktop shortcut for CC-Toolbox (no-window launcher: pythonw + launch_w.pyw)
# Called by the one-time setup bat; can also be run alone.
# NOTE: keep this file ASCII-only. PowerShell 5.1 reads .ps1 as ANSI on Chinese
# Windows (GBK), so any UTF-8 Chinese comment would break parsing.
$ErrorActionPreference = 'Stop'
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$desktop = [Environment]::GetFolderPath('Desktop')
$venvPythonw = Join-Path $scriptDir 'venv\Scripts\pythonw.exe'
$launcherPy = Join-Path $scriptDir 'launch_w.pyw'
$iconFile = Join-Path $scriptDir 'static\app_icon.ico'

if (-not (Test-Path $venvPythonw)) {
    Write-Output "[ERROR] venv not found: $venvPythonw"
    Write-Output "        Run launcher.bat once to finish setup first."
    exit 1
}
if (-not (Test-Path $launcherPy)) {
    Write-Output "[ERROR] launch_w.pyw not found."
    exit 1
}
if (-not (Test-Path $iconFile)) {
    Write-Output "[WARN] Icon file missing, shortcut will use default icon: $iconFile"
}

$wsh = New-Object -ComObject WScript.Shell
$shortcut = $wsh.CreateShortcut("$desktop\CC-Toolbox.lnk")
$shortcut.TargetPath = $venvPythonw
$shortcut.Arguments = 'launch_w.pyw'
$shortcut.WorkingDirectory = $scriptDir
$shortcut.Description = 'CC-Toolbox - Claude Code Toolbox (double-click to start/stop)'
$shortcut.IconLocation = "$iconFile,0"
$shortcut.WindowStyle = 7
$shortcut.HotKey = 'Ctrl+Alt+T'
$shortcut.Save()

Write-Output "[OK] Desktop shortcut created: $desktop\CC-Toolbox.lnk"
