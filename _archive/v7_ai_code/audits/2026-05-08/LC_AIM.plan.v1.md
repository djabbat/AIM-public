## PLAN IMPROVEMENTS

### P0 — Блокеры

**P0.1 Удалить Dockerfile и зафиксировать запрет**  
Файл нарушает директиву «НИКАКОГО Docker» (CLAUDE.md, STACK.md). Удалить `Dockerfile`. В `STACK.md` добавить явную запись: «Docker запрещён; при необходимости — согласование с пользователем».  
**Файлы:** `Dockerfile` (удалить), `STACK.md` (добавить секцию).  
**Трудоёмкость:** S (15 мин)  
**Риск:** низкий — файл не используется в production (native systemd).

---

### P1 — Важно

**P1.1 Объединить мелкие Rust-крейты по функциональным доменам**  
Слить `aim-memory-*`, `aim-ai-*`, `aim-*-calibration`, `aim-*-monitor` и аналогичные (< 500 строк) в единые крейты `aim-memory`, `aim-ai`, `aim-calibration`, `aim-monitor`. Обновить `Cargo.toml` workspace и все зависимости.  
**Файлы:** `rust-core/Cargo.toml`, все затрагиваемые крейты.  
**Трудоёмкость:** L (2–3 дня)  
**Риск:** средний — потребуется проверить все `use` и `mod`; могут сломаться импорты в Python shims (`agents/*.py`).

**P1.2 Внедрить единый CLI-фреймворк для всех Rust-бинарников**  
Добавить зависимость `clap = "4"` в workspace, переписать ручной разбор `std::env::args()` во всех бинарниках (aim-ai-cases, aim-interactions, aim-ai-prompt-versions, и др.) на derive-структуры. Ввести общий трейт `CliCommand` для единообразия.  
**Файлы:** `rust-core/Cargo.toml` (+dep), все `main.rs` бинарников (≈20 файлов).  
**Трудоёмкость:** M (1 день)  
**Риск:** низкий — clap стабилен, замена шаблонного кода.

**P1.3 Синхронизировать документацию с фактическим состоянием**  
- `LINKS.md`: удалить секции KIMI и Qwen, заменить на пометку «REJECTED 2026-05-07, см. UPGRADE.md».  
- `MAP.md`: добавить все крейты Phase 8/9 (aim-coach, aim-pam, aim-disagreement, aim-codesign, aim-interactions, и т.д.).  
- `TODO.md`: убрать пункты, ссылающиеся на `docs/operational/DEPLOY_RUNBOOK.md` и `PILOT_PROTOCOL.md`, если файлы не существуют (или создать их).  
- `PARAMETERS.md`: заменить упоминания KIMI/Qwen на «не реализовано — REJECTED» или убрать.  
**Файлы:** `LINKS.md`, `MAP.md`, `TODO.md`, `PARAMETERS.md`.  
**Трудоёмкость:** M (0.5 дня)  
**Риск:** низкий.

**P1.4 Изолировать Python-legacy зависимости**  
Вынести неиспользуемые в production зависимости из `requirements.txt` (customtkinter, python-telegram-bot, rapidocr-onnxruntime) в отдельный `requirements-legacy.txt`. В `STACK.md` явно указать, что legacy-зависимости не загружаются автоматически.  
**Файлы:** `requirements.txt` (очистить), `requirements-legacy.txt` (создать), `STACK.md` (добавить примечание).  
**Трудоёмкость:** S (30 мин)  
**Риск:** низкий — legacy-код не активен в production (Frozen Python).

**P1.5 Задокументировать допустимость Node/JS для Phoenix-ассетов**  
В `STACK.md` добавить строку: «Node.js/JavaScript разрешены только для сборки Phoenix-статики (esbuild, Tailwind). PHP, Ruby, Go и другие не допускаются».  
**Файлы:** `STACK.md`.  
**Трудоёмкость:** S (5 мин)  
**Риск:** отсутствует.

**P1.6 Обновить MAP.md — отразить все крейты и микросервисы**  
Добавить новые крейты Phase 8/9 (aim-coach, aim-verify, aim-grep, aim-interactions, aim-regimen-validator и др.), указать статус (Tier 1/2/3). Включить PyO3-связки (`aim-kernel-py`).  
**Файлы:** `MAP.md`.  
**Трудоёмкость:** M (0.5 дня)  
**Риск:** низкий.

**P1.7 Добавить pre-commit hook для проверки stack-rule**  
Создать скрипт `scripts/pre-commit.sh`, который проверяет:  
— отсутствие файлов `Dockerfile`, `docker-compose.yml`, `.dockerignore`;  
— отсутствие новых .py-файлов вне `agents/`, `tools/`, `scripts/` (legacy).  
Подключить в `.git/hooks/pre-commit` (или через `.githooks`).  
**Файлы:** `scripts/pre-commit.sh` (создать), `.git/hooks/` (скопировать).  
**Трудоёмкость:** M (0.5 дня)  
**Риск:** низкий — не нарушает существующую логику.

---

### P2 — Nice-to-have

**P2.1 Заменить subprocess shims на PyO3 in-process для hot-path**  
Для крейтов `aim-pam`, `aim-disagreement`, `aim-codesign` (активно вызываемых из Python-агентов) реализовать PyO3-биндинги, чтобы избежать fork+exec на каждый вызов.  
**Файлы:** `rust-core/crates/aim-pam-py/`, `aim-disagreement-py/`, `aim-codesign-py/` (создать); `agents/pam_tracker.py`, `automation_bias_detector.py`, `codesign_log.py` (переписать на прямой import).  
**Трудоёмкость:** L (2–3 дня)  
**Риск:** высокий — PyO3 ABI нестабилен между версиями Python; потребуется CI для сборки.

**P2.2 Автоматическая генерация MAP.md из Cargo.toml**  
Написать скрипт `scripts/generate_map.sh`, который парсит `Cargo.toml` и выводит таблицу крейтов с описаниями (из `lib.rs` doc-комментариев). Вызывать при `cargo build` или в pre-commit.  
**Файлы:** `scripts/generate_map.sh` (создать), `MAP.md` (автообновление).  
**Трудоёмкость:** M (1 день)  
**Риск:** низкий — не изменяет код.

**P2.3 Переместить корневые Python-файлы в поддиректорию legacy**  
Перенести `config.py`, `db.py`, `medical_system.py`, `aim_gui.py`, `aim_cli.py` в `legacy/` (или `python/`). В корне оставить только симлинки для обратной совместимости (опционально). Обновить все импорты в legacy-модулях.  
**Файлы:** `legacy/` (создать), корневые .py (переместить), все файлы, импортирующие их (проверить grep).  
**Трудоёмкость:** M (0.5 дня)  
**Риск:** средний — могут поломаться неявные импорты в `tests/` и `AI/`.

**P2.4 Добавить CI-конфигурацию (Github Actions)**  
Базовый workflow: `cargo test —workspace`, `mix test`, `pytest tests/`, `shellcheck` для скриптов. Использовать `ubuntu-latest`, Rust stable, Elixir 1.17.  
**Файлы:** `.github/workflows/aim-ci.yml` (создать).  
**Трудоёмкость:** M (1 день)  
**Риск:** низкий.

**P2.5 Исправить орфографию в README.md**  
"Гибридный" → "Гибридный" (или корректный термин).  
**Файлы:** `README.md`.  
**Трудоёмкость:** S (5 мин)  
**Риск:** отсутствует.