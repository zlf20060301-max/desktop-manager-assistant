@echo off
chcp 65001 >nul
setlocal
set "ROOT=%~dp0"
cd /d "%ROOT%"

echo ============================================
echo   桌面管家 - 安装 / 修复运行环境
echo ============================================
echo.

where py >nul 2>nul
if errorlevel 1 (
    echo [错误] 未找到 Python 启动器 py.exe，请先安装 Python 3.10 或更高版本。
    echo        下载地址：https://www.python.org/downloads/
    pause
    exit /b 1
)

if not exist "%ROOT%.venv\Scripts\python.exe" (
    echo [1/3] 创建虚拟环境 .venv ...
    py -3.10 -m venv .venv
    if errorlevel 1 (
        echo [错误] 虚拟环境创建失败。
        pause
        exit /b 1
    )
) else (
    echo [1/3] 虚拟环境已存在，跳过。
)

echo [2/3] 升级 pip ...
"%ROOT%.venv\Scripts\python.exe" -m pip install --upgrade pip -q

echo [3/3] 安装 PySide6（约 250MB，请耐心等待）...
"%ROOT%.venv\Scripts\python.exe" -m pip install -r "%ROOT%requirements.txt" -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn
if errorlevel 1 (
    echo.
    echo [提示] 清华镜像安装失败，尝试官方源 ...
    "%ROOT%.venv\Scripts\python.exe" -m pip install -r "%ROOT%requirements.txt"
)

echo.
echo 安装完成！现在可以双击「启动桌面管家.cmd」运行。
pause
