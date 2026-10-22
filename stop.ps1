$ErrorActionPreference = 'Stop'
$semyonPidFile = Join-Path $PSScriptRoot '.runtime.pid'
if (Test-Path -LiteralPath $semyonPidFile) {
    $semyonPid = [int](Get-Content -LiteralPath $semyonPidFile)
    $semyonProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $semyonPid" -ErrorAction SilentlyContinue
    if ($semyonProcess -and $semyonProcess.CommandLine -like "*$PSScriptRoot\bot.py*") {
        Stop-Process -Id $semyonPid
        Write-Host 'Semyon stopped.'
    }
    Remove-Item -LiteralPath $semyonPidFile
} else {
    Write-Host 'For a bot started in a terminal, press Ctrl+C in that terminal.'
}
