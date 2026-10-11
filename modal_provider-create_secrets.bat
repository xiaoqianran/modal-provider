@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "ENV_FILE=%~dp0.env"
set "MODAL_ENV=main"
if not "%MODAL_ENVIRONMENT%"=="" set "MODAL_ENV=%MODAL_ENVIRONMENT%"

if /I "%~1"=="--dry-run" goto :dryrun

where uv >nul 2>nul || (
  echo [modal-provider] ERROR: uv is not available on PATH.
  exit /b 1
)

if not exist "%ENV_FILE%" (
  echo [modal-provider] ERROR: .env not found.
  echo Copy .env.example to .env and set HF_TOKEN first.
  exit /b 1
)

set "TMP_HF=%TEMP%\modal-provider-hf-%RANDOM%-%RANDOM%.env"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$line = Get-Content -LiteralPath '%ENV_FILE%' ^| Where-Object { $_ -match '^\s*HF_TOKEN\s*=' } ^| Select-Object -First 1; if (-not $line) { exit 2 }; $value = ($line -replace '^\s*HF_TOKEN\s*=\s*','').Trim(); if (-not $value -or $value -eq 'hf_your_token_here') { exit 3 }; Set-Content -LiteralPath '%TMP_HF%' -Value ('HF_TOKEN=' + $value) -Encoding ascii"
if errorlevel 1 (
  echo [modal-provider] ERROR: HF_TOKEN is missing or still a placeholder in .env.
  if exist "%TMP_HF%" del /q "%TMP_HF%" >nul 2>nul
  exit /b 1
)

echo [modal-provider] Syncing Hugging Face credentials to Modal environment "%MODAL_ENV%"...

uv run --directory "%~dp0modal-gen-client" modal secret create -e "%MODAL_ENV%" --force --from-dotenv "%TMP_HF%" huggingface
if errorlevel 1 goto :failed

uv run --directory "%~dp0modal-gen-client" modal secret create -e "%MODAL_ENV%" --force --from-dotenv "%TMP_HF%" hyworld2-hf
if errorlevel 1 goto :failed

del /q "%TMP_HF%" >nul 2>nul

echo [modal-provider] Secrets ready: huggingface, hyworld2-hf
exit /b 0

:failed
if exist "%TMP_HF%" del /q "%TMP_HF%" >nul 2>nul
echo [modal-provider] ERROR: failed to create/update Modal secrets.
exit /b 1

:dryrun
echo [modal-provider] Dry run only. No credentials will be read or written.
echo   source: .env ^(HF_TOKEN only^)
echo   target environment: %MODAL_ENV%
echo   target secrets:
echo     - huggingface
 echo    - hyworld2-hf
exit /b 0
