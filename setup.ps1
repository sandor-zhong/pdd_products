$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$taskPython = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    $taskCandidates = @()
    $taskVersionDir = Join-Path $env:USERPROFILE '.pyenv/pyenv-win/versions'
    if (Test-Path -LiteralPath $taskVersionDir) {
        $taskCandidates += Get-ChildItem -LiteralPath $taskVersionDir -Directory | Sort-Object Name -Descending | ForEach-Object { Join-Path $_.FullName 'python.exe' }
    }
    $taskCommand = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($taskCommand) { $taskCandidates += $taskCommand.Source }
    $taskCandidates += Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
    $taskSelected = $null
    foreach ($taskCandidate in $taskCandidates) {
        if (Test-Path -LiteralPath $taskCandidate) {
            & $taskCandidate -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>$null
            if ($LASTEXITCODE -eq 0) { $taskSelected = $taskCandidate; break }
        }
    }
    if (-not $taskSelected) { throw 'Python 3.10+ was not found. Install Python, then run setup.ps1 again.' }
    & $taskSelected -m venv (Join-Path $PSScriptRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Failed to create the virtual environment.' }
}
& $taskPython -m pip install --timeout 30 --retries 2 -r (Join-Path $PSScriptRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Check the network and run setup.ps1 again.' }
Write-Host 'Ready. Double-click start.bat to open the application.'
