# install_node.ps1 — bootstrap an AIM node on Windows.
#
# Installs:
#   • Python venv with AIM dependencies
#   • Ollama (if missing)        ← local LLM (qwen2.5:7b + qwen2.5:3b)
#   • %USERPROFILE%\.aim_env with hub URL, user token, optional DeepSeek key
#
# Usage (in PowerShell):
#   .\scripts\install_node.ps1
#
# To bypass execution policy if needed:
#   powershell -ExecutionPolicy Bypass -File .\scripts\install_node.ps1

param(
    [string]$HubUrl   = $env:AIM_HUB_URL,
    [string]$Token    = $env:AIM_USER_TOKEN,
    [string]$DsKey    = $env:DEEPSEEK_API_KEY
)

$ErrorActionPreference = "Stop"
$AimRoot = (Resolve-Path "$PSScriptRoot\..").Path
$EnvFile = Join-Path $env:USERPROFILE ".aim_env"

function Write-Bold($msg)  { Write-Host $msg -ForegroundColor White  -BackgroundColor Black }
function Write-OK($msg)    { Write-Host $msg -ForegroundColor Green }
function Write-Err($msg)   { Write-Host $msg -ForegroundColor Red   }

Write-Bold "AIM node installer  (platform: Windows)"
Write-Host "AIM_ROOT = $AimRoot"
Write-Host ""

# ── 1. Python venv ─────────────────────────────────────────────────────────

$venvPath = Join-Path $AimRoot "venv"
if (-not (Test-Path $venvPath)) {
    Write-Bold "[1/5] creating Python venv"
    python -m venv $venvPath
}
$activate = Join-Path $venvPath "Scripts\Activate.ps1"
. $activate
& python -m pip install --upgrade pip --quiet
Write-Bold "[1/5] installing Python deps"
& pip install -r (Join-Path $AimRoot "requirements.txt") --quiet
& pip install argon2-cffi httpx --quiet
Write-OK   "      OK"

# ── 2. Ollama ──────────────────────────────────────────────────────────────

Write-Bold "[2/5] checking Ollama"
$ollamaCmd = Get-Command ollama -ErrorAction SilentlyContinue
if (-not $ollamaCmd) {
    Write-Host "      Ollama not found, downloading installer…"
    $msi = Join-Path $env:TEMP "OllamaSetup.exe"
    Invoke-WebRequest -Uri "https://ollama.com/download/OllamaSetup.exe" -OutFile $msi
    Write-Host "      running Ollama installer (GUI)…"
    Start-Process -FilePath $msi -Wait
    if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
        Write-Err "      Ollama installation did not put 'ollama' on PATH."
        Write-Err "      Re-open PowerShell after install and re-run this script."
        exit 1
    }
}

# Probe Ollama API; start service if needed.
try {
    Invoke-WebRequest -Uri "http://127.0.0.1:11434/api/tags" -UseBasicParsing -TimeoutSec 2 | Out-Null
} catch {
    Write-Host "      starting ollama serve in background…"
    Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Hidden
    Start-Sleep -Seconds 4
}
Write-OK "      OK"

# ── 3. Pull default models ─────────────────────────────────────────────────

Write-Bold "[3/5] pulling local models (this can take 10–30 min on first run)"
$models = @("qwen2.5:3b-instruct", "qwen2.5:7b-instruct")
foreach ($m in $models) {
    $listed = (& ollama list 2>$null) -join "`n"
    if ($listed -notmatch [regex]::Escape($m.Split(":")[0])) {
        Write-Host "      pulling $m …"
        & ollama pull $m
    } else {
        Write-Host "      already present: $m"
    }
}
Write-Host "      tip: also try  ollama pull deepseek-r1:7b   for a local reasoner"
Write-OK   "      OK"

# ── 4. Configure ~/.aim_env ────────────────────────────────────────────────

Write-Bold "[4/5] configuring $EnvFile"

function Get-EnvVar($key) {
    if (-not (Test-Path $EnvFile)) { return "" }
    foreach ($line in Get-Content $EnvFile) {
        if ($line -match "^$([regex]::Escape($key))=(.*)$") {
            return ($Matches[1] -replace '^"','' -replace '"$','')
        }
    }
    return ""
}

function Set-EnvVar($key, $val) {
    $newLine = "$key=$val"
    if (Test-Path $EnvFile) {
        $content = Get-Content $EnvFile
        $found = $false
        $out = foreach ($line in $content) {
            if ($line -match "^$([regex]::Escape($key))=") { $found = $true; $newLine }
            else { $line }
        }
        if (-not $found) { $out += $newLine }
        Set-Content -Path $EnvFile -Value $out -Encoding UTF8
    } else {
        Set-Content -Path $EnvFile -Value $newLine -Encoding UTF8
    }
}

if (-not (Test-Path $EnvFile)) { New-Item -ItemType File -Path $EnvFile | Out-Null }

# Hub URL
if (-not $HubUrl) {
    $current = Get-EnvVar "AIM_HUB_URL"
    $HubUrl = Read-Host "AIM Hub URL [$current] (blank = local-only)"
    if (-not $HubUrl) { $HubUrl = $current }
}
Set-EnvVar "AIM_HUB_URL" $HubUrl

# User token (if hub set)
if ($HubUrl) {
    if (-not $Token) {
        $current = Get-EnvVar "AIM_USER_TOKEN"
        $masked = if ($current) { $current.Substring(0, [Math]::Min(12, $current.Length)) + "…" } else { "" }
        $Token = Read-Host "AIM_USER_TOKEN [$masked]"
        if (-not $Token) { $Token = $current }
    }
    Set-EnvVar "AIM_USER_TOKEN" $Token
}

# DeepSeek (optional)
if (-not $DsKey) {
    $current = Get-EnvVar "DEEPSEEK_API_KEY"
    $masked = if ($current) { $current.Substring(0, [Math]::Min(8, $current.Length)) + "…" } else { "" }
    $DsKey  = Read-Host "DeepSeek API key (optional, for cloud reasoner) [$masked]"
    if (-not $DsKey) { $DsKey = $current }
}
if ($DsKey) { Set-EnvVar "DEEPSEEK_API_KEY" $DsKey }

Write-OK "      $EnvFile updated"

# ── 5. Smoke test ──────────────────────────────────────────────────────────

Write-Bold "[5/5] smoke test"
Push-Location $AimRoot
& python -c "from llm import providers_status; import json; print(json.dumps(providers_status(), indent=2))"
Pop-Location

Write-Host ""
Write-OK "AIM node ready."
Write-Host ""
Write-Host "Next steps:"
Write-Host "  - run AIM web : python -m web.api --port 8080"
Write-Host "  - run AIM CLI : python medical_system.py"
Write-Host "  - run AIM GUI : python aim_gui.py"
Write-Host "  - run Telegram: python telegram_bot.py   (requires TELEGRAM_BOT_TOKEN)"
