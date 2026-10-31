param([Parameter(ValueFromRemainingArguments = $true)][string[]] $InputFiles)
$ErrorActionPreference = 'Stop'
$taskPython = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    & (Join-Path $PSScriptRoot 'setup.ps1')
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
& $taskPython (Join-Path $PSScriptRoot 'main.py') @InputFiles
exit $LASTEXITCODE
