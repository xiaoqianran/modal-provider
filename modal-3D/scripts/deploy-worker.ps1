param(
    [Parameter(Mandatory = $true)]
    [string]$Worker
)

$workerPath = (Resolve-Path -LiteralPath $Worker -ErrorAction Stop).Path
if ([IO.Path]::GetExtension($workerPath) -ne ".py") {
    throw "Worker must be a Python file: $workerPath"
}

$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$relativePath = [IO.Path]::GetRelativePath($repoRoot, $workerPath)
if ($relativePath.StartsWith("..")) {
    throw "Worker must be inside the repository: $workerPath"
}
$module = [IO.Path]::ChangeExtension($relativePath, $null) -replace '[\\/]', '.'

Push-Location $repoRoot
try {
    & uv run modal run -m "${module}::sync_weights"
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
    # There is no registry step. Deploy the selected worker module directly;
    # the client resolves generation/mask workers from local static configuration.
    & uv run modal deploy -m $module
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
