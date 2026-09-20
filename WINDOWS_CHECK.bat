@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

if exist "%~dp0deploy\windows\config.cmd" call "%~dp0deploy\windows\config.cmd"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy\windows\doctor.ps1"
set "CHECK_EXIT_CODE=%ERRORLEVEL%"

echo.
pause
exit /b %CHECK_EXIT_CODE%
