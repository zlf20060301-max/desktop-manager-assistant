@echo off
chcp 65001 >nul
setlocal
set "ROOT=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%installer\install.ps1" %*
echo.
pause
