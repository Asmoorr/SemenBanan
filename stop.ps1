$ErrorActionPreference = 'Stop'
$semyonPidFile = Join-Path $PSScriptRoot '.runtime.pid'
if (Test-Path -LiteralPath $semyonPidFile) {
    $semyonPid = [int](Get-Content -LiteralPath $semyonPidFile)
    $semyonProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $semyonPid" -ErrorAction SilentlyContinue
    if ($semyonProcess -and $semyonProcess.CommandLine -like "*$PSScriptRoot*" -and ($semyonProcess.CommandLine -like "*-m semen_banan*" -or $semyonProcess.CommandLine -like "*\bot.py*" )) {
        # Останавливаем окружение, бота и текущий аудиогенератор вместе.
        & "$env:SystemRoot\System32\taskkill.exe" /PID $semyonPid /T /F | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Не удалось остановить дерево процессов Семёна.' }
        Write-Host 'Семён остановлен.'
    }
    Remove-Item -LiteralPath $semyonPidFile
} else {
    Write-Host 'Для остановки бота, запущенного в терминале, нажми в нём Ctrl+C.'
}
