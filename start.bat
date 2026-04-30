@echo off
REM start.bat — universal launcher for AIM on Windows.
REM Usage:
REM   start.bat            CLI (default)
REM   start.bat gui        tkinter GUI
REM   start.bat web        FastAPI on 127.0.0.1:8080
REM   start.bat hub        Hub mode (multi-user auth server)
REM   start.bat telegram   Telegram bot
REM   start.bat install    install node (Ollama + venv + ~/.aim_env)
REM   start.bat install-hub install hub
setlocal
cd /d "%~dp0"
if not exist venv ( python -m venv venv )
call venv\Scripts\activate.bat
pip install -q -r requirements.txt

set MODE=%1
if "%MODE%"=="" set MODE=cli
shift

if /I "%MODE%"=="cli"         ( python medical_system.py %* & goto :eof )
if /I "%MODE%"=="gui"         ( python aim_gui.py        %* & goto :eof )
if /I "%MODE%"=="web"         ( python -m web.api --port %AIM_WEB_PORT% %* & goto :eof )
if /I "%MODE%"=="node"        ( python -m web.api --port %AIM_WEB_PORT% %* & goto :eof )
if /I "%MODE%"=="hub" (
    set AIM_ROLE=hub
    if "%AIM_HUB_PORT%"=="" set AIM_HUB_PORT=8000
    python -m web.api --host 0.0.0.0 --port %AIM_HUB_PORT% %*
    goto :eof
)
if /I "%MODE%"=="telegram"    ( python telegram_bot.py %* & goto :eof )
if /I "%MODE%"=="bot"         ( python telegram_bot.py %* & goto :eof )
if /I "%MODE%"=="install"     ( powershell -ExecutionPolicy Bypass -File scripts\install_node.ps1 & goto :eof )
if /I "%MODE%"=="install-hub" ( powershell -ExecutionPolicy Bypass -File scripts\install_hub.ps1 & goto :eof )

echo unknown mode: %MODE%
echo usage: %~nx0 {cli^|gui^|web^|hub^|telegram^|install^|install-hub}
exit /b 1
