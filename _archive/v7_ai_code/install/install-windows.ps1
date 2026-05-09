# AIM Rust + Phoenix installer — Windows (Scheduled Tasks + nssm-free)
#
# Builds the Rust workspace + Phoenix release, registers Scheduled Tasks
# that run the orchestrator + Phoenix LiveView at logon. No Docker.
# Per CLAUDE.md HARD CONSTRAINT.
#
# Run in PowerShell:
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#   .\install-windows.ps1

param(
    [string]$Prefix = "$env:LOCALAPPDATA\aim",
    [string]$Source = "$PWD"
)

$ErrorActionPreference = 'Stop'

function Log($msg)  { Write-Host "[aim-install] $msg" -ForegroundColor Cyan }
function Fail($msg) { Write-Host "[aim-install] $msg" -ForegroundColor Red; exit 1 }

function Need($cmd) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        Fail "need '$cmd' on PATH"
    }
}

Log "checking toolchain"
Need git
Need cargo
Need rustc
Need elixir
Need mix

if (-not (Test-Path "$Source\AIM\rust-core\Cargo.toml")) {
    Fail "run from a LongevityCommon checkout (need AIM\rust-core\Cargo.toml at \$Source)"
}

Log "building Rust workspace (release)"
Push-Location "$Source\AIM\rust-core"
cargo build --release --workspace
Pop-Location

Log "building Phoenix umbrella (mix release)"
Push-Location "$Source\AIM\phoenix-umbrella"
$env:MIX_ENV = 'prod'
mix deps.get --only prod
mix compile
mix release --overwrite
Pop-Location

Log "staging into $Prefix"
New-Item -ItemType Directory -Force -Path "$Prefix\bin","$Prefix\phoenix","$Prefix\etc","$Prefix\logs" | Out-Null

Get-ChildItem "$Source\AIM\rust-core\target\release\aim-*.exe" -ErrorAction SilentlyContinue |
    ForEach-Object { Copy-Item $_.FullName "$Prefix\bin\" -Force }

$phxRel = Get-ChildItem -Path "$Source\AIM\phoenix-umbrella" -Recurse -Directory -Filter 'rel' |
    Select-Object -First 1
if ($phxRel) {
    Copy-Item -Recurse -Force "$($phxRel.FullName)\*" "$Prefix\phoenix\"
}

# ── Scheduled Tasks ───────────────────────────────────────────────────────

$orchExe = "$Prefix\bin\aim-llm.exe"
$phxBat  = "$Prefix\phoenix\bin\aim_web.bat"

if (Test-Path $orchExe) {
    Log "registering scheduled task: AIM-Orchestrator"
    $action  = New-ScheduledTaskAction  -Execute $orchExe -Argument 'serve' -WorkingDirectory $Prefix
    $trigger = New-ScheduledTaskTrigger -AtLogOn
    $settings= New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1)
    Register-ScheduledTask -TaskName 'AIM-Orchestrator' `
        -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
}

if (Test-Path $phxBat) {
    Log "registering scheduled task: AIM-Phoenix"
    $env:MIX_ENV = 'prod'
    $action  = New-ScheduledTaskAction -Execute $phxBat -Argument 'start' -WorkingDirectory "$Prefix\phoenix"
    $trigger = New-ScheduledTaskTrigger -AtLogOn
    $settings= New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1)
    Register-ScheduledTask -TaskName 'AIM-Phoenix' `
        -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
}

Log "done"
Write-Host ""
Write-Host "✅ AIM installed under $Prefix" -ForegroundColor Green
Write-Host "Start:  Start-ScheduledTask -TaskName AIM-Orchestrator,AIM-Phoenix"
Write-Host "URL:    http://127.0.0.1:4000/"
Write-Host "Keys:   `$env:USERPROFILE\.aim_env (DEEPSEEK_API_KEY=..., etc)"
