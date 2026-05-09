# _archive/ — отброшенные / superseded артефакты

Не пушится в public git. Хранится для archaeological reference + git
history backup. Каждая директория = stale snapshot с датой архивации.

| Path | Archived | Reason | Replacement |
|---|---|---|---|
| `aim-web_2026-05-07/` | 2026-05-07 | Standalone Phoenix app, superseded by umbrella | `phoenix-umbrella/apps/aim_web/` |
| `systemd_legacy_2026-05-07/` | 2026-05-07 | 1-unit dir, superseded by 19-unit canonical | `deploy/systemd/` |
| `queen_deploy_2026-05-07/` | 2026-05-07 | Hive queen deploy, 0 callers anywhere | (none — re-evaluate if hive scales) |

При необходимости восстановить: `mv _archive/X . && (git mv etc)`.

## 2026-05-07 (cont.) — Phase-9-like cleanup batch

| Path | Files | Reason |
|---|---|---|
| `_journal_2026-05-07/` | 3 | Orchestrator scratch journal, 0 callers; legacy from earlier session-mgmt experiment |

Также удалены (не архивированы — пустые / build artifacts):
- `patches/` (empty)
- `media/` (empty)
- `aim_generalist.egg-info/` (build artifact, regenerable via `pip install -e .`)

Сохранены (active callers / production):
- `install/` (production installers: install-linux.sh, install-macos.sh, install-windows.ps1, deploy-server.sh)
- `fonts/` (Georgian Unicode bundled fonts for GUI)
- `experiments/` (1 caller: scripts/backup_system.py)
- `migrations/` (db migrator module)
- `cli/` (1 test caller; needs review separately)
- `export/` (4 callers: tests + backup)
- `logs/` (runtime, gitignored)
