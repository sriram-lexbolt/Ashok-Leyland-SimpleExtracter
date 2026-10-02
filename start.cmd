@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" -OpenBrowser %*
set "launcherExit=%ERRORLEVEL%"
if not "%launcherExit%"=="0" (
    echo.
    echo The application could not start. Review the error above.
    pause
)
exit /b %launcherExit%
