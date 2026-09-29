<#
  Stops the processes started by start_all.ps1 (reads logs\pids.json). It only stops those two process trees
  and never touches anything else.
#>
$ErrorActionPreference = "Stop"
$File = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) "logs\pids.json"
if (-not (Test-Path $File)) { Write-Host "No logs\pids.json found: nothing to stop."; exit 0 }
$Pids = Get-Content $File -Raw | ConvertFrom-Json
foreach ($Name in "backend", "frontend") {
    $ProcessId = $Pids.$Name
    if ($ProcessId -and (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)) {
        & taskkill /PID $ProcessId /T /F | Out-Null   # /T also ends the child processes (npm -> node, uvicorn workers)
        Write-Host "Stopped $Name (PID $ProcessId)."
    } else {
        Write-Host "$Name (PID $ProcessId) is not running."
    }
}
Remove-Item $File
