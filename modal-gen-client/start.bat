@echo off
setlocal EnableExtensions
cd /d "%~dp0"
if /I "%~1"=="--dry-run" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts/local-process.ps1" -Action start -DryRun
  exit /b
)
where uv >nul 2>nul || (
  echo ERROR: uv is required.
  exit /b 1
)
uv sync --frozen
if errorlevel 1 exit /b 1
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts/local-process.ps1" -Action start
exit /b %ERRORLEVEL%
