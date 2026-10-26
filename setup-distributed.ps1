param([switch]$SkipInstall)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$pythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Create .venv and install requirements.txt first.' }
if (-not $SkipInstall) {
    & $pythonPath -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
}
& $pythonPath -m sagsin.database
if ($LASTEXITCODE -ne 0) { throw 'Start MySQL and check DATABASE_URL / MYSQL_ADMIN_USER / MYSQL_ADMIN_PASSWORD, then retry.' }
Write-Host 'Ready. Restart backend.main:app and use the existing FL Training screen.'
