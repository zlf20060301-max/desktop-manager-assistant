# 桌面管理助手 —— 卸载脚本
#
# 由安装目录里的「卸载.cmd」调用，或被 Windows「应用和功能」调用。
# 只删除自己安装的东西：安装目录、两个快捷方式、注册表项。
# 用户数据（%APPDATA%\桌面管理助手）默认保留，会单独询问。

[CmdletBinding()]
param(
    [switch]$Quiet,          # 静默卸载，占位
    [switch]$RemoveUserData  # 连同配置一起删（不询问）
)

$ErrorActionPreference = 'Continue'
$APP_NAME = '桌面管理助手'
$EXE_NAME = "$APP_NAME.exe"

$InstallDir = $PSScriptRoot
$UserDataDir = Join-Path $env:APPDATA $APP_NAME

function Write-Ok($t) { Write-Host "    $t" -ForegroundColor Green }
function Write-Info($t) { Write-Host "    $t" -ForegroundColor Gray }

# ---------- 安全校验：确认这确实是我们的安装目录 ----------
if (-not (Test-Path (Join-Path $InstallDir $EXE_NAME))) {
    Write-Host ''
    Write-Host "  [中止] 当前目录里没有 $EXE_NAME，看起来不是 $APP_NAME 的安装目录。" -ForegroundColor Red
    Write-Host "         为避免误删，脚本已停止。目录：$InstallDir" -ForegroundColor Red
    Write-Host ''
    exit 1
}

Write-Host ''
Write-Host '============================================' -ForegroundColor White
Write-Host "   卸载 $APP_NAME" -ForegroundColor White
Write-Host '============================================' -ForegroundColor White
Write-Host ''
Write-Info "程序目录：$InstallDir"
Write-Info "配置数据：$UserDataDir"
Write-Host ''

if (-not $Quiet) {
    $ans = Read-Host "确认卸载 $APP_NAME 吗？[y/N]"
    if ($ans -notmatch '^[Yy]') { Write-Host '已取消。' ; exit 0 }
}

# ---------- 关掉正在运行的实例 ----------
$running = Get-Process -Name ($EXE_NAME -replace '\.exe$', '') -ErrorAction SilentlyContinue |
           Where-Object { $_.Path -and $_.Path.StartsWith($InstallDir, 'OrdinalIgnoreCase') }
if ($running) {
    Write-Info "关闭 $($running.Count) 个正在运行的实例"
    $running | Stop-Process -Force
    Start-Sleep -Milliseconds 800
}

# ---------- 用户数据 ----------
$deleteUserData = $RemoveUserData
if (-not $Quiet -and -not $RemoveUserData -and (Test-Path $UserDataDir)) {
    $a = Read-Host '要一起删掉你的配置和操作记录吗？（删除后就无法撤销之前的操作了）[y/N]'
    if ($a -match '^[Yy]') { $deleteUserData = $true }
}

# ---------- 快捷方式 ----------
$startMenuLnk = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\$APP_NAME.lnk"
$desktopLnk = Join-Path ([Environment]::GetFolderPath('Desktop')) "$APP_NAME.lnk"
foreach ($lnk in @($startMenuLnk, $desktopLnk)) {
    if (Test-Path $lnk) { Remove-Item $lnk -Force; Write-Ok "已删除快捷方式 $lnk" }
}

# ---------- 注册表 ----------
$regKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\$APP_NAME"
if (Test-Path $regKey) { Remove-Item $regKey -Recurse -Force; Write-Ok '已从「应用和功能」移除' }

# ---------- 用户数据 ----------
if ($deleteUserData -and (Test-Path $UserDataDir)) {
    Remove-Item $UserDataDir -Recurse -Force -ErrorAction SilentlyContinue
    Write-Ok "已删除配置数据 $UserDataDir"
} elseif (Test-Path $UserDataDir) {
    Write-Info "已保留配置数据：$UserDataDir"
    Write-Info '（重新安装后会继续沿用，想手动删掉随时可以）'
}

# ---------- 删除程序目录 ----------
# 脚本自己就在这个目录里，不一定能把自己删干净：
# 先直接删一遍（绝大多数文件都能删掉），剩下的交给一个隐藏进程稍后清理。
Remove-Item -LiteralPath $InstallDir -Recurse -Force -ErrorAction SilentlyContinue

if (Test-Path $InstallDir) {
    # 用 -EncodedCommand 传脚本：Start-Process 不会给参数补引号，
    # 中文或带空格的路径直接拼进命令行会被拆坏。
    $escaped = $InstallDir.Replace("'", "''")
    $script = "Start-Sleep -Seconds 2; Remove-Item -LiteralPath '$escaped' -Recurse -Force -ErrorAction SilentlyContinue"
    $encoded = [Convert]::ToBase64String([System.Text.Encoding]::Unicode.GetBytes($script))
    Start-Process -FilePath 'powershell.exe' `
        -ArgumentList '-NoProfile', '-WindowStyle', 'Hidden', '-EncodedCommand', $encoded `
        -WindowStyle Hidden | Out-Null
}

Write-Host ''
Write-Host "   $APP_NAME 已卸载。" -ForegroundColor Green
Write-Host '   程序目录会在几秒内自动消失。' -ForegroundColor Green
Write-Host ''
