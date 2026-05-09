# AUDIT — Fixes #1-4 Empirical Verification (2026-05-07, post-fixes)

**Скоуп:** второй аудит после завершения Fix #1-4. Цель — убедиться, что
фиксы (a) реально работают в production-flow, не только в unit-тестах,
(b) не создали скрытых регрессий, (c) не оставили других мест, нарушающих
stack rule аналогично Phase 7.

**Метод:** 2 параллельных Explore-агента + verification grep + Phoenix
`mix phx.routes`. Все findings верифицированы вручную.

---

## TL;DR

| Fix | Empirical status | Issue found |
|---|---|---|
| #1 — L_AGENCY в `decide` | ✅ работает в основной цепи (doctor / medical_system) | 🔴 **2 callsite пропускают activation_level**: `labs.py:360-365`, `chat.py:359-365` (HIGH) |
| #2 — Python → Rust shims | ✅ 3 шима тонкие, тесты зелёные | 🟠 7 ДРУГИХ Python модулей нарушают stack rule так же как Phase 7 (MEDIUM) |
| #3 — Phoenix LiveViews | ✅ 5 routes зарегистрированы, компиляция чистая | 🟢 OK |
| #4 — docs sweep | ✅ MAP/CLAUDE/UPGRADE/MIGRATION обновлены | 🟢 OK |

**Severity свод:** 1 HIGH (L_AGENCY bypass в 2 callsite), 1 MEDIUM (7 stack-rule violation для Phase 8), 0 CRITICAL.

---

## 1. Fix #1 — L_AGENCY в `decide` — РАБОТАЕТ С ДЫРОЙ

### Что подтверждено

- `kernel.decide` в Rust (PyO3-default) и Python legacy теперь вызывает
 `evaluate_extended_with_patient` для каждой alternative.
- `Scored.extended` exposed; 5 новых тестов в `test_kernel_extended.py`
 проверяют block / pass-when-codesigned / pass-disengaged / Scored.extended.
- Production callsite `medical_system.py:308,364,381,395` все используют
 `mem.to_kernel_dict` который auto-populate `activation_level` через
 `pam_tracker`. ✅
- `agents/doctor.py:246,423` (triage / treatment) передают patient dict
 через тот же `to_kernel_dict`. ✅
- Rust workspace `cargo check --all` — clean (90+ crates compile).

### 🔴 Найденная дыра

**`agents/labs.py:360-365`** и **`agents/chat.py:359-365`** конструируют
`patient` dict вручную через `setdefault` для 6 полей, но **НЕ
устанавливают `activation_level`**. В результате при попадании в `decide`:

```python
# labs.py:343 пример
p = {..}
p.setdefault("age", 40)
p.setdefault("allergies", [])
#.. ещё 4 setdefault, но НЕТ activation_level..
result = decide([test_action, treatment_action], p,..)
```

→ `evaluate_l_agency` видит `activation_level=0` (default) → треатируется
как «disengaged / unknown» → **pass-with-flag** → закон **не блокирует**
treatment даже для активированного пациента.

### Fix (тривиальный, ≤10 LoC)

```python
# В обоих местах добавить:
from agents import pam_tracker
p.setdefault("activation_level",
 pam_tracker.current_activation_level(p.get("id", "")))
```

### Также найдено: log_decision не пишет extended

`agents/kernel_legacy.py::log_decision` сериализует `Scored` в SQLite +
`AI_LOG.md`, но **не упоминает `extended`**. Закон сработал и заблокировал
treatment — но в audit log этого не видно. Severity = MEDIUM (security
theatre если кто-то полагается на log для compliance review).

---

## 2. Fix #2 — Python → Rust shims — ПОДТВЕРЖДЕНО + новый scope

### Что подтверждено

- `agents/pam_tracker.py` (137 LoC) — pure subprocess wrapper над
 `aim-pam` binary. Все scoring/persistence/delta — в Rust. ✅
- `agents/automation_bias_detector.py` (75 LoC) — pure subprocess wrapper. ✅
- `agents/codesign_log.py` (100 LoC) — pure subprocess wrapper над
 `aim-codesign`. ✅
- 71/71 Python kernel + Phase 7 integration tests pass. Tests для шимов
 фактически тестируют Rust binaries через subprocess.

### 🟠 Новый scope: 7 ДРУГИХ Python файлов нарушают то же правило

Сверены имена `agents/*.py` против `rust-core/crates/aim-*`. **Все 12
упомянутых Rust crates существуют** (verified by `ls -d`). Из них 7
соответствуют Python файлам, которые НЕ являются shim'ами а делают
независимую реализацию:

| Python файл | Rust crate | Природа дублирования | LoC ~ |
|---|---|---|---|
| `agents/smart_routing.py` | `aim-smart-routing` | tier classification + cost calc дублируется | ~250 |
| `agents/router_ab_test.py` | `aim-ab-router` | A/B-trial loop independent | ~200 |
| `agents/regimen_validator.py` | `aim-regimen-validator` | severity checker (Python wraps `interactions.py`) | ~150 |
| `agents/resilient_llm.py` | `aim-resilient-llm` | tenacity-retry; Rust имеет аналог через tokio | ~200 |
| `agents/reflexion.py` | `aim-reflexion` | reflection memory / persistent cache | ~600 |
| `agents/generalist.py` (часть) | `aim-generalist` | tool-dispatch loop | ~600 (всего; портируется частично) |
| `agents/graph.py` | `aim-graph` | LangGraph state machine | ~150 |

**Всего ~2150 LoC к портированию в Phase 8.** Severity = MEDIUM (не
критично, но technical debt растёт чем дольше живут параллельные пути).

### Compliant shims/wrappers (для контраста)

`agents/kernel.py` (PyO3 import shim), `agents/pam_tracker.py`,
`agents/automation_bias_detector.py`, `agents/codesign_log.py` — 4 файла
делают именно то, что должны.

### Подтверждённый legacy (по STACK.md exception)

`agents/intake.py` (OCR/PDF), `agents/lang.py` (langdetect),
`agents/email_agent.py` (Gmail), `agents/voice.py` (Whisper),
`telegram_*.py`, `aim_gui.py` (customtkinter), `web/api.py` (FastAPI →
будет Phoenix позже).

---

## 3. Fix #3 — Phoenix LiveViews — ВСЁ OK

`mix phx.routes AimWeb.Router | grep -E "(/pam|/codesign|/disagreement|/activation)"`:

```
GET /pam AimWeb.PamLive :cohort
GET /pam/:patient_id AimWeb.PamLive :patient
GET /codesign/:patient_id AimWeb.CodesignLive :index
GET /disagreement AimWeb.DisagreementLive :index
GET /activation AimWeb.ActivationLive :index
```

Все 5 routes зарегистрированы. `mix compile` — clean. Что я НЕ проверил
(вне scope аудита кода): фактический рендеринг через `mix phx.server` +
curl. Это требует boot'а сервера и mock-данных.

**Открытый риск** (LOW): шаблоны рендера могут упасть в edge-case'ах
(например, `Float.round(integer * 1.0, 1)` для `score` который Rust
сериализует как int если он целочисленный) — но это runtime не
compile-time.

---

## 4. Fix #4 — docs sweep — ВЫПОЛНЕНО

Обновлены: `CLAUDE.md` (cornerstone section с реальным списком
done/deferred), `MAP.md` (новые crates + Python шимы + LiveViews
добавлены в §2), `UPGRADE.md` (новый раздел `v7.4 — Patient as a Project
cornerstone` с ✅ для всех Phase 1-7 + Fix #1-3), `MIGRATION_RUST_PHOENIX.md`
(Phase 5 «Patient as a Project cornerstone» добавлен).

⚠️ Что НЕ обновил: `STACK.md` — нужно ли? Он описывает правило, не
implementation status, поэтому не требует обновления. Достаточно
сослаться из UPGRADE.md.

---

## Recommended next actions (priority order)

1. 🔴 **Закрыть L_AGENCY hole** в `labs.py` + `chat.py` (≤30 мин,
 2 файла, ≤10 LoC, регрессионный тест уже есть в
 `test_kernel_extended.py:test_decide_blocks_treatment_for_activated_patient_without_codesign`).
2. 🟠 **Логировать Scored.extended в `log_decision`** для compliance
 audit trail (≤30 мин).
3. 🟢 **Phoenix smoke** — запустить `mix phx.server` в фоне, curl 5
 новых routes, проверить что рендер не падает с пустыми JSONL
 (≤15 мин).
4. 🟠 **Phase 8 plan** — формальный roadmap для 7 violation Python
 файлов (≤2150 LoC). Предлагаемый порядок:
 - Week 1: smart_routing, router_ab_test (hot path; влияют на cost)
 - Week 2: regimen_validator (clinical safety)
 - Week 3: resilient_llm (infrastructure)
 - Phase 9: reflexion, generalist, graph (большие, требуют
 re-design tool schema)

---

## Honest self-assessment

Первый аудит нашёл 2 CRITICAL bugs (L_AGENCY dead, stack rule violation
Phase 7). Этот второй аудит нашёл 1 HIGH (L_AGENCY hole в labs/chat) +
расширил scope с 3 файлов до 7 файлов в Phase 8. Это нормальная
прогрессия — каждый новый аудит копает чуть глубже. После этого пакета
исправлений достаточно проверить #1-3 из recommended actions, и
cornerstone «Patient as a Project» будет полностью операционализирован
во всех клинических путях.
