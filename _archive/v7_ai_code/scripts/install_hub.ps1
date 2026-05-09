# install_hub.ps1 — bootstrap an AIM Hub on Windows.
#
# A Hub is a single multi-user instance — manages users, JWT cookies,
# tokens, audit log, /link codes. Does NOT run LLM (each node does that).
#
# Usage:
#   .\scripts\install_hub.ps1
#   $env:AIM_HUB_PORT=8000; .\scripts\install_hub.ps1

param([int]$HubPort = $(if ($env:AIM_HUB_PORT) { [int]$env:AIM_HUB_PORT } else { 8000 }))

$ErrorActionPreference = "Stop"
$AimRoot = (Resolve-Path "$PSScriptRoot\..").Path

function Bold($m){ Write-Host $m -ForegroundColor White }
function OK($m)  { Write-Host $m -ForegroundColor Green }

Bold "AIM Hub installer"
Write-Host "AIM_ROOT = $AimRoot"
Write-Host "Port     = $HubPort"
Write-Host ""

$venv = Join-Path $AimRoot "venv"
if (-not (Test-Path $venv)) {
    Bold "[1/3] creating Python venv"
    python -m venv $venv
}
. (Join-Path $venv "Scripts\Activate.ps1")
& python -m pip install --upgrade pip --quiet
Bold "[1/3] installing minimal hub deps"
& pip install fastapi uvicorn argon2-cffi python-dotenv pydantic --quiet
OK   "      OK"

Bold "[2/3] bootstrapping admin user"
Push-Location $AimRoot
$existing = & python -c "from agents import auth; print(len(auth.list_users()))"
if ($existing.Trim() -eq "0") {
    $u = Read-Host "Admin username"
    & python -m scripts.user_admin create $u --role admin
    OK "      admin '$u' created"
} else {
    Write-Host "      $existing user(s) already exist — skipping bootstrap"
}
Pop-Location

Bold "[3/3] writing run script"
$runScript = @"
@echo off
cd /d "$AimRoot"
call venv\Scripts\activate.bat
set AIM_ROLE=hub
python -m web.api --host 0.0.0.0 --port $HubPort
"@
Set-Content -Path (Join-Path $AimRoot "start_hub.bat") -Value $runScript -Encoding ASCII
OK "      $AimRoot\start_hub.bat"

Write-Host ""
OK "AIM Hub ready."
Write-Host ""
Write-Host "Start it with:    $AimRoot\start_hub.bat"
Write-Host "Behind reverse-proxy with TLS recommended for public deployment."
Write-Host "Set AIM_HUB_HTTPS=1 to flag JWT cookies as Secure."
