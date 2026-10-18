# 创建 CC-Toolbox 桌面快捷方式（相对路径，随仓库移动可用）
$desktop = [Environment]::GetFolderPath('Desktop')
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$wsh = New-Object -ComObject WScript.Shell
$shortcut = $wsh.CreateShortcut("$desktop\CC-Toolbox.lnk")

# 目标：启动 bat（相对本仓库）
$shortcut.TargetPath = Join-Path $scriptDir "launcher.bat"
$shortcut.WorkingDirectory = $scriptDir
$shortcut.Description = "CC-Toolbox · Claude Code 工具箱管理器"
$shortcut.IconLocation = Join-Path $scriptDir "static\favicon.ico"

# 快捷键 Ctrl+Alt+T
$shortcut.HotKey = "Ctrl+Alt+T"

$shortcut.WindowStyle = 1  # 1=普通, 3=最大化, 7=最小化
$shortcut.Save()

Write-Output "快捷方式已创建: $desktop\CC-Toolbox.lnk"
