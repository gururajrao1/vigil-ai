# Starts the VigilAI frontend dev server (installs deps on first run).
$ErrorActionPreference = "Stop"
Set-Location "$PSScriptRoot\frontend"

if (-not (Test-Path "node_modules")) {
    Write-Host "Installing frontend dependencies..." -ForegroundColor Cyan
    npm install
}

Write-Host "Starting VigilAI dashboard on http://localhost:5173" -ForegroundColor Green
npm run dev
