param([string] $NsisCompiler = '')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$taskPython = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    throw 'Run setup.ps1 first to create the project Python environment.'
}
& $taskPython -m pip install --disable-pip-version-check --progress-bar off --timeout 30 --retries 2 -r (Join-Path $PSScriptRoot 'requirements-build.txt')
if ($LASTEXITCODE -ne 0) { throw 'Build dependency installation failed.' }
if (-not $NsisCompiler) {
    $taskBundledCompiler = Join-Path $PSScriptRoot '.build-tools/nsis-3.12/makensis.exe'
    if (Test-Path -LiteralPath $taskBundledCompiler) { $NsisCompiler = $taskBundledCompiler }
    else {
        $taskSystemCompiler = Get-Command makensis.exe -ErrorAction SilentlyContinue
        if ($taskSystemCompiler) { $NsisCompiler = $taskSystemCompiler.Source }
    }
}
if (-not $NsisCompiler -or -not (Test-Path -LiteralPath $NsisCompiler)) {
    throw 'NSIS was not found. Install NSIS 3.12 or pass -NsisCompiler with the path to makensis.exe.'
}
$env:PYINSTALLER_CONFIG_DIR = Join-Path $PSScriptRoot '.build-tools/pyinstaller-cache'
& $taskPython -m PyInstaller --noconfirm --clean (Join-Path $PSScriptRoot 'packaging/product-desk.spec')
if ($LASTEXITCODE -ne 0) { throw 'Application build failed.' }
& $taskPython (Join-Path $PSScriptRoot 'packaging/collect_notices.py')
if ($LASTEXITCODE -ne 0) { throw 'Dependency notice collection failed.' }
& $taskPython (Join-Path $PSScriptRoot 'packaging/make_manifest.py')
if ($LASTEXITCODE -ne 0) { throw 'Uninstall manifest generation failed.' }
& $NsisCompiler /V3 /INPUTCHARSET UTF8 "/DPROJECT_ROOT=$PSScriptRoot" (Join-Path $PSScriptRoot 'packaging/installer.nsi')
if ($LASTEXITCODE -ne 0) { throw 'Installer build failed.' }
Write-Host 'Installer is ready in dist.'
