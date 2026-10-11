@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "DRY_RUN=0"
if /I "%~1"=="--dry-run" set "DRY_RUN=1"

where uv >nul 2>nul || (
  echo [modal-2D] ERROR: uv is not available on PATH.
  exit /b 1
)

echo [modal-2D] Pulling model weights into Modal Volume modal-2d-models...

call :prefetch sana-sprint-0.6b || exit /b 1
call :prefetch sana-sprint-1.6b || exit /b 1
call :prefetch qwen-image-2512 || exit /b 1
call :prefetch z-image-turbo || exit /b 1
call :prefetch hidream-o1-image || exit /b 1

echo [modal-2D] Model pull complete.
exit /b 0

:prefetch
set "MODEL_ID=%~1"
echo [modal-2D] ^> %MODEL_ID%
if "%DRY_RUN%"=="1" (
  echo   uv run modal run -m modal_2d.app::prefetch --model-id "%MODEL_ID%"
  exit /b 0
)
uv run modal run -m modal_2d.app::prefetch --model-id "%MODEL_ID%"
exit /b %ERRORLEVEL%
