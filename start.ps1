# CCLEAR launcher (Windows / PowerShell)
# Usage: right-click project root -> "Open in Terminal" -> run:
#   powershell -ExecutionPolicy Bypass -File .\start.ps1
#
# What it does: checks .env -> installs deps on first run -> starts backend (8000)
#               -> starts frontend (5173) -> opens browser.
# NOTE: messages are ASCII-only to stay compatible with Windows PowerShell 5.1
#       (which misreads non-BOM UTF-8)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Definition
$backend = Join-Path $root 'backend'
$frontend = Join-Path $root 'frontend'

Write-Host '== CCLEAR launcher ==' -ForegroundColor Cyan

# 1. Backend env file
$envFile = Join-Path $backend '.env'
if (-not (Test-Path $envFile)) {
    Write-Host '[!] backend/.env not found.' -ForegroundColor Yellow
    Write-Host '    Copying backend/.env.example -> backend/.env' -ForegroundColor Yellow
    Copy-Item (Join-Path $backend '.env.example') $envFile
    Write-Host '    Please edit backend/.env and set DEEPSEEK_API_KEY, then re-run this script.' -ForegroundColor Yellow
    notepad $envFile
    exit 1
}

# 2. Backend venv + deps
$venvPython = Join-Path $backend '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPython)) {
    Write-Host '[*] First run: creating Python venv and installing backend deps...' -ForegroundColor Green
    Push-Location $backend
    python -m venv .venv
    & $venvPython -m pip install --upgrade pip
    & $venvPython -m pip install -r requirements.txt
    Pop-Location
}

# 3. Frontend deps
if (-not (Test-Path (Join-Path $frontend 'node_modules'))) {
    Write-Host '[*] First run: installing frontend deps...' -ForegroundColor Green
    Push-Location $frontend
    npm install
    Pop-Location
}

# 4. Start backend (new window)
Write-Host '[*] Starting backend at http://127.0.0.1:8000 ...' -ForegroundColor Green
Start-Process powershell -ArgumentList @(
    '-NoExit', '-Command',
    "Set-Location '$backend'; & '$venvPython' -m uvicorn app.main:app --reload --port 8000"
)

# 5. Start frontend (new window)
Write-Host '[*] Starting frontend at http://localhost:5173 ...' -ForegroundColor Green
Start-Process powershell -ArgumentList @(
    '-NoExit', '-Command',
    "Set-Location '$frontend'; npm run dev"
)

# 6. Open browser after a short wait
Start-Sleep -Seconds 4
Start-Process 'http://localhost:5173'

Write-Host '== Done. Both services run in separate windows; closing them stops the services. ==' -ForegroundColor Cyan
