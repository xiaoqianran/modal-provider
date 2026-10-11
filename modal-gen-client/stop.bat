@echo off
setlocal EnableExtensions
cd /d "%~dp0"
if /I "%~1"=="--dry-run" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts/local-process.ps1" -Action stop -DryRun
  exit /b
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts/local-process.ps1" -Action stop
exit /b %ERRORLEVEL%
