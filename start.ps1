$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$semyonBackground = $args -contains '-Background'
$semyonBotArgs = @($args | Where-Object { $_ -ne '-Background' })
$semyonDiagnostic = @($semyonBotArgs | Where-Object { $_ -in @('--check', '--check-gateway', '--check-music', '--help', '-h') }).Count -gt 0
if ($semyonBackground -and $semyonBotArgs.Count -gt 0) { throw 'Run diagnostic modes in the foreground.' }
$env:SEMEN_BANAN_HOME = $PSScriptRoot
if (-not $semyonDiagnostic -and (Test-Path '.runtime.pid')) {
    $semyonPid = [int](Get-Content '.runtime.pid')
    $semyonProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $semyonPid" -ErrorAction SilentlyContinue
    if ($semyonProcess -and $semyonProcess.CommandLine -like "*$PSScriptRoot*" -and ($semyonProcess.CommandLine -like "*-m semen_banan*" -or $semyonProcess.CommandLine -like "*\bot.py*" )) {
        Write-Host 'Semyon is already running. Use stop.ps1 first.'
        exit 0
    }
}
if (-not (Test-Path '.venv\Scripts\python.exe')) {
    py -3.13 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.13 first.' }
}
& '.\.venv\Scripts\python.exe' -c "import sys; sys.exit(sys.version_info[:2] != (3, 13))"
if ($LASTEXITCODE -ne 0) { throw 'This project requires Python 3.13.' }
& '.\.venv\Scripts\python.exe' -c "import importlib.util, sys; sys.exit(not all(importlib.util.find_spec(name) for name in 'semen_banan httpx dotenv mido numpy onnxruntime piper'.split()))"
if ($LASTEXITCODE -ne 0) {
    & '.\.venv\Scripts\python.exe' -m pip install -r requirements-music.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
}
if (-not (Test-Path 'assets\nanomaestro\model.onnx') -or -not (Test-Path 'assets\GeneralUser-GS.sf2') -or -not (Test-Path 'assets\speech\denis.onnx.json')) {
    & '.\.venv\Scripts\python.exe' tools/setup_assets.py
    if ($LASTEXITCODE -ne 0) { throw 'Music setup failed.' }
}
if (-not (Test-Path '.env')) { Copy-Item '.env.example' '.env' }
if ($semyonBackground) {
    $semyonRuntime = Join-Path $PSScriptRoot '.runtime'
    New-Item -ItemType Directory -Path $semyonRuntime -Force | Out-Null
    $semyonPython = (Resolve-Path '.venv\Scripts\python.exe').Path
    $semyonArguments = @('-X', 'utf8', '-u', '-m', 'semen_banan') + $semyonBotArgs
    $semyonProcess = Start-Process -FilePath $semyonPython -ArgumentList $semyonArguments -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $semyonRuntime 'stdout.log') -RedirectStandardError (Join-Path $semyonRuntime 'stderr.log') -PassThru
    Set-Content -LiteralPath (Join-Path $PSScriptRoot '.runtime.pid') -Value $semyonProcess.Id
    Write-Host "SemenBanan started in background. PID: $($semyonProcess.Id)"
} else {
    & '.\.venv\Scripts\python.exe' -X utf8 -m semen_banan @semyonBotArgs
    exit $LASTEXITCODE
}
