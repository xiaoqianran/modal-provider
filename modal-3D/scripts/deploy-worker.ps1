param(
    [Parameter(Mandatory = $true)]
    [string]$Worker
)

$workerPath = (Resolve-Path -LiteralPath $Worker -ErrorAction Stop).Path
if ([IO.Path]::GetExtension($workerPath) -ne ".py") {
    throw "Worker must be a Python file: $workerPath"
}

$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$repoPrefix = $repoRoot.TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
if (-not $workerPath.StartsWith($repoPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Worker must be inside the repository: $workerPath"
}
$relativePath = $workerPath.Substring($repoPrefix.Length)
$extension = [IO.Path]::GetExtension($relativePath)
$relativeModulePath = $relativePath.Substring(0, $relativePath.Length - $extension.Length)
$module = $relativeModulePath -replace '[\\/]', '.'

$uvArgs = @(
    "run",
    "--isolated",
    "--frozen",
    "--default-index", "https://pypi.org/simple"
)

# Modal CLI emits Unicode status glyphs. Force Python UTF-8 mode so Windows
# PowerShell 5.1 on GBK/ACP locales cannot fail while printing deployment logs.
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

Push-Location $repoRoot
try {
    & uv @uvArgs modal run -e main -m "${module}::sync_weights"
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
    # There is no registry step. Deploy the selected worker module directly;
    # the client resolves generation/mask workers from local static configuration.
    & uv @uvArgs modal deploy -e main -m $module
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
