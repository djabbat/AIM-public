# Kernel port to Rust — анализ + предложение плана

**Дата:** 2026-05-07
**Контекст:** Финальный шаг STACK rule «всё в Rust». `agents/kernel.py` (Asimov decision kernel + Ze utility + extended laws) — самый центральный, самый связанный, самый safety-critical модуль AIM.
**Статус:** Анализ. Решение по плану — за тобой.

---

## 1. Что есть сейчас

### 1.1 Python kernel.py — 930 LoC

**Public API (30 функций/классов):**

| Категория | Функции / классы |
|---|---|
| Data classes | `Decision`, `LawsResult`, `ExtendedLawsResult`, `ScoringResult`, `Scored`, `OverrideContext`, `KernelViolation` |
| Asimov L0-L3 | `evaluate_l0`, `evaluate_l1`, `evaluate_l2`, `evaluate_l3`, `evaluate_laws` |
| Extended laws | `evaluate_l_privacy`, `evaluate_l_consent`, `evaluate_l_verifiability`, `evaluate_extended` |
| Impedance / Ze | `impedance_checklist`, `impedance_llm_delta`, `impedance`, `expected_impedance_after`, `phi_ze_path_integral`, `instant_c` |
| Ethics | `ethics_ze_score`, `ethics_autonomy`, `ethics_beneficence`, `ethics_nonmaleficence`, `ethics_justice`, `ethics_composite` |
| Scoring + decide | `score_decision`, `decide` |
| Logging | `_ensure_ai_events_table`, `log_decision` |
| Display | `format_compact`, `format_verbose`, `needs_clarification` |

**Зависимости Python kernel.py:**
- `config.KernelWeights` (struct), `config.PATIENTS_DIR`, `config.LOGS_DIR` — Python-only
- `db._conn`, `db.init_db` (через _ensure_ai_events_table) — Python-only
- `llm.ask_fast` (для `impedance_llm_delta` LLM-judge edge case) — Python-only, но `aim-llm` Rust crate существует
- Filesystem: `PATIENTS_DIR/<id>/AI_LOG.md` writes — портируется тривиально
- Standard lib: json, sqlite3, time, dataclasses

**Callers (7 production agents + 9 test files):**
- `agents/orchestrator.py` (492 LoC) — главный caller через `evaluate_laws`, `evaluate_l_*`, `score_decision`
- `agents/labs.py` (408 LoC) — использует `decide` для ranking lab interpretation alternatives
- `agents/doctor.py` (578 LoC) — `decide` для diagnostic ranking
- `agents/chat.py`, `agents/generalist.py` (2324 LoC), `agents/email_agent.py`, `agents/writer.py` — частичное использование
- 9 test файлов: `test_kernel.py` (274), `test_kernel_extended.py` (82), `test_kernel_scenarios.py` (329), `test_law_gates.py`, `test_orchestrator_reflexion.py`, `test_chat.py`, `test_labs.py`, `test_permission_broker.py`, `test_treatment.py`

**Тесты Python:** ~80+ тестов в test_kernel*.py (685 LoC всего). `pytest tests/test_kernel*.py` проходят зелёные (проверено в этой сессии).

### 1.2 aim-kernel Rust scaffold — 1069 LoC + 34 теста (уже есть)

**Что портировано:**
- ✅ Все data structs: `Decision`, `Patient`, `Context`, `LawsResult`, `ExtendedLawsResult`, `ScoringResult`, `KernelWeights`, `EthicsParts`, `CitationCheckResult`, `Medication`
- ✅ Все Asimov: `evaluate_l0`, `evaluate_l1`, `evaluate_l2`, `evaluate_l3`, `evaluate_laws`
- ✅ Extended laws: `evaluate_l_privacy`, `evaluate_l_consent`, `evaluate_l_verifiability`, `evaluate_extended`
- ✅ Все ethics: `ethics_ze_score`, `ethics_autonomy`, `ethics_beneficence`, `ethics_nonmaleficence`, `ethics_justice`, `ethics_composite`
- ✅ Impedance: `impedance_checklist`, `impedance`, `expected_impedance_after`, `instant_c`, `phi_ze_path_integral`
- ✅ `score_decision`

**Что MISSING в Rust:**
- ❌ `decide` — главный entry point: filter by laws → score → rank → optional override → return Scored. **Это ~95 строк Python (lines 787-877).**
- ❌ `log_decision` — SQLite ai_events INSERT + per-patient AI_LOG.md append. **~95 строк (lines 690-786).**
- ❌ `format_compact`, `format_verbose` — display rendering для CLI. **~35 строк.**
- ❌ `needs_clarification` — heuristic. **~5 строк.**
- ❌ `impedance_llm_delta` — LLM-judge edge case для L0 (использует `ask_fast`). **~40 строк, требует aim-llm Rust call.**
- ❌ `OverrideContext` struct + soft/hard override logic в decide
- ❌ Equivalent of `KernelViolation` exception (обычно `Result<T, KernelError>`)
- ❌ Per-patient AI_LOG.md markdown writer (тривиально)

**Сводка:** ~270 строк Rust осталось добавить (decide + log + format + override). Большая часть структурной работы (1069 LoC) **уже сделана**.

### 1.3 Test parity status

| Suite | Python tests | Rust tests | Что покрывается |
|---|---|---|---|
| Core laws (L0-L3, evaluate_laws) | ~30 в test_kernel.py | 34 в aim-kernel/src/lib.rs | ⚠ Не точное совпадение, проверял разные edge cases |
| Extended laws (privacy/consent/verifiability) | ~15 в test_kernel.py + test_law_gates.py | partial | ⚠ Citation guard integration — Python-only пока |
| Scoring + decide | ~20 в test_kernel_extended.py + test_kernel_scenarios.py | 0 (decide не портирован) | ❌ Полная регрессия НЕ покрыта |
| log_decision SQLite | small | 0 | ❌ |
| LLM-judge impedance | ~3 mock-based | 0 | ❌ |

**Регрессия test_kernel.py + test_kernel_extended.py + test_kernel_scenarios.py = 685 LoC, ~80 тестов.** Python kernel зелёный. После порта надо подтвердить что Rust даёт тот же output на тех же входах для всех 80 тестов.

---

## 2. Стратегические опции

| Опция | Описание | Pros | Cons | Время |
|---|---|---|---|---|
| **A. Big-bang via PyO3** | Достроить aim-kernel в Rust, экспортировать через PyO3 (maturin); `agents/kernel.py` → `from aim_kernel import *` re-export. Все callers продолжают `from agents.kernel import Decision`. | Single source of truth, native perf, backward-compat imports, abi3 wheels кросс-Python | Build infrastructure (maturin), conversion overhead Python↔Rust типов, async LLM-judge from Rust requires careful design | 5-7 дней |
| **B. Strangler** | Достроить aim-kernel. Мигрировать callers по одному: `orchestrator.py` → uses Rust kernel via PyO3 binding, потом `doctor.py`, etc. Python kernel.py остаётся как fallback. | Постепенно, low risk per step, can rollback каждого caller отдельно | Двойной maintenance, неоднозначность какая версия используется | 2-3 недели |
| **C. HTTP service** | aim-kernel поднимается как HTTP service на :8779 (sister к aim-llm на :8770). Python kernel.py становится HTTP client. Callers не меняются. | Process isolation, can be on separate machine, легко deprecate Python | Latency 5-50ms на каждый kernel.evaluate (а decide может вызывать 5+ evaluate в одном запросе) | 4-5 дней |
| **D. PyO3 only** (subset) | Часть kernel в Rust+PyO3, часть остаётся Python (`log_decision` writes Python sqlite). Hybrid. | Меньше работы, меньше риск | Долгий гибрид, сложно reason about | 3-4 дня |
| **E. Pragmatic phased** | aim-kernel остаётся Rust library. Python kernel.py остаётся как есть. Новые Rust callers используют Rust kernel. Python callers используют Python kernel. Со временем как Python callers портируются — Python kernel.py становится не нужен. | Zero risk, zero migration | Кernel evolved separately в Rust vs Python — divergence over time. Никогда не закончится без принудительного решения. | 0 (текущее состояние) |

---

## 3. Моя рекомендация: **Опция A (PyO3)** с phased rollout

### 3.1 Почему A

1. **Уже сделано 80 % работы** — 1069 LoC Rust scaffold + 34 теста + все evaluate_*. Осталось ~270 строк (decide + log + format + override).

2. **PyO3 = native binding** — `from agents.kernel import Decision` после порта будет грузить C-extension, не subprocess/HTTP. Никакого latency overhead на каждый вызов.

3. **maturin + abi3 wheel** — один wheel для всех Python 3.10+. Build infra существует у Rust сообщества.

4. **Backward compatibility** — Python `agents/kernel.py` становится 5-строчный shim:
 ```python
 from aim_kernel import (
 Decision, LawsResult, ScoringResult, Scored, OverrideContext,
 evaluate_l0, evaluate_l1, evaluate_l2, evaluate_l3, evaluate_laws,
 evaluate_l_privacy, evaluate_l_consent, evaluate_l_verifiability,
 evaluate_extended, score_decision, decide, log_decision,
 impedance, instant_c, phi_ze_path_integral, ethics_composite,
 format_compact, format_verbose, needs_clarification,
 )
 ```
 Все 7 production agents и 9 test файлов работают без изменений.

5. **Source of truth** — кernel logic в одном Rust crate. Аудит проще: читать Rust, не сравнивать Python ↔ Rust.

6. **Test parity provable** — pytest + cargo test. Те же 80 Python тестов прогоняются на Rust impl через PyO3 binding. Если все зелёные — port корректен.

### 3.2 Почему НЕ другие

- **B (strangler)** — двойной maintenance 2-3 недели. Риск divergence Python ↔ Rust kernel logic если делать долго.
- **C (HTTP)** — latency убийца для kernel'а. orchestrator.py делает 4-6 evaluate_* на запрос; HTTP добавит 30-300ms. Неприемлемо для real-time clinical decisions.
- **D (subset)** — гибрид без четкого финиша.
- **E (phased)** — никогда не закончится. Текущее состояние = по факту E (Rust scaffold ~80%, Python в проде).

### 3.3 LLM-judge impedance — решение

`impedance_llm_delta` использует `llm.ask_fast` для LLM-вердикта на L0 edge cases. В Rust нужно либо:

**Вариант (a):** Вызвать Python из Rust через PyO3 callback — Rust trait `LlmCaller` с Python-implemented adapter. Python kernel.py shim даёт `LlmCaller` instance.

**Вариант (b):** aim-kernel Rust сам вызывает `aim-llm` HTTP endpoint (которое уже существует как Rust service на :8770).

**Вариант (c):** Оставить эту функцию в Python shim, в Rust отдать только синхронные части (impedance_checklist + numerical impedance). LLM-judge остаётся Python — это edge case, ~5% запросов.

**Рекомендую (b)** — aim-kernel вызывает aim-llm HTTP. Pure Rust path, no Python callback. Latency приемлема (LLM-judge редкий случай, не на критическом пути).

### 3.4 Test parity strategy

1. **Port каждый Python test на Rust** где возможно (cargo test). 34 уже есть; нужно ещё ~50 портировать.
2. **Side-by-side validator** — pytest test файл который для каждого test case прогоняет ОБА (Python kernel + PyO3-bound Rust kernel) и assert equality output. Раньше Python authoritative; после port Rust authoritative.
3. **Property-based tests** — proptest на law gates: random Decision + Patient → check invariants (allergic patient + matching drug → L1 fails ALWAYS).
4. **Golden file tests** — fixture с известными {input, expected_output} для regression.

---

## 4. План в фазах (5-7 дней)

### Фаза 1: Достроить Rust kernel (день 1-2, ~270 строк)
- [ ] `decide` в `aim-kernel` — filter by laws → score → rank → handle override
- [ ] `OverrideContext` struct + soft/hard override logic
- [ ] `log_decision` — SQLite INSERT + AI_LOG.md write (rusqlite)
- [ ] `format_compact` / `format_verbose` — display
- [ ] `needs_clarification`
- [ ] `impedance_llm_delta` — HTTP call к aim-llm на :8770

### Фаза 2: PyO3 binding (день 3-4)
- [ ] Cargo.toml: add `pyo3 = { version = "0.23", features = ["extension-module", "abi3-py310"] }`
- [ ] `pyo3` decorators на все public structs + functions
- [ ] Type conversion: `Decision::from_py(py: &PyDict)`, `to_py(&self) -> PyObject`
- [ ] `setup.py` / `pyproject.toml` для `maturin develop` build
- [ ] Build wheel, install в venv

### Фаза 3: Replace Python kernel.py (день 4-5)
- [ ] `agents/kernel.py` → 5-строчный shim importing from `aim_kernel` C-extension
- [ ] Заменить 30 `from agents.kernel import X` ничего, потому что Python shim re-exports identical names
- [ ] Запустить полный pytest suite — все 80+ test_kernel*.py зелёные
- [ ] Запустить `agents/labs.py`, `agents/doctor.py` reality check на тестовых пациентах

### Фаза 4: Side-by-side validator + property tests (день 5-6)
- [ ] `tests/test_kernel_parity.py` — для каждого fixture (Patient, Decision) сравнить старый Python output (через git stash legacy code или archived branch) vs новый Rust-через-PyO3. Assert equality.
- [ ] `tests/test_kernel_proptest.py` — proptest на L1 invariants (allergy match → fail), L_PRIVACY (Patients/ path → block), Ethics (composite ∈ [-1, 1]).

### Фаза 5: Cleanup + deploy (день 6-7)
- [ ] Удалить Python kernel.py implementation (только shim re-export остаётся)
- [ ] Update CLAUDE.md «kernel = Rust through PyO3»
- [ ] Tag release в Cargo.toml `aim-kernel = "0.2.0"`
- [ ] systemd / production: maturin install в venv

---

## 5. Риски и митигация

| Риск | Severity | Митигация |
|---|---|---|
| Rust kernel logic ≠ Python для edge cases — пациенту дают неправильное решение | 🔴 CRIT | Side-by-side validator (Фаза 4); property-based tests; запуск на ВСЕХ 6 реальных пациентах перед merge |
| PyO3 build complexity на target deploy machines | 🟡 MED | abi3 wheel + maturin = single binary wheel; CI builds для linux x86_64 + aarch64 |
| LLM-judge HTTP latency блокирует evaluate_l0 | 🟡 MED | impedance_llm_delta — edge case (~5% calls); + cache; + fallback на checklist-only when timeout |
| log_decision SQLite locking при concurrent writes | 🟡 MED | rusqlite WAL mode + single-writer |
| Регрессия orchestrator.py (cascade through 7 callers) | 🟠 HIGH | Phase 3 запускает полный pytest suite; не deploy без зелёной регрессии |

---

## 6. Что нужно от тебя для старта

**Решения:**

1. **Опция A окей?** (PyO3 binding, single source Rust, Python shim re-exports)
2. **LLM-judge** — путь (b) HTTP call к aim-llm, как я рекомендую? Или другой?
3. **Maturin build** — окей собирать через `maturin develop` в venv? Альтернатива `setuptools-rust` тоже работает.
4. **Когда merge** — после всех 5 фаз (1 неделя) или фазами по мере готовности?
5. **Backward compat имена** — все 30 функций / классов Python публичны через shim. Окей?

**После решений начинаю Фазу 1.**

---

## 7. Обоснование "почему сейчас, не потом"

- Phase A-E + ports + cleanup закрыты вчера. Stack rule «всё новое в Rust» применён. Кernel — последний крупный Python module в operational stack который нарушает это правило.
- 1069 LoC scaffold уже есть — половина работы сделана. Откладывать = накапливать divergence Python ↔ Rust scaffold.
- 80 тестов в Python = solid validation framework. Идеальный момент для side-by-side validator.
- Без kernel в Rust — Python kernel.py остаётся вечной dependency, и Stack rule никогда не закроется.

---

**Готов делать Фазу 1 сразу после твоего ответа на 5 вопросов §6.**
