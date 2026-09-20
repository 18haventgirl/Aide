@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0启动Aide.ps1"
exit /b %ERRORLEVEL%
