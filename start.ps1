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
}
& '.\.venv\Scripts\python.exe' -c 'import importlib.util, sys; sys.exit(not all(importlib.util.find_spec(name) for name in ["httpx", "dotenv", "mido", "numpy", "onnxruntime"]))'
if ($LASTEXITCODE -ne 0) {
    & '.\.venv\Scripts\python.exe' -m pip install -r requirements-music.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
}
if (-not (Test-Path 'assets\nanomaestro\model.onnx') -or -not (Test-Path 'assets\TimGM6mb.sf2')) {
    & '.\.venv\Scripts\python.exe' setup_music.py
    if ($LASTEXITCODE -ne 0) { throw 'Music setup failed.' }
}
if (-not (Test-Path '.env')) { Copy-Item '.env.example' '.env' }
& '.\.venv\Scripts\python.exe' bot.py @args
