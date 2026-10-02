@echo off
chcp 65001 >nul
setlocal
set "ROOT=%~dp0"
set "PY=%ROOT%.venv\Scripts\python.exe"

if not exist "%PY%" (
    echo.
    echo   [未找到运行环境] 请先双击运行「安装依赖.cmd」
    echo.
    pause
    exit /b 1
)

echo 正在以调试模式启动（关闭窗口即退出，错误会显示在此）...
"%PY%" "%ROOT%main.py"
echo.
echo 程序已退出，退出码 %ERRORLEVEL%
pause
