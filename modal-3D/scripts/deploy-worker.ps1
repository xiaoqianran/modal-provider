param(
    [Parameter(Mandatory = $true)]
    [string]$Worker
)

$workerPath = (Resolve-Path -LiteralPath $Worker -ErrorAction Stop).Path
if ([IO.Path]::GetExtension($workerPath) -ne ".py") {
    throw "Worker must be a Python file: $workerPath"
}

& modal deploy $Worker
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

& modal run "${Worker}::register"
exit $LASTEXITCODE
