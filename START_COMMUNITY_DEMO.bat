@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

if exist "%~dp0deploy\windows\config.cmd" call "%~dp0deploy\windows\config.cmd"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy\windows\start-community-demo.ps1" %*
set "DEMO_EXIT_CODE=%ERRORLEVEL%"

if not "%DEMO_EXIT_CODE%"=="0" (
    echo.
    echo Community demo failed. Review the error above.
    pause
)

exit /b %DEMO_EXIT_CODE%
