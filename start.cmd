@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
set "workbenchExit=%ERRORLEVEL%"
pause
exit /b %workbenchExit%
