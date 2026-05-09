# Python → Rust migration path

**Дата:** 2026-05-06 (HW1, Phase A-E + ports)
**Контекст:** AIM Stack rule (`CLAUDE.md` HARD CONSTRAINT) — backend / алгоритмы / agents / CLI / системные сервисы должны быть Rust. Python остаётся для legacy и bridges.

Этот документ описывает текущий гибрид и путь к финальной чистке.

---

## Текущее состояние (2026-05-06)

### ✅ Полностью на Rust (production-ready)

Каждое имеет CLI binary в `rust-core/target/release/`:

| Подсистема | Rust crate(s) | Binary |
|---|---|---|
| Project lifecycle | `aim-project-state-machine`, `aim-project-owner` | `aim-project-owner` |
| Patient lifecycle | `aim-patient-state-machine`, `aim-patient-memory`, `aim-patient-owner` | `aim-patient-owner` |
| Experiment lifecycle | `aim-experiment-state-machine`, `aim-experiment-owner` | `aim-experiment-owner` (включая `mcp-config` subcommand) |
| Patient communications | `aim-patient-comms` (SQLite) | `aim-patient-comms` |
| Stakeholder tracker | `aim-stakeholder-tracker` (SQLite) | (library only — используется через `aim-weekly-project-digest`) |
| Journal watcher (NDJSON) | `aim-journal-watcher` | (library) |
| MCP lab-runner config gen | `aim-mcp-lab-runner` | (library; CLI через `aim-experiment-owner mcp-config`) |
| Daily brief composer | `aim-lifecycle` + `aim-daily-brief` | `aim-daily-brief --telegram` |
| Weekly project digest | `aim-weekly-project-digest` | `aim-weekly-project-digest --telegram` |
| Long-running scheduler | `aim-serve-daemon` | `aim-serve-daemon` |

### 🟡 Гибрид — Python работает + Rust альтернатива доступна

Один из пары должен быть `systemctl --user enable`'d одновременно (НЕ оба):

| Назначение | Python (legacy) | Rust (alternative) |
|---|---|---|
| Daily brief delivery | `aim-daily-brief.service` (Python script + `notify` multiplexer) | `aim-daily-brief-rust.service` (Rust binary с встроенным Telegram client) |
| Weekly project digest delivery | `aim-weekly-project-digest.service` | `aim-weekly-project-digest-rust.service` |
| Long-running orchestrator | `aim-serve-daemon.service` (Python `agents/serve_daemon.py`) | `aim-serve-daemon-rust.service` (только daily_brief + weekly_project_digest jobs; Python остаётся для escalation/kpi/memory) |

### ❌ Остаётся в Python (нет Rust port)

| Что | Где | Почему |
|---|---|---|
| Hooks framework + producers | `agents/hooks.py`, `agents/hook_handlers.py`, fire-callsites в `labs.py`/`kernel.py`/`db.py`/`intake.py`/`patient_inbox_watcher.py` | Bridge в существующих Python модулях — fire обязан быть в том же runtime что producer |
| Asimov decision kernel | `agents/kernel.py` | Большой, complex, plugin-style; Rust port = отдельная фаза работы |
| Lab interpretation | `agents/labs.py`, `lab_reference.py` | 59 analytes + LLM integration (DS-V4-pro) |
| OCR pipeline | `agents/intake.py` (tesseract / pdfplumber / pymupdf) | Нет зрелых Rust аналогов |
| LLM router | `llm.py` | DS/Groq/KIMI/Qwen/Ollama — Rust есть `aim-llm` crate scaffold, но не production |
| AI subproject (S1-S14, hive_queen Python) | `AI/ai/*.py` (33 модуля) | Активно эволюционирует через Python; ML/sklearn deps |
| Pattern miner extensions | `agents/pattern_miner.py` (`_mine_stakeholder_silence`, `_mine_patient_followup_drift`) | Bridge — расширения existing Python module |
| escalation_engine | `agents/escalation_engine.py` | tiny DSL evaluator — Rust port доступен (`aim-escalation-engine` scaffold), но Python в production |
| KPI sync, memory_scan | `agents/kpi_auto_updater.py`, `agents/memory_monitor.py` | Существующие Python модули |

---

## Команды для переключения systemd Python → Rust

### Daily brief — Python → Rust

```bash
# 1. Build Rust binary в --release режиме
cd ~/Desktop/LongevityCommon/AIM/rust-core
cargo build --release -p aim-daily-brief

# 2. Подложить.service файл в user systemd
cp deploy/systemd/aim-daily-brief-rust.service ~/.config/systemd/user/
systemctl --user daemon-reload

# 3. Switch
systemctl --user disable --now aim-daily-brief.timer # отключить Python
systemctl --user enable --now aim-daily-brief-rust.timer # включить Rust
# (если timer'а для Rust ещё нет — запускать вручную или добавить.timer аналогично)

# 4. Проверить
systemctl --user status aim-daily-brief-rust.service
journalctl --user -u aim-daily-brief-rust.service -n 50
```

Аналогично для `aim-weekly-project-digest` и `aim-serve-daemon`.

### Откат (Rust → Python)

```bash
systemctl --user disable --now aim-daily-brief-rust.service
systemctl --user enable --now aim-daily-brief.timer
```

---

## Real patient MEMORY.md migration

```bash
# Dry-run (default; ничего не пишет)
python -m scripts.migrate_patient_memory

# Один пациент — посмотреть diff
python -m scripts.migrate_patient_memory --patient Feradze_Maia_1981_12_20

# Применить для одного (создаёт.bak-YYYYMMDDTHHMMSS перед записью)
python -m scripts.migrate_patient_memory --patient Feradze_Maia_1981_12_20 --apply

# Применить для всех 6 пациентов
python -m scripts.migrate_patient_memory --apply --all

# После миграции — проверить через Rust binary
~/Desktop/LongevityCommon/AIM/rust-core/target/release/aim-patient-owner brief Feradze_Maia_1981_12_20
```

После миграции пациентские MEMORY.md имеют секции `## Phase` (default `INTAKE`), `## Milestones` (`_(none)_`), `## Awaiting` (`_(none)_`). Врач заполняет руками или через CLI / LiveView.

---

## Cleanup checklist (когда уверен в Rust path)

После как минимум 2 недель работы Rust systemd units без регрессий:

- [ ] Удалить `scripts/daily_brief.py` (заменён `aim-daily-brief` binary)
- [ ] Удалить `scripts/weekly_project_digest.py` (заменён `aim-weekly-project-digest` binary)
- [ ] Удалить Python systemd unit'ы: `aim-daily-brief.{service,timer}`, `aim-weekly-project-digest.{service,timer}`, `aim-serve-daemon.service` (Python)
- [ ] Переименовать `-rust` варианты в canonical (без суффикса)
- [ ] Запустить регрессию `cargo test --workspace` + Python pytest суиту чтобы убедиться что bridges (hooks, daily_brief.py wrapper) не сломались

**НЕ делать** до тех пор пока:
- Python escalation_engine / kpi_auto_updater / memory_monitor не портированы в Rust (они нужны Python serve_daemon)
- Реальная нагрузка на новых Rust units не подтверждена за ≥2 недели

---

## Ссылки

- Аудит-отчёт: `AUDIT_PROJECT_MANAGER_2026-05-06.md`
- CLAUDE.md: «Project-manager subsystem» секция
- Workspace: `rust-core/Cargo.toml` — список 9 новых crates
- Pilot configs: `USER/projects/FCLC.yaml` (existing) + `USER/experiments/E0.yaml` + `USER/experiments/AutomatedMicroscopy.yaml`
