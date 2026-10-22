$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (Test-Path '.runtime.pid') {
    $semyonPid = [int](Get-Content '.runtime.pid')
    $semyonProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $semyonPid" -ErrorAction SilentlyContinue
    if ($semyonProcess -and $semyonProcess.CommandLine -like "*$PSScriptRoot\bot.py*") {
        Write-Host 'Semyon is already running. Use stop.ps1 first.'
        exit 0
    }
}
if (-not (Test-Path '.venv\Scripts\python.exe')) {
    py -3 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.10+ first.' }
    & '.\.venv\Scripts\python.exe' -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
}
if (-not (Test-Path '.env')) { Copy-Item '.env.example' '.env' }
& '.\.venv\Scripts\python.exe' bot.py @args
