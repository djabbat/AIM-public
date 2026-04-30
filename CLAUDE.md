# CLAUDE.md — AIM v7.0

---

## Startup Protocol

**Полные правила:** `~/Desktop/Claude/protocols/START.md`

---

## Multi-user (Hub + Node)

AIM работает в двух режимах через `AIM_ROLE`:

| Режим | Назначение | LLM | DB | Запуск |
|---|---|---|---|---|
| `hub` (1 шт) | users / tokens / audit / `/link` codes | НЕТ | `aim_hub.db` | `bash start.sh hub` |
| `node` (default, у каждого юзера локально) | chat / memory / patients / LLM | Ollama + DeepSeek-V4 | `aim.db` | `bash start.sh web` |

**Установка:**
- Linux/macOS node: `bash scripts/install_node.sh` (ставит Ollama + qwen2.5:7b/3b + venv + `~/.aim_env`)
- Windows node: `powershell -ExecutionPolicy Bypass -File scripts\install_node.ps1`
- Hub: `bash scripts/install_hub.sh` (минимум deps, без Ollama, создаёт первого admin)

**Auth flow node→hub:**
1. Admin создаёт юзера: `python -m scripts.user_admin create <username>`
2. Admin выдаёт токен: `python -m scripts.user_admin token <username>` → копирует в `~/.aim_env` пользователя как `AIM_USER_TOKEN` + `AIM_HUB_URL`
3. Node при старте бьёт `/api/auth/validate-token` у hub'а, кэширует ответ 24h, шлёт heartbeat в `/api/nodes/heartbeat`
4. Offline grace: 7 дней по кэшу при недоступном hub'е (`AIM_OFFLINE_GRACE`)
5. Telegram /link — admin: `python -m scripts.user_admin link-code <username>` → 6-значный код, юзер шлёт боту `/link 123456`

**LLM на node — приоритеты роутинга (cloud-first per user 2026-04-30):**
1. Reasoning task → DeepSeek-V4-pro (cloud, default reasoner)
2. Long-context (>30K токенов) → DeepSeek-V4-flash (1M ctx)
3. Default chat → DeepSeek-V4-flash
4. ask_fast → Groq llama-3.1-8b-instant (быстрее DS на коротких запросах)
5. Fallback при unreachable cloud → Ollama (qwen2.5:7b или deepseek-r1 для reasoning)

**Без DeepSeek** node работает на Groq + Ollama. **Без Ollama** — только cloud. Hybrid рекомендован.

---

## Generalist & Domain Specialists (2026-04-30, расширено)

AIM имеет **tool-using executor** (Claude-style agency) с **28 tools**:

| Tool | Что делает |
|---|---|
| `read_file / write_file / edit_file / apply_patch` | UTF-8 файлы; apply_patch = atomic unified-diff multi-edit |
| `glob / grep` | поиск файлов и regex-поиск (использует ripgrep если установлен) |
| `bash` | whitelist'ed shell (ls/cat/grep/git/python/pytest, не `rm`) |
| `web_search / web_fetch` | DuckDuckGo HTML scrape + httpx fetch с очисткой HTML — для всего вне PubMed |
| `memory_recall / memory_save` | semantic поиск + сохранение в auto-memory (LanceDB) |
| `view_image` | **Native vision** — PNG/JPG/PDF page → Claude или DS-V4 vision (OCR fallback) |
| `verify_pmid / verify_doi / search_pubmed` | PubMed esummary + Crossref hard-check |
| `delegate_doctor` | DoctorAgent (diagnose/treatment/labs/chat) |
| `delegate_writer` | `agents/writer.py` — peer review, edit, cover letter, md→docx |
| `delegate_researcher` | `agents/researcher.py` — find/summarise/verify (zero hallucinated DOIs) |
| `delegate_coder` | `agents/coder.py` — Aider wrap + edit-then-test loop |
| `delegate_email` | `agents/email_agent.py` — Gmail list/search/draft/send (gated by L_CONSENT) |
| `delegate_parallel` | **Sub-agent fan-out** — N независимых generalist'ов + synthesis |
| `kernel_check` | precheck L_PRIVACY/L_CONSENT/L_VERIFIABILITY перед side-effect |

### Generalist v2 features (2026-04-30 final)

- **Native messages[] + strict JSON mode** для DeepSeek calls — лучший prefix-cache hit, меньше parse failures.
- **Auto-compact history** при >30K tokens — старые tool-results summarises через `ask_long`.
- **Auto-ensemble на critical prompts** — `is_critical(task)` триггерит 3-model planning consensus до старта tool-loop.
- **Self-critique loop** — на критичный final adversarial reviewer ловит фабрикованные ссылки / unsupported claims; 1 retry max.
- **Streaming events** — `run_streaming(task)` yield'ит `{type:tool_call|tool_result|self_critique_*|final|interrupted}`. CLI `medical_system.py "A"` показывает live progress.
- **Speculative prefetch + parallel tool batches + sub-agent fan-out** — все три вместе резко снижают wall-clock на multi-step задачах.
- **Multi-action pipeline** (A3) — `{"actions":[...]}` allows mixed serial+parallel groups within one LLM round.
- **D1 persisted tool calls** — каждый tool_call/result пишется в `messages` table → resume restores full trace, не только user/assistant.
- **D2 scratchpad** — tools `note(key,value)` / `recall(key)` для working memory внутри одного run() (не в каждом prompt).
- **C4 bash_async / bash_status / bash_output / bash_kill** — long-running commands не блокируют generalist; job_id polling.
- **E2 SIGINT interrupt** — `request_interrupt()` API + auto Ctrl+C handler в main thread; чистый shutdown prefetcher/pool.
- **F1 tool examples** — `register_tool(..., examples=[{call:...}])` рендерится в system prompt для error-prone tools (apply_patch, delegate_writer).
- **F2 JSONL session log** — каждый event пишется в `~/.cache/aim/sessions/<run_id>.jsonl` для retro debugging.

### LLM tier chain extended (per user 2026-04-30)

| Tier | Function | Provider chain |
|---|---|---|
| critical | `ask_critical()` | **Claude Opus 4.7** → **Gemini 2.5 Pro** (free 50/d) → DS-V4-pro → Ollama r1 |
| reasoning | `ask_deep()` | DS-V4-pro → Claude Opus → Gemini 2.5 Pro → Ollama r1 |
| long-context | `ask_long()` | DS-V4-flash (1M ctx) → Gemini 2.5 Pro → Ollama |
| default | `ask()` | DS-V4-flash → Gemini Flash → Ollama qwen2.5:7b |
| fast | `ask_fast()` | Groq llama-3.1-8b → DS-V4-flash → Ollama 3b |

Ключи (опционально, в `~/.aim_env`):
- `ANTHROPIC_API_KEY` — premium critical-tier (paid)
- `GEMINI_API_KEY` — **free 50 req/day** на 2.5-pro, sign up at <https://aistudio.google.com/apikey> без credit card

Запуск: `from agents.generalist import run; run("задача", max_iters=12)` → `{answer, trace, tools_used}`.

### Parallelism & Speed

- **Parallel tool calls.** LLM может вернуть `{"parallel": [{tool},{tool}]}` — ThreadPoolExecutor выполняет concurrent (verify_pmid×5, read_file×3, etc).
- **Speculative pre-fetch** (`agents/speculative_prefetch.py`). Фоновый поток смотрит historical context → запускает наиболее вероятные `read_file`/`memory_recall`/`verify_pmid` заранее. Cache hit → instant; mismatch → discarded.
- **Sub-agent fan-out** (`delegate_parallel`). Спавнит N независимых `generalist.run()`-ов параллельно, синтезирует результаты через `ask_critical`.

## Ensemble + adjudication (2026-04-30)

`agents/ensemble.py` — для критичных решений запросить 3 модели (Claude/DS-pro/Ollama) одновременно:
- Если **agreement ≥ 0.35** (Jaccard k-shingle) → consensus, return.
- Если расхождения → adjudicator (Claude Opus 4.7 если есть key, иначе DS-V4-pro) объединяет в один ответ.

Trigger: `agents.ensemble.is_critical(prompt)` — regex по grant/diagnosis/treatment/contract/etc.

## LLM tier chain (cloud-first per user 2026-04-30)

| Tier | Function | Provider chain |
|---|---|---|
| critical | `ask_critical()` | **Claude Opus 4.7** → DS-V4-pro → Ollama r1 |
| reasoning | `ask_deep()` | DS-V4-pro → Ollama deepseek-r1 |
| long-context | `ask_long()` | DS-V4-flash (1M ctx) → Ollama (truncated) |
| default | `ask()` | DS-V4-flash → Ollama qwen2.5:7b |
| fast | `ask_fast()` | Groq llama-3.1-8b → DS-V4-flash → Ollama 3b |

Для использования Claude Opus как critical-tier: `ANTHROPIC_API_KEY` в `~/.aim_env`.

## CLI integration

`medical_system.py` — два новых пункта меню:
- **A** — AI assistant (free-form ReAct loop через `generalist.run()`)
- **R** — Resume previous session (через `agents/session_manager.py`)

## Extended Decision Kernel (non-clinical scope)

К существующим L0–L3 (Asimov) добавлены три закона для не-clinical actions:

- **L_PRIVACY** — блокирует egress пациентских данных (Patients/ paths, phone, DoB, MRN); пропускает только при `context.privacy_consent=True`.
- **L_CONSENT** — блокирует email_send / git_push_public / telegram_broadcast / web_publish без `context.user_confirmed=True`.
- **L_VERIFIABILITY** — каждое emit_text / write_manuscript / send_letter проходит через `tools.literature.enforce_citations(strict)`. Любой нерешаемый PMID/DOI = провал закона.

Per memory `feedback_deepseek_no_citations`: LLM фабрикует DOI — закон делает физически невозможным выдать unverified ссылку наружу.

## Cross-project memory

`agents/memory_index.py` теперь индексирует не только `~/.claude/projects/-home-oem/memory/`, но и core .md (CONCEPT/STATE/THEORY/DESIGN/EVIDENCE/PARAMETERS/OPEN_PROBLEMS/MEMORY) из всех `~/Desktop/<project>/`. Toggle: `AIM_INDEX_DESKTOP_PROJECTS=1` (default).

## Session persistence

`agents/session_manager.py`:
- `start_or_resume()` — picker для CLI (resume последние 5 сессий или start new)
- `on_turn_end()` — каждый turn пишется в `messages` table
- `finalize(sid, summary)` — закрывает session + auto-update `~/Desktop/<project>/STATE.md` если в summary упомянут project

---

## Архитектура

AIM v7.0 — гибридный LLM-роутер. Ядро:

| Файл | Роль |
|------|------|
| `medical_system.py` | Точка входа (CLI), agent loop |
| `aim_gui.py` | GUI (customtkinter), паритет с CLI |
| `telegram_bot.py` | Telegram-бот (python-telegram-bot) с `/link` для multi-user |
| `llm.py` | Роутер: Ollama (local) + DeepSeek-V4 (reasoner/long) + Groq (fast cloud) |
| `config.py` | Ключи, модели, пути, языки |
| `agents/auth.py` | Hub-side: users / JWT / API tokens / audit / link codes |
| `agents/hub_client.py` | Node-side: validate AIM_USER_TOKEN against hub, 24h cache |
| `web/api.py` | FastAPI; `AIM_ROLE=hub`/`node` переключает routes |
| `scripts/user_admin.py` | Hub admin CLI: create / list / token / link-code / nodes / audit |
| `scripts/install_node.{sh,ps1}` | Linux+mac / Windows installer (Ollama + venv + ~/.aim_env) |
| `scripts/install_hub.{sh,ps1}` | Hub installer (минимум deps, бутстрап admin user) |
| `i18n.py` | 9 языков (ООН-6 + KA + KZ + DA) |
| `db.py` | SQLite: пациенты, сессии, кэш |
| `lab_reference.py` | База лабораторных норм (59 аналитов) |
| `agents/doctor.py` | Диагностика, лечение, интерпретация анализов, чат, `check_patient_regimen` |
| `agents/intake.py` | OCR (tesseract/rapidocr), PDF (pymupdf/pdfplumber), WhatsApp, INBOX |
| `agents/lang.py` | Перевод 4 типов, detect, explain_term, simplify |
| `agents/interactions.py` | Drug-drug interaction checker (v0.1 stub, ~30 pairs; P0 audit 2026-04-21). PMID-verified; `check_interaction`, `check_regimen`, `format_regimen_report`. TODO: RxNav/DrugBank integration |
| `tests/test_interactions.py` | Unit tests для `agents/interactions.py` (16 cases) |

---

## Правило LLM

**Никогда не вызывать API напрямую.** Всегда через `llm.py`:

```python
from llm import ask, ask_deep, ask_long, ask_multilang, ask_fast
```

Роутер сам выберет модель.

---

## Правило языков

**9 языков везде.** Ни одна строка UI не пишется жёстко — только через `i18n.py`:

```python
from i18n import t
print(t("menu_title", lang))
```

---

## Пациенты (СТРОГО)

- `Patients/` — **НИКОГДА** не читать, не изменять, не коммитить без явной команды
- Новые файлы → `Patients/INBOX/`
- **Формат папок:** `SURNAME_NAME_YYYY_MM_DD/` где `YYYY_MM_DD` = **дата рождения** пациента
  (определяется auto из анализов через intake pipeline)
- **Если ДР неизвестна ИЛИ сомнительна** → placeholder `2000_01_01` (sentinel: легко
  увидеть в выборках, заведомо не настоящая ДР, требует уточнения у врача).
  Сомнительная = противоречит другим источникам (например, папка датирована визитом
  2026, а в файле внутри ДР 2001) — лучше явный placeholder, чем неверная конкретика.
  Никогда НЕ оставлять без даты (`SURNAME_NAME_/` нарушает naming + ломает intake
  auto-detection)
- **Префикс `_` для AI-сгенерированных файлов:** `_ai_analysis.txt`, `_report_*.pdf`
  (отличает их от исходников: jpeg/pdf от пациента, `*_ocr.txt`/`*_text.txt` — извлечения)
- **Каждая папка должна содержать:** `MEMORY.md` (canonical state, см. `agents/patient_memory.py`)
  + опционально `AI_LOG.md` (создаётся kernel.py при первом decision)
- **Тесты НЕ создают артефакты в `Patients/`** — см. `tests/conftest.py` (PATIENTS_DIR
  изолирован в `tests/_runtime_fixtures/`)

---

## Ключи

Только в `~/.aim_env` (или `%USERPROFILE%\.aim_env` на Windows). Никогда в коде.

```
# Multi-user (если node ходит в hub)
AIM_HUB_URL=https://hub.example.com
AIM_USER_TOKEN=aim_xxx       # выдаёт admin: python -m scripts.user_admin token <user>
AIM_NODE_ID=my-laptop-jaba   # опц. (default: hostname-username)

# LLM
DEEPSEEK_API_KEY=...         # опционально (для reasoner/long-context)
GROQ_API_KEY=...             # опционально (cloud fast tier)
                             # Ollama не требует ключа — только http://127.0.0.1:11434

# Telegram (опц.)
TELEGRAM_BOT_TOKEN=...
TELEGRAM_ALLOWED_IDS=123,456 # static allow-list (или используй /link через hub)
```

---

## Git push

Перед каждым push спрашивать: приватный (`djabbat/AIM`) или публичный (`djabbat/AIM-public`)?

Публичный **исключает**: `CONCEPT.md`, `CLAUDE.md`, `TODO.md`, `PARAMETERS.md`, `Patients/`

---

## При добавлении пункта меню

Изменить **оба** файла: `medical_system.py` + `aim_gui.py` (уже существует).
Источник истины — ключи в `i18n.py` (m1..m8, mq и т.д.).
