# AIM Installation

Native installers for the Rust + Phoenix stack. **No Docker** —
per `CLAUDE.md` HARD CONSTRAINT.

## Prerequisites

| Tool | Min version | Install |
|-----------|-------------|-----------------------------------------------|
| Rust | 1.78 | <https://rustup.rs/> |
| Elixir | 1.16 | distro / `brew install elixir` / `asdf` |
| Erlang/OTP| 26 | bundled with Elixir on most installs |
| git | any | distro |

Optional but useful: `tesseract` (OCR for `Patients/INBOX/`).

## One-liner from a checkout

```bash
git clone https://github.com/djabbat/AIM-public.git
cd AIM-public
./AIM/install/install-linux.sh # Linux (systemd user units)
./AIM/install/install-macos.sh # macOS (launchd plists)
.\AIM\install\install-windows.ps1 # Windows (Scheduled Tasks)
```

Each installer:

1. `cargo build --release --workspace` — compiles all 178 Rust crates.
2. `mix release --overwrite` — builds the Phoenix umbrella.
3. Stages binaries + Phoenix release into a per-user prefix.
4. Wires native service units (systemd / launchd / Scheduled Tasks).
5. Symlinks `aim` into `~/.local/bin/`.

## Per-user keys

LLM provider keys go in `~/.aim_env` (or `%USERPROFILE%\.aim_env`):

```
DEEPSEEK_API_KEY=sk-...
GROQ_API_KEY=gsk_...
ANTHROPIC_API_KEY=sk-ant-... # optional
GEMINI_API_KEY=... # optional, free tier
AIM_HUB_URL=https://hub.example.com # if joining a hub
AIM_USER_TOKEN=aim_xxx # token from `aim user-admin`
```

The hub never stores LLM keys; each user pays their own provider
account. See `aim-user-keys` crate.

## Service control

| OS | Start | Logs |
|---------|----------------------------------------------------------|-----------------------------------|
| Linux | `systemctl --user start aim-orchestrator aim-phoenix` | `journalctl --user -u aim-phoenix -f`|
| macOS | `launchctl load ~/Library/LaunchAgents/com.longevitycommon.aim.*.plist` | `~/Library/Application Support/aim/logs/` |
| Windows | `Start-ScheduledTask -TaskName AIM-Orchestrator,AIM-Phoenix` | `%LOCALAPPDATA%\aim\logs\` |

Web UI: <http://127.0.0.1:4000/>

## Uninstall

```bash
# Linux
systemctl --user disable --now aim-orchestrator aim-phoenix
rm -rf ~/.local/aim ~/.config/systemd/user/aim-*.service

# macOS
launchctl unload ~/Library/LaunchAgents/com.longevitycommon.aim.*.plist
rm -rf ~/Library/Application\ Support/aim ~/Library/LaunchAgents/com.longevitycommon.aim.*

# Windows
Unregister-ScheduledTask -TaskName AIM-Orchestrator,AIM-Phoenix -Confirm:$false
Remove-Item -Recurse $env:LOCALAPPDATA\aim
```
