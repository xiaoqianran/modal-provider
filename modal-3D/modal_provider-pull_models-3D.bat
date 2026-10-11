@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "DRY_RUN=0"
if /I "%~1"=="--dry-run" set "DRY_RUN=1"

where uv >nul 2>nul || (
  echo [modal-3D] ERROR: uv is not available on PATH.
  exit /b 1
)

echo [modal-3D] Pulling model weights into provider-owned Modal Volumes...

call :sync modal_3d.rembg_worker || exit /b 1
call :sync modal_3d.fastsam3d_plus_plus || exit /b 1
call :sync modal_3d.hunyuan2_1_plus_plus || exit /b 1
call :sync modal_3d.hermit_trellis2_plus_plus || exit /b 1
call :sync modal_3d.pixal3d || exit /b 1
call :sync modal_3d.p3sam_worker || exit /b 1
call :sync modal_3d.xpart_worker || exit /b 1
call :sync modal_3d.hunyuan_paint_worker || exit /b 1
call :sync modal_3d.hunyuan2mv_worker || exit /b 1
call :sync modal_3d.tokenrig_worker || exit /b 1

echo [modal-3D] Model pull complete. Weightless mesh/pose workers need no model download.
exit /b 0

:sync
set "MODULE=%~1"
echo [modal-3D] ^> %MODULE%::sync_weights
if "%DRY_RUN%"=="1" (
  echo   uv run modal run -m %MODULE%::sync_weights
  exit /b 0
)
uv run modal run -m %MODULE%::sync_weights
exit /b %ERRORLEVEL%
