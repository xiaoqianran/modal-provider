param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("start", "stop")]
    [string]$Action,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$projectDir = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$stateDir = Join-Path $projectDir ".run"
$stateFile = Join-Path $stateDir "modal-gen.json"
$pythonPath = Join-Path $projectDir ".venv\Scripts\python.exe"

function Get-OwnedProcess {
    if (-not (Test-Path -LiteralPath $stateFile)) { return $null }
    $record = Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json
    $running = Get-Process -Id $record.processId -ErrorAction SilentlyContinue
    if ($null -eq $running) { return $null }
    $details = Get-CimInstance Win32_Process -Filter "ProcessId = $($record.processId)"
    if ($running.StartTime.ToUniversalTime().Ticks.ToString() -ne $record.startTicks -or
        $details.ExecutablePath -ne $pythonPath -or
        $details.CommandLine -notmatch " -m modal_gen\.launcher(?:\s|$)") {
        throw "Recorded PID belongs to another process. Refusing to control it."
    }
    return $running
}

if ($DryRun) {
    Write-Output "$Action local Connector + UI in $projectDir"
    Write-Output "Command: $pythonPath -m modal_gen.launcher"
    Write-Output "PID record: $stateFile"
    exit 0
}

$owned = Get-OwnedProcess
if ($Action -eq "stop") {
    if ($null -ne $owned) {
        Stop-Process -Id $owned.Id
        $owned.WaitForExit()
        Write-Output "Stopped modal-gen PID $($owned.Id). Cloud Apps are unaffected."
    } else {
        Write-Output "No process started by start.bat is running."
    }
    if (Test-Path -LiteralPath $stateFile) {
        Remove-Item -LiteralPath $stateFile
    }
    exit 0
}

if ($null -ne $owned) {
    Write-Output "modal-gen is already running, PID $($owned.Id)."
    exit 0
}
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Python environment missing. Run start.bat or uv sync first."
}
New-Item -ItemType Directory -Path $stateDir -Force | Out-Null
$started = Start-Process -FilePath $pythonPath -ArgumentList @("-m", "modal_gen.launcher") `
    -WorkingDirectory $projectDir -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $stateDir "stdout.log") `
    -RedirectStandardError (Join-Path $stateDir "stderr.log")
$startTicks = $started.StartTime.ToUniversalTime().Ticks.ToString()
@{ processId = $started.Id; startTicks = $startTicks } |
    ConvertTo-Json | Set-Content -LiteralPath $stateFile -Encoding UTF8
Start-Sleep -Milliseconds 1500
$started.Refresh()
if ($started.HasExited) {
    Remove-Item -LiteralPath $stateFile
    throw "modal-gen exited during startup. See .run\stderr.log."
}
$uiPort = if ($env:MODAL_GEN_UI_PORT) { $env:MODAL_GEN_UI_PORT } else { "48124" }
Write-Output "Started modal-gen PID $($started.Id). Console: http://127.0.0.1:$uiPort/"
Write-Output "Logs: $stateDir"
