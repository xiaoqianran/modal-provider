param(
    [Parameter(Mandatory = $true)]
    [string]$Worker
)

$workerPath = (Resolve-Path -LiteralPath $Worker -ErrorAction Stop).Path
if ([IO.Path]::GetExtension($workerPath) -ne ".py") {
    throw "Worker must be a Python file: $workerPath"
}

$rootPath = (Get-Location).Path
$relativePath = [IO.Path]::GetRelativePath($rootPath, $workerPath)
if ($relativePath.StartsWith("..")) {
    throw "Worker must be importable from the current project root: $workerPath"
}
$module = [IO.Path]::ChangeExtension($relativePath, $null).Replace("\", ".").Replace("/", ".")

& modal deploy -m $module
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

& modal run -m "${module}::register"
exit $LASTEXITCODE
