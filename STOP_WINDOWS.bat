@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

if exist "%~dp0deploy\windows\config.cmd" call "%~dp0deploy\windows\config.cmd"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy\windows\stop.ps1"
set "STOP_EXIT_CODE=%ERRORLEVEL%"

echo.
pause
exit /b %STOP_EXIT_CODE%
