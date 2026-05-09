# AIM v0.1.0 — first packaged release

First public packaging of AIM. Three platform archives are attached.

## Download

| Platform | File | SHA-256 |
|----------|------|---------|
| Linux | `aim-0.1.0-linux.tar.gz` | see `aim-0.1.0.sha256` |
| macOS | `aim-0.1.0-macos.tar.gz` | see `aim-0.1.0.sha256` |
| Windows | `aim-0.1.0-windows.zip` | see `aim-0.1.0.sha256` |

## Install (Linux / macOS)

```bash
tar -xzf aim-0.1.0-linux.tar.gz # or aim-0.1.0-macos.tar.gz
cd aim-0.1.0-linux # or aim-0.1.0-macos
bash scripts/install_node.sh
```

## Install (Windows)

```powershell
Expand-Archive aim-0.1.0-windows.zip
cd aim-0.1.0-windows
powershell -ExecutionPolicy Bypass -File scripts\install_node.ps1
```

The installer creates a Python venv, optionally installs Ollama
(local LLM), and writes `~/.aim_env` (or `%USERPROFILE%\.aim_env`)
with your settings.

## What's included

- AIM core (`aim_cli.py`, `aim_gui.py`, `medical_system.py`, `agents/`, `AI/`)
- Closed-loop self-improvement subproject (`AI/`)
- 33 generalist tools, ensemble + adjudication, session resume, scratchpad
- 9-language i18n (UN-6 + KA + KZ + DA)
- Hub/node multi-user support (`agents/auth.py`, `agents/hub_client.py`)
- Hive worker hooks (`AI/ai/hive_telemetry.py`, `hive_consumer.py`)
- Per-user LLM key isolation (`user_keys.py`, `key_setup.py`)

## What's NOT included

- `venv/` (created by installer)
- `Patients/` (per-clinic, never shipped)
- `*.db` (created on first run)
- `target/`, `_build/`, `deps/` (build artefacts)
- Internal-only docs in the public archive (`CONCEPT.md`, `CLAUDE.md`,
 `TODO.md`, `PARAMETERS.md`, audit reports)

## Connect to the Hive (optional)

```bash
echo 'AIM_HIVE_QUEEN_URL=https://hive.longevity.ge' >> ~/.aim_env
aim diag --hive-preview # dry-run, shows what would be sent
aim diag --hive-status # current Hive integration status
```

Each bee is fully functional offline. Hive participation is opt-in.

## License

MIT — see LICENSE in archive.
