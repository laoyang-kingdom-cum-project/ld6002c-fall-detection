@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

if exist "%~dp0deploy\windows\config.cmd" call "%~dp0deploy\windows\config.cmd"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy\windows\install-offline.ps1" %*
set "INSTALL_EXIT_CODE=%ERRORLEVEL%"

echo.
if not "%INSTALL_EXIT_CODE%"=="0" echo Installation failed. Review the error above.
pause
exit /b %INSTALL_EXIT_CODE%
