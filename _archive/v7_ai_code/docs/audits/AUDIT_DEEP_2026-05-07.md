# Сверхглубокий аудит AIM — 2026-05-07

**Скоуп:** вся кодовая база AIM после 14ч overnight-сессии 2026-05-07.
**Метод:** 5 параллельных Explore-агентов (Rust workspace · Python↔Rust integration · Phoenix · Security/kernel · CONCEPT-coherence) + ручная инвентаризация non-Rust/non-Phoenix кода.

---

## 0. TL;DR

**Состояние: B− (хорошее ядро, незакрытые дыры в integration + scope).**

✅ **Сильно:** Asimov-kernel (62 tests) + cornerstone Rust crates (aim-pam/coach/disagreement/codesign — 44 tests) + 192 Rust crates compile clean (19 warnings, все стилистические) + Phoenix umbrella с 14 routes (включая 6 cornerstone) + 1287 Python tests passing.

🔴 **Дыры:**
1. **L_AGENCY был мёртвым в production** — Fix #1 закрыл только в `decide`; `doctor.treatment` всё ещё пропускает `activation_level` (MEDIUM, ~5 LoC fix).
2. **49 800+ LoC Python остаётся** (не считая тестов/скриптов): 30 782 в `agents/`, 14 806 в `AI/ai/`, ~5 000 top-level — параллельные реализации существующим Rust crates. **Это в 80× больше чем portировано в Phase 8**.
3. **`aim-llm` HTTP-сервис: 0 unit tests** на `/v1/chat` + `/v1/ensemble` (CRITICAL для production).
4. **`aim-coach` isolated** — 17 tests pass, есть Phoenix LiveView, но НИ ОДИН Python production-callsite не вызывает его.
5. **Phoenix CSS отсутствует** — все cornerstone LiveViews рендерятся как unstyled HTML. i18n cornerstone routes hardcoded EN.
6. **3 CONCEPT.md устарели** относительно реализации (HAP/Ontogenesis помечены TOXIC, но папки живые; `aim-media` упомянут в § 11 как done, но crate не существует).

---

## 1. Rust workspace (192 crates)

### 1.1 Шкала использования
| Категория | # crates | Статус |
|---|---|---|
| Binaries в systemd / production callsites | ~22 | ✅ active |
| Library-only с >0 callers через `path =..` | ~30 | ✅ active |
| Library-only БЕЗ callers (untested + unused) | ~140 | 🟡 dead-code candidates |

**Топ-5 ядра:** `aim-kernel` (2105 LoC, 62 tests) · `aim-patient-memory` (1481 LoC, 31) · `aim-hub-auth` (984, 20) · `aim-escalation` (938, 17) · `aim-orchestrator` (919, 26).

### 1.2 Тесты
- 15 crates имеют ≥1 unit test → **~92% workspace без тестов**
- Это не катастрофа (часть testing идёт через subprocess callsites из Python), но `aim-llm` (716 LoC, **0 tests**) — реальный технический долг.

### 1.3 Compilation
- `cargo build --workspace` clean (debug ~5s; release ~30s)
- 19 warnings (4× unused PyO3 params; 12× UPPERCASE-naming для Asimov constants; 1× dead method) — все стилистические, безопасные

### 1.4 Recommended actions
- 🔴 Add tests на `aim-llm::router::chat` (provider failover, cache hit, timeout, malformed input)
- 🟡 Decide `aim-coach`: integrate в Python callsite ИЛИ delete (currently 17 tests + Phoenix LiveView, но не вызывается из production agent loop)
- 🟢 Cleanup: `cargo tree` audit для unreachable crates

---

## 2. Python ↔ Rust integration

### 2.1 Действующие шимы (Phase 7 + 8)
| Python | LoC | Rust binary | Tests |
|---|---|---|---|
| `agents/pam_tracker.py` | 137 | `aim-pam` | 5 в test_phase7 |
| `agents/automation_bias_detector.py` | 75 | `aim-disagreement` | 4 |
| `agents/codesign_log.py` | 100 | `aim-codesign` | 6 |
| `agents/smart_routing.py` | 121 | `aim-smart-routing` | 8 в test_phase8 |
| `agents/reflexion.py` | 106 | `aim-reflexion` | 5 |
| `agents/interactions.py` | 192 | `aim-interactions` | 16 |
| `agents/regimen_validator.py` | 192 (hybrid) | `aim-regimen-validator` | 18 |
| `agents/llm_client.py` | 121 | `aim-llm` HTTP | 7 |
| `agents/kernel.py` | 70 | `aim-kernel` (PyO3) | 22 |

### 2.2 Несоответствия
- `agents/llm_client.py` 121 LoC opt-in shim **никем не импортируется** (нужен env `AIM_LLM_HTTP_URL` + production-deployment `aim-llm` сервис).
- 4 файла в `agents/*.py` >300 LoC с прямыми Rust counterparts: `generalist.py` (2324) → `aim-generalist` · `graph.py` (942) → `aim-graph` · `doctor.py` (578) → `aim-doctor` · `chat.py` (430) → `aim-chat`. **Не shimmed**, остаются параллельные реализации.

### 2.3 PyO3 bindings
- **Только `aim-kernel-py`** имеет PyO3 binding. Остальные cornerstone crates (aim-pam, aim-disagreement, aim-codesign) → subprocess (медленнее, но проще).

---

## 3. Phoenix LiveView frontend

### 3.1 Routes (14)
- `/`, `/chat`, `/intake`, `/cases`, `/cases/:id`, `/consult`, `/dashboard`, `/drugs`, `/settings` — 9 базовых
- `/patients`, `/experiments` — 2 lifecycle dashboards (Phase A/B)
- `/pam`, `/pam/:id`, `/codesign/:id`, `/disagreement`, `/activation`, `/coaching/:id` — 6 cornerstone (Phase 4 + Fix #3)

### 3.2 LiveView modules
17 файлов в `apps/aim_web/lib/aim_web_web/live/`, 1923 LoC.

### 3.3 Дыры
🔴 **CSS отсутствует.** Нет `priv/static/app.css` ни inline `<style>`. `class="aim-pam"` / `class="level-3"` / `class="zone-aligned"` определены, но без правил — UI будет неструктурированным HTML.

🔴 **Cornerstone routes hardcoded EN.** `<h1>📊 PAM-13 cohort</h1>` вместо `<%= t("pam.cohort.title", @locale) %>`. Russian users не увидят перевод.

🟡 **0 LiveView тестов.** `apps/aim_web/test/` содержит только `i18n_test.exs`. `mount` / `handle_info(:tick)` / `System.cmd` failure paths не покрыты.

🟢 **Robust fallback на Rust binary missing** — все LiveViews используют `Path.join → Enum.find(&File.exists?/1)` + `case System.cmd → {_, 0}` pattern. Graceful degradation.

🟢 **Production-ready systemd unit** — `deploy/systemd/aim-phoenix.service` с `Type=simple`, `Restart=always`, `ProtectSystem=strict`.

---

## 4. Security + kernel enforcement

### 4.1 Закон-by-закон
| Закон | Статус | Where |
|---|---|---|
| L0 (danger) | ✅ enforced | doctor/labs/chat/triage все через `kernel.decide` |
| L1 (patient harm) | ✅ enforced | + drug interaction check в treatment |
| L2 (override) | ✅ enforced | hard override НЕ обходит L0+L1+extended |
| L3 (destructive) | ✅ enforced | rm/git-reset/DROP-TABLE blocked |
| L_PRIVACY | ✅ enforced | dual gate: orchestrator + inline в email_agent / generalist |
| L_CONSENT | ✅ enforced | + interactive broker via AIM_INTERACTIVE_CONSENT |
| L_VERIFIABILITY | ⚠️ tested, production unclear | tools/literature.enforce_citations exists |
| L_AGENCY | 🟡 partial | работает в chat.py + labs.py + medical_system; **GAP в `doctor.treatment` line 423** |

### 4.2 Decision callsites
```python
doctor.triage ✓ activation_level не нужен (action_type=triage)
doctor.treatment 🟡 GAP — activation_level НЕ populated → L_AGENCY no-op
chat.respond ✓ pam_tracker.current_activation_level
labs.interpret_kernel ✓ pam_tracker.current_activation_level
medical_system.* ✓ через mem.to_kernel_dict auto-populate
```

### 4.3 Audit trail
- ✅ `ai_events` SQLite WAL-mode, indexed, `extended_json` column added 2026-05-07
- ✅ Per-patient `AI_LOG.md` с extended laws ✅/❌ + reasons
- 🟡 No documented retention policy для AI_LOG.md (можно расти неограниченно)

### 4.4 Secrets
- ✅ `~/.aim_env` permissions 600
- ✅ `grep -rE "sk-[A-Za-z]" src/` → no hardcoded keys
- ✅ Multi-user hub mode: JWT + per-user API tokens, isolated patient dirs

---

## 5. CONCEPT-coherence

### 5.1 Соответствие
- AIM/CONCEPT v7.0 заявляет «аим-coach + aim-pam + aim-disagreement + L_AGENCY» — все есть в коде ✅
- LongevityCommon/CONCEPT v5.6: helmsa-cтруктура верна ✅
- PATIENT_AS_PROJECT.md cornerstone: Phoenix routes все ✅, Rust crates все ✅

### 5.2 Расхождения
| Severity | Расхождение |
|---|---|
| 🔴 CRITICAL | AIM/CONCEPT § 11 описывает **`aim-media`** (TTS/Image/Video/3D) как Phase 8 v7.2, но crate **не существует**. § 11 = roadmap, не current state. |
| 🟡 HIGH | LongevityCommon/CONCEPT § 3 помечает HAP/Ontogenesis как TOXIC/halted, но папки `~/Desktop/LongevityCommon/HAP/` + `Ontogenesis/` физически существуют с файлами. |
| 🟡 HIGH | MAP.md, UPGRADE.md, MIGRATION_RUST_PHOENIX.md — обновлены **только частично** на 2026-05-07 (новые crates Phase 5+8 не везде попали). |
| 🟠 MEDIUM | SSA/CONCEPT + DiffDiagnosis/CONCEPT не упоминают cornerstone integration (новые `patient_activation_level` fields, добавленные сегодня). |

---

## 6. **Non-Rust / non-Phoenix code inventory** (отвечая на текущий запрос)

### 6.1 Python остаётся: ≈73 902 LoC в 329 файлах

| Папка | LoC | Файлов | Стек-rule статус |
|---|---|---|---|
| `agents/` | **30 782** | 124 | смешанный: 9 шимов (Phase 7+8) + ~115 ещё Python-legacy |
| `AI/ai/` | **14 806** | 35 | 🔴 параллельная реализация существующим **30 aim-ai-\* Rust crates** |
| `tests/` | 15 593 | 83 | OK — тесты могут быть Python (pytest) |
| Top-level (`*.py`) | 5 053 | 16 | смешанный: `medical_system.py` (656) · `llm.py` (1017) · `telegram_bot.py` (610) · `aim_cli.py` (656) · `aim_gui.py` · `db.py` · `config.py` · etc. |
| `scripts/` | 2 403 | 14 | OK — install/migration scripts (acceptable) |
| `web/` | 1 120 | 4 | 🔴 `web/api.py` 772 LoC FastAPI — **должен быть Phoenix** |
| `tools/` | 593 | 4 | смешанный (literature.py — citation verifier) |
| `cli/` | 528 | 3 | OK |
| `export/`, `experiments/`, `migrations/` | ~1 100 | ~7 | OK (одноразовое) |

**Итого LoC, нарушающего стек-правило:** ~50 000 LoC (без тестов и однократных скриптов).

### 6.2 Топ-10 крупнейших Python файлов
| Файл | LoC | Rust counterpart | Действие |
|---|---|---|---|
| `agents/generalist.py` | 2 324 | `aim-generalist` (705 LoC, есть main.rs) | 🔴 крупнейший violation |
| `agents/kernel_legacy.py` | 1 043 | `aim-kernel` (porting done, но Python остался как fallback) | OK с пометкой "legacy fallback" |
| `llm.py` | 1 017 | `aim-llm` (HTTP service, ready) | 🔴 нужен переключатель Python ↔ HTTP shim |
| `DiffDiagnosis/_build_kernel.py` | 963 | — (build script) | OK |
| `agents/graph.py` | 942 | `aim-graph` (576 LoC) | 🟡 заблокирован Phase 5 |
| `SSA/_build_kernel.py` | 860 | — (build script) | OK |
| `web/api.py` | 772 | — (FastAPI; должен быть Phoenix) | 🔴 миграция в Phoenix |
| `tests/test_law_gates.py` | 668 | — (тест) | OK |
| `aim_cli.py` | 656 | `aim-cli` (есть скелет) | 🟡 |
| `telegram_bot.py` | 610 | `aim-telegram-bot` (есть crate) | 🟡 заблокирован python-telegram-bot lib |

### 6.3 Frontend assets
21 файл JS/CSS/HTML — все vendor (daisyui, heroicons, topbar) + 3 Phoenix `app.js`/`app.css`. Всё в порядке.

### 6.4 Что осталось `not Rust / not Phoenix`?
**Реальный non-compliant код:**
1. 🔴 **`AI/ai/`** — 14 806 LoC Python, 30 параллельных Rust crates `aim-ai-*` существуют, но интеграция не сделана
2. 🔴 **`web/api.py`** — 772 LoC FastAPI; routes должны быть в Phoenix
3. 🔴 **`agents/generalist.py`** — 2 324 LoC tool-using executor; aim-generalist crate (705 LoC) ждёт integration
4. 🟡 **`llm.py`** — 1 017 LoC; `aim-llm` HTTP-сервис готов, нужен только switch via `agents/llm_client.py`
5. 🟡 **`telegram_bot.py`** — 610 LoC python-telegram-bot; миграция требует Rust telegram client lib
6. 🟡 **`aim_gui.py`** — customtkinter GUI; **нет Rust GUI alternative** → официально legacy-exception
7. 🟢 **`tests/`** — 15 593 LoC pytest; legitimate (Python для тестов acceptable)
8. 🟢 **`scripts/install_*.sh`** — bash scripts; legitimate
9. 🟢 **`agents/intake.py`** — OCR/PDF (tesseract/rapidocr/pymupdf); **нет зрелых Rust альтернатив** → legacy-exception
10. 🟢 **`agents/lang.py`, `email_agent.py`, `voice.py`** — Gmail API / langdetect / faster-whisper; legacy-exceptions

---

## 7. Critical remediation plan

### Priority 1 (this week)
1. **Fix `doctor.treatment:423`** — ~5 LoC (add `pam_tracker.current_activation_level` populate). Закрывает реальную дыру L_AGENCY в clinical pathway.
2. **`aim-llm` unit tests** — добавить provider-failover / cache / timeout / malformed-input tests (≥10 cases).
3. **Phoenix CSS** — встроить `<style>` в `root.html.heex` с правилами для cornerstone классов; иначе UI неприемлемый.
4. **i18n cornerstone routes** — extract все `<h1>`/labels в `i18n.ex` keys.

### Priority 2 (next sprint)
5. **`aim-coach` integration** — либо delete crate, либо подключить в Python coach loop через subprocess.
6. **`web/api.py` → Phoenix** — миграция 772 LoC FastAPI → Phoenix routes (значимая работа, ~2 days).
7. **CONCEPT.md sweep** — § 11 (`aim-media`) переместить в `PHASE_X_ROADMAP.md`; HAP/Ontogenesis папки либо удалить, либо обновить статус в LongevityCommon/CONCEPT.
8. **MAP/UPGRADE/MIGRATION docs** — синхронизировать с реальными 2026-05-07 артефактами.

### Priority 3 (Phase 9+, multi-week)
9. **`AI/ai/` → `aim-ai-*` shims** — 35 файлов × ~1 day each = ~7 weeks работы; самый крупный остаточный non-compliant блок (14 806 LoC).
10. **`agents/generalist.py` → `aim-generalist`** — 2 324 LoC; требует tool ABI design (PyO3 vs subprocess vs FFI).
11. **`agents/graph.py` → `aim-graph`** — заблокирован Phase 5 (HTTP-shim для llm.py).
12. **LiveView integration tests** — ≥5 test cases per cornerstone route.

### Out of scope (legitimate Python legacy)
- `agents/intake.py` (OCR/PDF), `lang.py` (langdetect), `email_agent.py` (Gmail API), `voice.py` (Whisper), `aim_gui.py` (customtkinter) — нет зрелых Rust альтернатив; задокументировать в `STACK.md`.
- `scripts/*.sh`, `tests/*.py`, `_build_kernel.py` build scripts — bash/pytest legitimate.

---

## 8. Цифры (сводная таблица)

| Метрика | Значение |
|---|---|
| Rust crates | 192 |
| Rust unit tests (top 10 cornerstone+kernel) | 244 |
| Rust binary outputs в `target/release/` | 22 |
| Phoenix LiveViews | 17 (1 923 LoC) |
| Phoenix routes | 14 (6 cornerstone) |
| Python files | 329 |
| Python LoC (total) | 73 902 |
| Python LoC (non-test, non-script, non-build) | ~52 000 |
| Python LoC stack-rule violation | ~50 000 |
| Python tests passing | 1 287 + 34 subtests |
| Memory rules додано в этой сессии | 3 |
| Audit-документов в репозитории | 4 (CORNERSTONE/PATIENT_AS_PROJECT/PROJECT_MANAGER/FIXES_VERIFICATION + this) |

---

## 9. Финальная оценка

**Кодовая база:**
- Ядро (Rust kernel + cornerstone crates) — ✅ production-grade
- Phoenix UI — 🟡 functional но без CSS/i18n
- Python legacy — 🔴 50 000 LoC ещё ждёт миграции

**Соответствие декларациям (CONCEPT/cornerstone):**
- Заявленное реализовано на ~80%
- 1 CRITICAL gap (L_AGENCY в doctor.treatment) + 6 HIGH gaps (aim-media в CONCEPT vs реальность · CSS/i18n · 4 крупных Python violations)

**Безопасность:**
- 7/8 законов enforced полностью
- L_AGENCY на 95% — один callsite (`doctor.treatment`) пропускает activation_level

**Honest summary:** AIM сегодня — солидное ядро + впечатляющая overnight-миграция (cornerstone + 4 Phase 8 ports + Phase 4 + Phase 5 service), но **существенная часть legacy Python остаётся**. Перед production v1.0 нужно: закрыть L_AGENCY hole в treatment + добавить тесты на aim-llm + Phoenix CSS + i18n + decide aim-coach status.
