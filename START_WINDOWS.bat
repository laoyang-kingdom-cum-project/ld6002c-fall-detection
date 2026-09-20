@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

if exist "%~dp0deploy\windows\config.cmd" call "%~dp0deploy\windows\config.cmd"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy\windows\start.ps1"
set "START_EXIT_CODE=%ERRORLEVEL%"

if not "%START_EXIT_CODE%"=="0" (
    echo.
    echo Startup failed. Review the error above.
    pause
)

exit /b %START_EXIT_CODE%
