# 在桌面创建 CC-Toolbox 快捷方式（无窗口启动：pythonw + launch_w.pyw）
# 由「一键安装并创建桌面图标.bat」调用，也可单独运行
$ErrorActionPreference = 'Stop'
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$desktop = [Environment]::GetFolderPath('Desktop')
$venvPythonw = Join-Path $scriptDir 'venv\Scripts\pythonw.exe'
$launcherPy = Join-Path $scriptDir 'launch_w.pyw'
$iconFile = Join-Path $scriptDir 'static\favicon.ico'

if (-not (Test-Path $venvPythonw)) {
    Write-Output "[ERROR] venv not found: $venvPythonw"
    Write-Output "        Run launcher.bat once to finish setup first."
    exit 1
}
if (-not (Test-Path $launcherPy)) {
    Write-Output "[ERROR] launch_w.pyw not found."
    exit 1
}

$wsh = New-Object -ComObject WScript.Shell
$shortcut = $wsh.CreateShortcut("$desktop\CC-Toolbox.lnk")
$shortcut.TargetPath = $venvPythonw
$shortcut.Arguments = 'launch_w.pyw'
$shortcut.WorkingDirectory = $scriptDir
$shortcut.Description = 'CC-Toolbox · Claude Code 工具箱管理器（双击启动/停止）'
$shortcut.IconLocation = "$iconFile,0"
$shortcut.WindowStyle = 7   # 7=最小化（pythonw 本身无窗口）
$shortcut.HotKey = 'Ctrl+Alt+T'
$shortcut.Save()

Write-Output "[OK] Desktop shortcut created: $desktop\CC-Toolbox.lnk"
