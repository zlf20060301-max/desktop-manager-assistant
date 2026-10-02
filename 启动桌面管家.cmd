@echo off
chcp 65001 >nul
setlocal
set "ROOT=%~dp0"
set "PY=%ROOT%.venv\Scripts\pythonw.exe"

if not exist "%PY%" (
    echo.
    echo   [未找到运行环境] 请先双击运行「安装依赖.cmd」
    echo.
    pause
    exit /b 1
)

start "" "%PY%" "%ROOT%main.py"
exit /b 0
