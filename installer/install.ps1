# 桌面管理助手 —— 安装脚本
#
# 按用户安装（不需要管理员权限）：程序装到 %LOCALAPPDATA%\Programs\桌面管理助手
# 用户数据（配置、撤销台账）单独放在 %APPDATA%\桌面管理助手，卸载时可选择保留。
#
# 用法：
#   powershell -ExecutionPolicy Bypass -File installer\install.ps1
#   powershell -ExecutionPolicy Bypass -File installer\install.ps1 -NoDesktopShortcut

[CmdletBinding()]
param(
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA 'Programs\桌面管理助手'),
    [switch]$NoDesktopShortcut,
    [switch]$NoStartMenuShortcut,
    [switch]$NoLaunch
)

$ErrorActionPreference = 'Stop'
$ROOT = Split-Path -Parent $PSScriptRoot          # installer\ 的上一级 = 项目根
$APP_NAME = '桌面管理助手'
$PUBLISHER = 'zlf20060301-max'
$EXE_NAME = "$APP_NAME.exe"

function Write-Step($n, $text) { Write-Host "[$n] $text" -ForegroundColor Cyan }
function Write-Ok($text) { Write-Host "    $text" -ForegroundColor Green }
function Write-Info($text) { Write-Host "    $text" -ForegroundColor Gray }

# --------------------------------------------------------------------------
Write-Host ''
Write-Host '============================================' -ForegroundColor White
Write-Host "   $APP_NAME — 安装到本机" -ForegroundColor White
Write-Host '============================================' -ForegroundColor White
Write-Host ''

# ---------- 1. 版本号（从 app\__init__.py 读，保持单一来源）----------
Write-Step '1/6' '读取版本信息'
$initFile = Join-Path $ROOT 'app\__init__.py'
$Version = '0.1.0'
if (Test-Path $initFile) {
    $line = Get-Content $initFile | Where-Object { $_ -match '__version__' } | Select-Object -First 1
    if ($line -match '(\d+\.\d+\.\d+)') { $Version = $Matches[1] }
}
Write-Ok "版本 $Version"

# ---------- 2. 检查打包产物 ----------
Write-Step '2/6' '检查打包产物'
$DistDir = Join-Path $ROOT "dist\$APP_NAME"
$DistExe = Join-Path $DistDir $EXE_NAME
if (-not (Test-Path $DistExe)) {
    Write-Host "    找不到 $DistExe" -ForegroundColor Yellow
    $ans = Read-Host '    要现在打包吗？（约 2-5 分钟）[Y/n]'
    if ($ans -eq '' -or $ans -match '^[Yy]') {
        & (Join-Path $ROOT 'build.ps1')
        if (-not (Test-Path $DistExe)) { throw '打包后仍未找到 exe，已中止' }
    } else {
        throw '请先运行 build.ps1 完成打包'
    }
}
$srcSize = (Get-ChildItem $DistDir -Recurse -File | Measure-Object Length -Sum).Sum / 1MB
Write-Ok ('产物就绪，{0:N1} MB' -f $srcSize)

# ---------- 3. 关掉正在运行的旧版本 ----------
Write-Step '3/6' '检查是否有旧版本在运行'
$running = Get-Process -Name ($EXE_NAME -replace '\.exe$', '') -ErrorAction SilentlyContinue |
           Where-Object { $_.Path -and $_.Path.StartsWith($InstallDir, 'OrdinalIgnoreCase') }
if ($running) {
    Write-Info "关闭 $($running.Count) 个正在运行的实例"
    $running | Stop-Process -Force
    Start-Sleep -Milliseconds 800
} else {
    Write-Ok '没有正在运行的实例'
}

# ---------- 4. 复制文件 ----------
Write-Step '4/6' "复制到 $InstallDir"
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null

# robocopy 的 0-7 都算成功（1=有复制，2=有额外文件，3=两者都有）
$null = robocopy $DistDir $InstallDir /MIR /NFL /NDL /NJH /NJS /NP /R:2 /W:1
if ($LASTEXITCODE -ge 8) { throw "复制文件失败，robocopy 退出码 $LASTEXITCODE" }

# 卸载器一起放进安装目录
Copy-Item (Join-Path $PSScriptRoot 'uninstall.ps1') $InstallDir -Force
Copy-Item (Join-Path $PSScriptRoot '卸载.cmd') $InstallDir -Force

$installedSize = (Get-ChildItem $InstallDir -Recurse -File | Measure-Object Length -Sum).Sum / 1MB
Write-Ok ('已安装 {0:N1} MB' -f $installedSize)

# ---------- 5. 快捷方式 ----------
Write-Step '5/6' '创建快捷方式'
$InstalledExe = Join-Path $InstallDir $EXE_NAME
$ws = New-Object -ComObject WScript.Shell

function New-Shortcut($path, $desc) {
    $dir = Split-Path -Parent $path
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    $lnk = $ws.CreateShortcut($path)
    $lnk.TargetPath = $InstalledExe
    $lnk.WorkingDirectory = $InstallDir
    $lnk.IconLocation = "$InstalledExe,0"
    $lnk.Description = $desc
    $lnk.Save()
    Write-Ok $path
}

if (-not $NoStartMenuShortcut) {
    $startMenu = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'
    New-Shortcut (Join-Path $startMenu "$APP_NAME.lnk") "$APP_NAME — 桌面文档管理" | Out-Null
}
if (-not $NoDesktopShortcut) {
    $desktop = [Environment]::GetFolderPath('Desktop')
    New-Shortcut (Join-Path $desktop "$APP_NAME.lnk") "$APP_NAME — 桌面文档管理" | Out-Null
}

# ---------- 6. 注册到「应用和功能」----------
Write-Step '6/6' '注册卸载信息'
$regKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\$APP_NAME"
New-Item -Path $regKey -Force | Out-Null

$uninstallCmd = 'cmd.exe /c ""{0}""' -f (Join-Path $InstallDir '卸载.cmd')
$props = @{
    DisplayName     = $APP_NAME
    DisplayVersion  = $Version
    Publisher       = $PUBLISHER
    DisplayIcon     = "$InstalledExe,0"
    InstallLocation = "$InstallDir\"
    UninstallString = $uninstallCmd
    InstallDate     = (Get-Date -Format 'yyyyMMdd')
    NoModify        = 1
    NoRepair        = 1
    EstimatedSize   = [int]($installedSize * 1024)
}
foreach ($k in $props.Keys) {
    Set-ItemProperty -Path $regKey -Name $k -Value $props[$k]
}
Write-Ok "已注册：设置 → 应用 → 已安装的应用"

# ---------- 完成 ----------
Write-Host ''
Write-Host '============================================' -ForegroundColor Green
Write-Host "   安装完成！$APP_NAME $Version" -ForegroundColor Green
Write-Host '============================================' -ForegroundColor Green
Write-Host ''
Write-Info "程序位置：$InstallDir"
Write-Info '开始菜单和桌面都有快捷方式了'
Write-Info "卸载：设置 → 应用 → 已安装的应用 → $APP_NAME（会问你要不要保留配置）"
Write-Host ''

if (-not $NoLaunch) {
    $ans = Read-Host '现在就启动吗？[Y/n]'
    if ($ans -eq '' -or $ans -match '^[Yy]') {
        Start-Process $InstalledExe
        Write-Ok '已启动'
    }
}
