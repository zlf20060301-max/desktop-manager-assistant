# 打包成独立 exe（不依赖 Python 环境）
# 用法：  .\build.ps1
# 产物：  dist\桌面管理助手\桌面管理助手.exe

$ErrorActionPreference = 'Stop'
$ROOT = $PSScriptRoot
Set-Location $ROOT

$PY = Join-Path $ROOT '.venv\Scripts\python.exe'
if (-not (Test-Path $PY)) {
    Write-Host '[错误] 找不到 .venv，请先运行 安装依赖.cmd' -ForegroundColor Red
    exit 1
}

$ICON = Join-Path $ROOT 'assets\icon.ico'
if (-not (Test-Path $ICON)) {
    Write-Host '[1/3] 图标不存在，先生成 ...'
    & $PY (Join-Path $ROOT 'tools\make_icon.py')
}

Write-Host '[2/3] 清理旧产物 ...'
foreach ($d in @('build', 'dist')) {
    $p = Join-Path $ROOT $d
    if (Test-Path $p) { Remove-Item $p -Recurse -Force }
}

Write-Host '[3/3] PyInstaller 打包中（首次约 2-5 分钟）...'

# 只保留真正用到的 Qt 模块，其余全部排除，能省下 100MB 以上
$EXCLUDES = @(
    'tkinter', 'unittest', 'pydoc_data', 'test',
    'numpy', 'pandas', 'PIL', 'matplotlib', 'scipy',
    'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.QtWebEngineQuick',
    'PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.QtQuick3D', 'PySide6.QtQuickWidgets',
    'PySide6.Qt3DCore', 'PySide6.Qt3DRender', 'PySide6.Qt3DInput', 'PySide6.Qt3DLogic',
    'PySide6.Qt3DAnimation', 'PySide6.Qt3DExtras',
    'PySide6.QtMultimedia', 'PySide6.QtMultimediaWidgets',
    'PySide6.QtCharts', 'PySide6.QtDataVisualization', 'PySide6.QtGraphs',
    'PySide6.QtBluetooth', 'PySide6.QtNfc', 'PySide6.QtPositioning',
    'PySide6.QtSerialPort', 'PySide6.QtSensors', 'PySide6.QtSerialBus',
    'PySide6.QtDesigner', 'PySide6.QtHelp', 'PySide6.QtUiTools', 'PySide6.QtTest',
    'PySide6.QtSql', 'PySide6.QtOpenGL', 'PySide6.QtOpenGLWidgets',
    'PySide6.QtPdf', 'PySide6.QtPdfWidgets', 'PySide6.QtSpatialAudio',
    'PySide6.QtRemoteObjects', 'PySide6.QtScxml', 'PySide6.QtStateMachine',
    'PySide6.QtTextToSpeech', 'PySide6.QtWebChannel', 'PySide6.QtWebSockets',
    'PySide6.QtHttpServer', 'PySide6.QtNetworkAuth'
)

$args = @(
    '-m', 'PyInstaller',
    '--noconfirm', '--clean',
    '--name', '桌面管理助手',
    '--icon', $ICON,
    '--noconsole',
    '--onedir',
    '--noupx',
    '--optimize', '1'
)
foreach ($e in $EXCLUDES) { $args += @('--exclude-module', $e) }
$args += 'main.py'

& $PY @args
if ($LASTEXITCODE -ne 0) {
    Write-Host '[错误] 打包失败' -ForegroundColor Red
    exit $LASTEXITCODE
}

$exe = Join-Path $ROOT 'dist\桌面管理助手\桌面管理助手.exe'
if (-not (Test-Path $exe)) {
    Write-Host "[错误] 没有找到产物 $exe" -ForegroundColor Red
    exit 1
}

$size = (Get-ChildItem (Join-Path $ROOT 'dist\桌面管理助手') -Recurse -File |
         Measure-Object Length -Sum).Sum / 1MB
Write-Host ''
Write-Host ('打包完成：{0}' -f $exe) -ForegroundColor Green
Write-Host ('产物体积：{0:N1} MB' -f $size) -ForegroundColor Green
