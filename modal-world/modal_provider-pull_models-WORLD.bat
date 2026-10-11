@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "DRY_RUN=0"
if /I "%~1"=="--dry-run" set "DRY_RUN=1"

where uv >nul 2>nul || (
  echo [modal-world] ERROR: uv is not available on PATH.
  exit /b 1
)

echo [modal-world] Pulling HY-World 2.0 model caches into Modal Volume hyworld2-models...

call :run preload_worldnav_stage1_weights || exit /b 1
call :run verify_worldnav_stage1_cache || exit /b 1
call :run preload_worldstereo_stage3_weights || exit /b 1
call :run verify_worldstereo_stage3_cache || exit /b 1

echo [modal-world] Model pull and offline-cache verification complete.
exit /b 0

:run
set "FUNCTION=%~1"
echo [modal-world] ^> modal_world.app::%FUNCTION%
if "%DRY_RUN%"=="1" (
  echo   uv run modal run -m modal_world.app::%FUNCTION%
  exit /b 0
)
uv run modal run -m modal_world.app::%FUNCTION%
exit /b %ERRORLEVEL%
