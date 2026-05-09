# AIM — STACK rule (постоянное правило ядра)

**Дата установки:** 2026-05-04
**Источник:** прямая директива пользователя ("delai vse na Rust",
"frontend na Phoenix", "prodoljit razvitie AIM — na Rust i Phoenix",
"v Docker ne pomeschat po vozmojnosti nichego" 2026-05-04).

---

## Единственное технологическое правило

**Всё, что разрабатывается в AIM, пишется на:**

- **Backend / CLI / агенты / алгоритмы / БД-доступ / системные сервисы → Rust**
 (workspace `AIM/rust-core/`, новые крейты в `crates/aim-*`)
- **Frontend / dashboards / interactive UI → Phoenix LiveView**
 (Elixir, по паттерну Ze/BioSense/FCLC: `mix release` → systemd
 `/opt/aim-*/`, native, без Docker runtime)

**Никаких новых модулей на Python без явной необходимости.**

**НИКАКОГО Docker.** Ни runtime, ни build-time, ни dev-окружения.
Развёртывание = native systemd units (`mix release` для Phoenix,
`cargo build --release` + `systemd unit` для Rust). Ни Dockerfile,
ни docker-compose.yml, ни OCI-images в новых модулях.

Исключения только если пользователь явно попросит. По умолчанию —
без Docker даже для тестов CI / sandbox / build-isolation.

---

## Что считается "явной необходимостью" для Python

Только если задача требует библиотеки, для которой **нет зрелого Rust
аналога**, и переписывать её = огромная работа без пропорциональной
выгоды. На 2026-05-04 список:

| Задача | Python-зависимость | Почему нет Rust |
|--------|--------------------|-----------------|
| OCR | `rapidocr_onnxruntime`, `tesseract` | tesseract-rs незрелый, ONNX Runtime Rust есть но без полного OCR pipeline |
| PDF text extraction | `pymupdf`, `pdfplumber` | `lopdf` / `pdfium-render` ограничены |
| WhatsApp pipeline | существующий `agents/intake.py` | работает, шим через subprocess из Rust |
| ASR (speech-to-text) | `faster_whisper` локально + OpenAI Whisper API fallback в `agents/voice.py`, `agents/telegram_extras.py` | whisper-rs есть, но ONNX models + точность ниже; OpenAI Whisper API = ASR, **не** chat-completion → не нарушает «LLM only via llm.py» |
| TTS офлайн (v7.2) | `xtts-v2`, `pyttsx3`, `espeak-ng` | нет нативного Rust voice cloning |
| Talking-head офлайн (v7.2) | `SadTalker`, `Wav2Lip` | PyTorch-only, нет Rust-портов |
| 3D mesh офлайн (v7.2) | `Hunyuan3D`, `TripoSR`, Microsoft `Trellis` | diffusion-based, PyTorch-only |
| 3D scripting (v7.2) | Blender `bpy` | Blender Python — единственный API; вызов `blender --background --python` |
| Молекулярная визуализация (v7.2) | `RDKit`, `py3Dmol`, PyMOL | хемоинформатика — только Python; рендерим в GLB → Three.js |
| DICOM 3D (v7.2) | 3D Slicer (`vtk`, `pydicom`) | медицинская визуализация — Python экосистема |

### Notes (2026-05-07)

- **OpenAI SDK импорт ≠ нарушение** правила «LLM only via llm.py» если он
 используется для **non-LLM endpoints** (Whisper ASR, TTS, embeddings).
 Chat completion (`.chat.completions.create`) — обязан идти через
 `llm.py::ask*` функции. Известные **legitimate** uses Whisper API:
 - `agents/voice.py:80-90` — fallback после faster-whisper
 - `agents/telegram_extras.py:90-103` — voice message transcription

### Frozen Python legacy (planned-port, не нарушение пока в frozen режиме)

Эти модули **активны в production**, но Python-only. Расширять их —
запрещено; security-patch / bug-fix — разрешено. Полный port — отдельная
фаза в `STRATEGY.md`:

| Модуль | LoC | Что делает | Phase для port'а |
|--------|-----|------------|------------------|
| `web/api.py` | 772 | FastAPI hub-side: `/api/auth/{login,logout,me,validate-token,consume-pair-code}`, `/api/nodes/heartbeat` (multi-user mode) | STRATEGY P2-4 (Phoenix `aim_gateway` или `aim_web`) |
| `medical_system.py` | 656 | CLI entrypoint (agent loop) | STRATEGY P2-9b (orchestrator binary, после порта generalist) |
| `telegram_bot.py` | 610 | python-telegram-bot polling + handlers | STRATEGY P3 (eval `teloxide` maturity) |
| `aim_cli.py` | 656 | argparse CLI commands | STRATEGY P2-9c (clap subcommand набор) |
| `aim_gui.py` | — | customtkinter desktop GUI | замена на native Phoenix-LiveView desktop через Tauri shell — TBD |

**Frozen rule:** новые routes / commands / handlers в этих файлах
**не добавляются**. Если нужна новая функциональность — пишется новый
Rust crate / Phoenix LiveView с тем же контрактом. Список замораживается
по состоянию 2026-05-07.

**Все эти Python-блоки вызываются из Rust через subprocess или unix
socket.** Они не получают новой функциональности — только сохранение
существующего. Любые их расширения — пишем на Rust обёртку и
постепенно вытесняем Python.

---

## Что считается "разработкой в AIM"

- Новые модули в `AI/ai/` → пишутся как новые Rust crates в
 `rust-core/crates/aim-ai-*/` (НЕ как `.py` файлы)
- Новые модули в `agents/` → как Rust crates `crates/aim-agent-*/`
- Новые web-страницы / dashboards → как LiveView в `aim-web/lib/`
 (НЕ как новые `aim_gui.py` дополнения, НЕ как FastAPI endpoints
 в `web/api.py`)
- Новые CLI-команды → как subcommands в `aim` clap CLI (НЕ как новые
 argparse pieces в `aim_cli.py`)
- Новые тесты → Rust `#[cfg(test)]` или Phoenix `mix test`. pytest
 только для shimming Python legacy.

---

## Что НЕ нужно переписывать прямо сейчас

Существующий Python AIM **продолжает работать**, его не выкидываем.
Замена идёт по очереди — одно ядро за раз — с паритетным test suite.
Удаление Python-предка только когда Rust-замена покрывает 100% и
проходит eval-harness.

Порядок миграции зафиксирован в `docs/migration/MIGRATION_RUST_PHOENIX.md`. Текущий
sprint — Phase 1 (Hive layer на Rust).

---

## Соблюдение

Это правило применяется **на каждой сессии разработки AIM** автоматически.
Если AI-ассистент или человек собирается написать `*.py` в AIM/ — должна
сработать проверка: "это Phase X миграции, или это shim для существующей
OCR/PDF-зависимости?". Если ни то ни другое — правило нарушено.

То же самое для Docker: если кто-то собирается создать `Dockerfile`,
`docker-compose.yml`, `.dockerignore` или `OCI image` — сработать
проверка: "пользователь явно попросил Docker?". Если нет — правило
нарушено, использовать systemd / native release.

При сомнении — спросить пользователя. Не писать Python "потому что
быстрее"; не писать Docker "потому что проще".

---

**Это файл ядра.** Он не генерируется из CONCEPT.md; он сам — правило.
В public git не загружается (через `.gitignore` core .md ruling).
