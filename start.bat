@echo off
setlocal
if exist "%~dp0logs\aide.cmd" (
  call "%~dp0logs\aide.cmd" %*
  exit /b %ERRORLEVEL%
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0启动Aide.ps1"
exit /b %ERRORLEVEL%
