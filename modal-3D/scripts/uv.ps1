param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$UvArgs
)

$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$env:UV_PROJECT_ENVIRONMENT = Join-Path $repoRoot ".venv-windows"
$env:UV_DEFAULT_INDEX = "https://pypi.org/simple"
$env:UV_LINK_MODE = "copy"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

Push-Location $repoRoot
try {
    & uv @UvArgs
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
