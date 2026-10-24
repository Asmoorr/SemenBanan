$ErrorActionPreference = 'Stop'
$semyonPidFile = Join-Path $PSScriptRoot '.runtime.pid'
if (Test-Path -LiteralPath $semyonPidFile) {
    $semyonPid = [int](Get-Content -LiteralPath $semyonPidFile)
    $semyonProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $semyonPid" -ErrorAction SilentlyContinue
    if ($semyonProcess -and $semyonProcess.CommandLine -like "*$PSScriptRoot*" -and ($semyonProcess.CommandLine -like "*-m semen_banan*" -or $semyonProcess.CommandLine -like "*\bot.py*" )) {
        # Stop the venv launcher, the bot, and an active audio worker together.
        & "$env:SystemRoot\System32\taskkill.exe" /PID $semyonPid /T /F | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Failed to stop the SemenBanan process tree.' }
        Write-Host 'Semyon stopped.'
    }
    Remove-Item -LiteralPath $semyonPidFile
} else {
    Write-Host 'For a bot started in a terminal, press Ctrl+C in that terminal.'
}
