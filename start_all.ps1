<#
  Starts the AmbiSense API and dashboard for local development.

    .\start_all.ps1                       # API on 8000, dashboard on 5173 (or the next free ports)
    .\start_all.ps1 -BackendPort 8010 -FrontendPort 5180

  It never kills anything: if a port is taken it picks the next free one and tells you. Logs go to logs\,
  process IDs to logs\pids.json (stop with .\stop_all.ps1). Requires Python and Node.js on PATH; installs
  dependencies only if they are missing.
#>
param([int]$BackendPort = 8000, [int]$FrontendPort = 5173, [string]$BindAddress = "127.0.0.1")
$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$FrontendRoot = Join-Path $ProjectRoot "frontend"
$LogDir = Join-Path $ProjectRoot "logs"
New-Item -ItemType Directory -Force $LogDir | Out-Null

function Test-PortFree([int]$Port) {
    return -not (Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
}
function Get-FreePort([int]$Preferred, [string]$Label) {
    $port = $Preferred
    while (-not (Test-PortFree $port)) { $port++ }
    if ($port -ne $Preferred) { Write-Host "$Label port $Preferred is in use by another process; using $port instead." -ForegroundColor Yellow }
    return $port
}

if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw "Python was not found in PATH." }
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { throw "Node.js was not found in PATH." }

Write-Host "Checking AmbiSense dependencies..." -ForegroundColor Cyan
python -c "import fastapi, uvicorn, sqlalchemy, cv2, torch" 2>$null
if ($LASTEXITCODE -ne 0) { python -m pip install -r (Join-Path $ProjectRoot "backend\requirements.txt") }
if (-not (Test-Path (Join-Path $FrontendRoot "node_modules"))) { Push-Location $FrontendRoot; npm.cmd install; Pop-Location }

$BackendPort = Get-FreePort $BackendPort "Backend"
$FrontendPort = Get-FreePort $FrontendPort "Frontend"

Write-Host "Starting AmbiSense backend..." -ForegroundColor Green
$Backend = Start-Process python -ArgumentList "-m", "uvicorn", "backend.app.main:app", "--host", $BindAddress, "--port", $BackendPort `
    -WorkingDirectory $ProjectRoot -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $LogDir "backend.out.log") -RedirectStandardError (Join-Path $LogDir "backend.err.log")

Write-Host "Starting AmbiSense dashboard..." -ForegroundColor Green
$env:VITE_BACKEND_URL = "http://${BindAddress}:$BackendPort"   # the dev server proxies /api and /ws here
$Frontend = Start-Process npm.cmd -ArgumentList "run", "dev", "--", "--host", $BindAddress, "--port", $FrontendPort, "--strictPort" `
    -WorkingDirectory $FrontendRoot -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $LogDir "frontend.out.log") -RedirectStandardError (Join-Path $LogDir "frontend.err.log")

@{ backend = $Backend.Id; frontend = $Frontend.Id; backend_port = $BackendPort; frontend_port = $FrontendPort; started = (Get-Date).ToString("o") } |
    ConvertTo-Json | Set-Content (Join-Path $LogDir "pids.json") -Encoding utf8

# Wait until the API answers (model imports can take a while) so the printed URLs are real.
$healthy = $false
for ($i = 0; $i -lt 90 -and -not $healthy; $i++) {
    Start-Sleep -Seconds 2
    try { $healthy = (Invoke-WebRequest "http://${BindAddress}:$BackendPort/api/health" -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200 } catch { $healthy = $false }
    if ($Backend.HasExited) { throw "The backend exited early; see logs\backend.err.log" }
}

Write-Host ""
Write-Host "AmbiSense API:       http://${BindAddress}:$BackendPort  (health: $(if ($healthy) { 'OK' } else { 'not answering yet - check logs\backend.err.log' }))"
Write-Host "API docs:            http://${BindAddress}:$BackendPort/docs"
Write-Host "AmbiSense dashboard: http://${BindAddress}:$FrontendPort"
Write-Host "Backend PID: $($Backend.Id) | Frontend PID: $($Frontend.Id)"
Write-Host "Stop with: .\stop_all.ps1"
