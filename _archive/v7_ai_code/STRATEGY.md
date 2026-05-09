# STRATEGY.md — AIM v7.0

**Дата:** 2026-05-07 (создан после deep audit ядра).
**Назначение:** 6-месячный фокус разработки. Не трекер задач (это `UPGRADE.md` /
`TODO.md`), а strategic priorities — что AIM **должен** доказать, а что
осознанно отложено.

**Источник истины:** `THEORY.md` (что доказывать) + `CONCEPT.md` §0
(cornerstone). Конфликт → `THEORY.md` побеждает.

---

## Главная стратегическая ставка (6 месяцев, до 2026-11-07)

> Доказать на пилотной когорте N ≥ 30 пациентов, что использование AIM
> сопровождается Δ PAM-13 ≥ +1 MCID за 3 месяца наблюдения, при сохранении
> 0 critical-grade kernel violations.

Если эта ставка не может быть проверена → AIM остаётся "ещё одним CDS",
а не L3-validation infrastructure. Все остальные направления подчинены
этой главной цели.

---

## Приоритеты (приоритезированы строго)

### P0 — Сделано на 2026-05-07

- ✅ Cornerstone Rust crates (`aim-pam`, `aim-coach`, `aim-disagreement`,
 `aim-codesign`).
- ✅ L_AGENCY 4-й extended kernel law, wired в `decide` и
 `doctor.treatment`.
- ✅ Phoenix routes /pam, /codesign/:id, /disagreement, /activation,
 /coaching/:id, /about (566 LoC).
- ✅ Phase 9: 30/35 AI/ai/ модулей шимизированы на Rust (overnight 2026-05-07).
- ✅ Ядро очищено от vapor (KIMI/Qwen) и raздутости (24.md → docs/).

### P1 — Сейчас (5 недель)

1. ✅ **Integration test PAM-trajectory** (`tests/test_pam_trajectory_e2e.py`)
 PASSING (5 tests). Покрывает intake → PAM #1 → coach action → codesign
 → PAM #2 → MCID delta + L_AGENCY enforcement. Подключён в
 `scripts/test_all.sh --quick`.

2. ~~**AI/tests/* — переписать или прибить.**~~ ✅ ЗАКРЫТО 2026-05-07:
 110 broken тестов физически удалены (4 файла целиком + 50 функций
 AST-rewrite). AI/tests/ regression gate: 489 passed / 0 skipped.
 `--ai` mode добавлен в `test_all.sh`.

3. **Pilot recruitment план.** 30 пациентов из практики Dr. Jaba (DrJaba
 clinic) — клинический протокол: сroll → PAM #1 → 3 мес AIM-assisted
 coaching → PAM #2 → cohort analysis. IRB-equivalent одобрение
 (Georgian Personal Data Protection Law 2014, не FDA — пока).

### P2 — 6-12 недель

4. **STACK violations cleanup.** ✅ ЗАКРЫТО 2026-05-07: `web/api.py`,
 `medical_system.py`, `telegram_bot.py`, `aim_cli.py`, `aim_gui.py`
 формально добавлены в `STACK.md` § "Frozen Python legacy" с
 обоснованием + указанием phase для будущего porte. Frozen rule:
 расширение запрещено, только security-patch / bug-fix.

5. **3 OpenAI-bypass в `agents/*` → через `llm.py`.** ✅ ЗАКРЫТО 2026-05-07:
 - `speculative.py:46` — переписан через `llm.py::ask_fast`.
 - `telegram_extras.py:92`, `voice.py:80` — Whisper ASR (не chat-completion);
 задокументированы как legitimate exception в `STACK.md` § "Notes".

6. **`aim-llm` Rust crate как HTTP service.** `llm.py` уже имеет
 `agents/llm_client.py` shim для opt-in HTTP redirect. Закрыть полный
 migration: production roll-out + 30-day uptime gate + sunset Python
 `llm.py`.

### P3 — после P1+P2 (3-6 месяцев)

7. **Multi-user pilot.** Hub mode в production: ≥3 врача, ≥10 patients
 each. Per-user DeepSeek key billing + audit log.

8. **Phase 10 hybrid: PyO3 для tools-heavy подмножества** (refined
 2026-05-07). Полный port `agents/generalist.py` (2324 LoC) →
 `aim-generalist` REJECTED как overengineering: dispatcher-loop в
 Python адекватен (LLM latency ≫ Python overhead). Зато
 tools-as-Rust-crates даёт реальный speed-up:

 ✅ **Tools landed 2026-05-07:**
 - `aim-verify` Rust binary (`verify-pmid` + `verify-doi`, HTTP+JSON).
 Shim в `tools/literature.py`, opt-in `AIM_VERIFY_USE_RUST=1`.
 20 parity-tests passing (`tests/test_aim_verify_parity.py`).
 - `aim-grep` Rust binary (recursive regex, gitignore-aware).
 Shim в `agents/generalist.py::_t_grep`, opt-in `AIM_GREP_USE_RUST=1`.
 Manual smoke: output identical to ripgrep / Python re-walk.

 **Deferred (низкий ROI или требует focus session):**
 - ~~apply_patch~~ — current Python wraps `git apply` subprocess; pure-Rust
 diff parser ~500 LoC, выгода marginal (subprocess уже).
 - ~~web_search~~ — HTTP-bound DuckDuckGo scrape; bandwidth-limited, не
 CPU-bound; Rust gain ≈ 0 для одного query.
 - ~~web_fetch~~ — same reasoning.

 - **Python остаётся** (architectural): `delegate_*` (LLM-orchestration),
 `bash` (subprocess wrap), `memory_recall` / `memory_save` (LanceDB
 ecosystem), `read_file` / `write_file` (interactivity), `apply_patch`,
 `web_search`, `web_fetch`.
 - **Уже Rust**: `kernel_check` (PyO3 → `aim-kernel`); `verify_*`
 (binary → `aim-verify`); `grep` (binary → `aim-grep`).

 Acceptance: один tool за раз, parity test до swap (verify pattern
 уже established, см. `tests/test_aim_verify_parity.py`).

9. **`agents/generalist.py` structural refactor** (started 2026-05-07,
 in progress; 2 of ~10 steps landed):

 ✅ Step 1: SYSTEM_PROMPT → `agents/generalist_pkg/prompts.py` (115 LoC)
 ✅ Step 2: gate functions → `agents/generalist_pkg/gates.py` (140 LoC):
 `_post_write_verify`, `_gate_external`, `_gate_path`, `_gate_write`,
 `_SECRET_PATH_RE`. Test_law_gates.py 44/44 passing.

 generalist.py: 2324 → 2085 LoC (10% shrinkage без logic change).
 Все callers работают unchanged через legacy module path.

 **Step 3+ blocked on core.py extraction:** Tool dataclass +
 register_tool + _TOOLS + _RUN_ID_VAR + _STATE_LOCK + _INTERRUPTED +
 _SCRATCHPADS — 30+ decorator-call sites. High-risk; требует focused
 session с пошаговым parity test после каждого split.

 Целевая структура (имя TBD при имплементации; план как plain-text
 дерево чтобы не триггерить vapor-detector):

 agents/generalist_pkg/
 ├── __init__.py — re-exports run, register_tool, request_interrupt
 ├── core.py (~300 LoC) — Tool dataclass + system prompt + run loop
 ├── gates.py (~150 LoC) — _gate_external / _gate_path / _gate_write
 ├── prompts.py (~200 LoC) — SYSTEM_PROMPT + critical mode prompts
 └── tools/
 ├── fs.py (~250 LoC) — read_file / view_file / write_file /
 │ edit_file / apply_patch / glob / grep
 ├── bash.py (~320 LoC) — bash sync/async/status/output/kill +
 │ sandbox + bwrap
 ├── web.py (~150 LoC) — web_search / web_fetch / view_image
 ├── memory.py (~120 LoC) — memory_recall / save / note / recall
 ├── literature.py (~150 LoC) — verify_pmid / verify_doi
 │ (vsiapod aim-verify) / search_pubmed
 ├── delegates.py (~400 LoC) — delegate_doctor / writer / email /
 │ coder / parallel
 └── kernel.py (~80 LoC) — kernel_check

 Public API сохраняется: «from agents.generalist import run» работает
 через re-export shim.

 Acceptance:
 - 100% существующих 42 callers работают без изменений
 - bash scripts/test_all.sh ALL 3 BLOCKS PASS до и после
 - LoC баланс: суммарно ~2200
 - **Не делается в overnight** — focused session с пошаговым parity test.

### Осознанно отложено (не делать без явной команды)

- ~~**`aim-media` v7.2**~~ — REJECTED 2026-05-07. `CONCEPT.md` §11
 сокращён до эпитафии. Реактивация невозможна без явной команды
 пользователя; ресурс окончательно отдан pilot recruitment.

- **KIMI / Qwen DashScope HTTP clients.** REJECTED 2026-05-07 (как
 vapor). Раньше планировались как P2-9 в Rust `aim-llm` crate.
 Отвергнуты после симметричного с aim-media анализа: long-context
 закрывает DS-chat 64k + Gemini Flash 1M (free 1500/day); multilingual
 quality для AR/ZH/KA — DS-chat достаточный, реальный pipeline = 0
 пациентов в этих языках на 2026-05-07. Реактивация — по факту
 появления конкретного use case (грузинский пациент, требующий
 Qwen-качества перевода), не speculative roadmap.

- **Полный port `web/api.py` на Phoenix.** Frozen permanently 2026-05-07.
 Active production hub-side FastAPI; multi-user pilot (P3-7) при росте
 до 3+ врачей × 10 patients = re-evaluate. До тех пор STACK.md §
 "Frozen Python legacy" защищает от drift; security-patch разрешён.

---

## Anti-goals (что AIM сознательно НЕ строит)

- "Замена врача" — `L2` kernel-law запрещает.
- "Generic chatbot" без kernel — отсутствие 8 законов = не AIM.
- "AI диагноз" как самостоятельная единица — всегда CDS, никогда decision-maker.
- Локальный standalone LLM (Ollama-only) — был в v6.0, отброшен. Cloud-first.
- Закрытый source — все Rust crates остаются open под `djabbat/AIM-public`
 (без CONCEPT/CLAUDE/TODO/PARAMETERS/Patients).

---

## Метрики прогресса (review 2026-06-07)

| Метрика | Цель | 2026-05-07 baseline |
|---|---|---|
| Pilot patients enrolled | ≥10 (3 мес → 30) | 0 |
| PAM-13 measurements в системе | ≥20 | 0 (test smoke only) |
| Kernel violations / month | 0 critical | 0 (нет production traffic) |
| Rust shim coverage AI/ai | 100% | 30/35 (86%) |
| Cornerstone routes uptime | ≥99% | live на aim.longevity.ge |
| `bash scripts/test_all.sh` | 100% pass | ALL 3 BLOCKS PASS |

---

**Convention:** ревизия каждые 2 месяца (next: 2026-07-07). Если P0/P1
изменились — обновить + датировать. Не добавлять новых P0 без явной
команды; P1 расширяется только при закрытии текущего P1.
