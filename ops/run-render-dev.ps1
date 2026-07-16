# Run PJSK Render Service in dev mode on port 3001
# Usage: .\ops\run-render-dev.ps1
#
# Requirements:
#   pip install -e ".[dev,render]"
#   python -m playwright install chromium

$ErrorActionPreference = "Stop"

$env:RENDER_HOST = "127.0.0.1"
$env:RENDER_PORT = "3001"
$env:RENDER_MAX_CONCURRENT = "2"

Write-Host "=== PJSK Render Dev Server ===" -ForegroundColor Cyan
Write-Host "Host:  $env:RENDER_HOST" -ForegroundColor Gray
Write-Host "Port:  $env:RENDER_PORT" -ForegroundColor Gray
Write-Host "Reload: ON (Python changes auto-restart)" -ForegroundColor Gray
Write-Host "JS changes: re-POST to see updates (no restart needed)" -ForegroundColor Gray
Write-Host ""

& .\.venv\Scripts\python.exe -m uvicorn render_service.main:app `
    --host $env:RENDER_HOST `
    --port $env:RENDER_PORT `
    --reload
