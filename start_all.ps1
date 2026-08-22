$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$FrontendRoot = Join-Path $ProjectRoot "frontend"

if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw "Python was not found in PATH." }
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { throw "Node.js was not found in PATH." }

Write-Host "Checking AmbiSense dependencies..." -ForegroundColor Cyan
python -c "import fastapi, uvicorn, sqlalchemy, cv2, torch" 2>$null
if ($LASTEXITCODE -ne 0) { python -m pip install -r (Join-Path $ProjectRoot "backend\requirements.txt") }
if (-not (Test-Path (Join-Path $FrontendRoot "node_modules"))) { Push-Location $FrontendRoot; npm install; Pop-Location }

Write-Host "Starting AmbiSense backend..." -ForegroundColor Green
$Backend = Start-Process python -ArgumentList "-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1", "--port", "8000" -WorkingDirectory $ProjectRoot -WindowStyle Hidden -PassThru
Write-Host "Starting AmbiSense dashboard..." -ForegroundColor Green
$Frontend = Start-Process npm.cmd -ArgumentList "run", "dev" -WorkingDirectory $FrontendRoot -WindowStyle Hidden -PassThru

Write-Host ""
Write-Host "AmbiSense Backend:  http://localhost:8000"
Write-Host "API Docs:           http://localhost:8000/docs"
Write-Host "AmbiSense Dashboard: http://localhost:5173"
Write-Host "Backend PID: $($Backend.Id) | Frontend PID: $($Frontend.Id)"
Write-Host "Stop with: Stop-Process -Id $($Backend.Id),$($Frontend.Id)"
