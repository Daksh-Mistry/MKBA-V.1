@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\bootstrap_windows.ps1" %*
set "ROBO_EXIT=%ERRORLEVEL%"
if not "%ROBO_EXIT%"=="0" (
  echo.
  echo Robo could not finish starting. Read the error above, then run this file again.
  pause
)
exit /b %ROBO_EXIT%
