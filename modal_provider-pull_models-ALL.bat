@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "ARGS=%*"

echo ============================================================
echo modal-provider model pull
echo ============================================================

echo.
echo [1/3] modal-2D
call "%~dp0modal-2D\modal_provider-pull_models-2D.bat" %ARGS%
if errorlevel 1 goto :failed

echo.
echo [2/3] modal-3D
call "%~dp0modal-3D\modal_provider-pull_models-3D.bat" %ARGS%
if errorlevel 1 goto :failed

echo.
echo [3/3] modal-world
call "%~dp0modal-world\modal_provider-pull_models-WORLD.bat" %ARGS%
if errorlevel 1 goto :failed

echo.
echo ============================================================
echo All provider model pulls completed successfully.
echo ============================================================
exit /b 0

:failed
echo.
echo ERROR: model pull stopped because one provider failed.
exit /b 1
