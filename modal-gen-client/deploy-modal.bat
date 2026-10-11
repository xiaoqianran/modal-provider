@echo off
setlocal EnableExtensions
cd /d "%~dp0"
where uv >nul 2>nul || (
  echo ERROR: uv is required.
  exit /b 1
)
uv run python -m modal_gen.deployment.cli deploy %*
exit /b %ERRORLEVEL%
