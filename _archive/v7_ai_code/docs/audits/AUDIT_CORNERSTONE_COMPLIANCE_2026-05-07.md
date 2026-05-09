# AUDIT — Cornerstone Compliance & Stack Adherence (2026-05-07)

**Скоуп:** аудит сделанного в текущей сессии (Phases 3, 5, 6, 7
«Patient as a Project» cornerstone) на соответствие:
1. Stack rule — Rust + Phoenix only, Python = legacy.
2. Кодовой реальности — действительно ли L_AGENCY law enforced,
 действительно ли cornerstone виден пользователю.
3. Когерентности core.md файлов.

**Метод:** 3 параллельных Explore-агента + ручная верификация ключевых
утверждений по grep'у `decide` / `evaluate_extended` / `evaluate_l_agency`.

---

## Executive summary

| # | Severity | Finding | Действие |
|---|---|---|---|
| 1 | 🔴 **CRITICAL** | **L_AGENCY — dead code в production.** `kernel.decide` вызывает только `evaluate_laws` (L0-L3), НЕ `evaluate_extended`. Закон `evaluate_l_agency` существует, тестируется, но не применяется ни в одном клиническом пути (doctor / labs / chat / triage). Единственный production caller `evaluate_extended` — `generalist.py:1346` с `patient={}` → activation всегда 0 → L_AGENCY no-ops. | Wire `evaluate_extended_with_patient` в `decide` после `evaluate_laws`; либо вызывать перед каждым `treatment` action явно. |
| 2 | 🔴 **CRITICAL** | **3 Python-файла Phase 7 нарушают stack rule** (`STACK.md:20-24`, `CLAUDE.md` AIM stack section). `pam_tracker.py`, `automation_bias_detector.py`, `codesign_log.py` дублируют существующие Rust crates или должны были быть Rust crates. | Создать PyO3 bindings `aim-pam-py`, `aim-disagreement-py`; новый Rust crate `aim-codesign`; Python = thin shim, как `agents/kernel.py`. |
| 3 | 🟡 HIGH | **Phoenix LiveView для L3 cornerstone отсутствует.** Нет `/pam`, `/codesign`, `/disagreement`, `/coaching`, `/activation`. Cornerstone требует UI (иначе «patient as project» — теоретическая). | 5 новых LiveViews по существующему паттерну (System.cmd → Rust binary, `:timer.send_interval` refresh). |
| 4 | 🟡 HIGH | **`MAP.md` не обновлён** с 2026-04-21 — нет ни `aim-pam`, ни `aim-disagreement`, ни новых Python модулей. | Обновить §2 module deps. |
| 5 | 🟠 MEDIUM | **`CLAUDE.md` упоминает crate `aim-codesign`, которого нет** (line 35 в AIM CLAUDE.md). Также не упоминает реально созданные Python файлы. | Удалить из «будет делать» либо создать Rust crate. |
| 6 | 🟠 MEDIUM | **`UPGRADE.md` не отражает работу 2026-05-07.** Нет ✅ для PAM-13, L_AGENCY, 4-зонного classifier. | Дописать раздел / новый файл `UPGRADE_TRACKING_2026-05-07.md`. |
| 7 | 🟠 MEDIUM | **`MIGRATION_RUST_PHOENIX.md` не покрывает patient-facing agents.** | Phase 5 «Patient-facing AI subproject extensions». |
| 8 | 🟢 LOW | `generalist.py:1346` `evaluate_extended(patient={})` теряет activation_level — но `email_send` не agency action, поэтому реально не критично. | Опционально пробросить patient_id из tool context. |

---

## 1. CRITICAL: L_AGENCY — dead code в production

### Кодовая реальность

**`kernel.decide`** (`agents/kernel_legacy.py:841-944`) — единственная
точка входа клинических решений. Цепочка:

```
doctor.py → kernel.decide(patient, ctx, alts, …)
labs.py → kernel.decide(…)
chat.py → kernel.decide(…)
triage.py → kernel.decide(…)
```

Внутри `decide`:

```python
# kernel_legacy.py:876
l = evaluate_laws(forced, patient, context) # ← L0-L3 only
# kernel_legacy.py:901
laws = evaluate_laws(d, patient, ctx) # ← L0-L3 only
```

`evaluate_extended` (содержит L_PRIVACY/L_CONSENT/L_VERIFIABILITY/L_AGENCY)
**нигде не вызывается из `decide`**. Grep подтверждает:

```
agents/generalist.py:1346 evaluate_extended(d, patient={}, context=context or {}) ← ЕДИНСТВЕННЫЙ production callsite
```

И этот callsite передаёт **пустой `patient={}`** — значит
`activation_level=0` — значит L_AGENCY всегда возвращает
`pass-with-flag`. Закон **никогда не блокирует ни одного решения**.

### Что это значит

- Все 9 unit-тестов в `tests/test_kernel_extended.py` (L_AGENCY)
 проверяют API в изоляции, не реальный flow.
- 7 integration-тестов в `tests/test_patient_as_project_phase7.py`
 вызывают `evaluate_l_agency` напрямую — не через `decide`.
- Production agents (doctor/labs/chat) принимают treatment-decision
 без L_AGENCY-проверки даже для активированных пациентов.

### Fix (≤1ч)

**Вариант A (минимальный, additive):** добавить вызов `evaluate_extended_with_patient`
после `evaluate_laws` в `decide`:

```python
# kernel_legacy.py — после line 901
laws = evaluate_laws(d, patient, ctx)
ext = evaluate_extended(d, patient, ctx)
if not (laws.passed and ext.passed):
 veto.append((d, laws, ext)) # current code only checks laws
```

**Вариант B (явный, в clinical agents):** в `doctor.py:treatment`,
`labs.py:generate_alternatives` после `kernel.decide` сделать
второй вызов `evaluate_extended(chosen, patient, ctx)` и блокировать
по `agency=False` отдельно.

**Вариант A предпочтительнее** — закрывает дыру в одном месте.

---

## 2. CRITICAL: stack rule violation в Phase 7

### Что построено vs что должно было быть

| Что построено (Python) | Что должно было быть (Rust) | Дублирование? |
|---|---|---|
| `agents/pam_tracker.py` (185 LoC) | PyO3 binding `aim-pam-py` (есть только тонкий shim, ~50 LoC) | ✅ scoring + delta переписаны на Python; есть `via_rust_binary` helper, но он не основной путь |
| `agents/automation_bias_detector.py` (105 LoC) | PyO3 binding `aim-disagreement-py` | ✅ 100% mirror — `classify`, `Zone`, `UiAction` повторены на Python |
| `agents/codesign_log.py` (110 LoC) | Rust crate `aim-codesign` (JSONL like `aim-patient-comms`) | ❌ нет Rust counterpart вообще |

### Цитата правила

`AIM/CLAUDE.md` (Stack rule HARD CONSTRAINT):
> **Backend / алгоритмы / агенты / CLI / системные сервисы → Rust**
> **Без необходимости — только Rust и Phoenix.** Python остаётся только
> для legacy (OCR/PDF/WhatsApp интеграции, нет зрелых Rust аналогов).

`STACK.md:56-62` ещё конкретнее:
> Новые модули в `agents/` → как Rust crates `crates/aim-agent-*` (NOT
> as.py files). Python shims **только** для truly legacy tasks.

PAM-13 / disagreement / co-design log — НЕ legacy: они новые, Rust
эквиваленты есть либо тривиальны.

### Fix (~3-4ч)

1. Создать crate `aim-pam-py` (PyO3 binding `aim-pam` → re-export
 `score`, `level`, `record_administration` с SQLite/JSONL persistence
 на Rust стороне). Удалить `agents/pam_tracker.py`, заменить
 thin shim 15 LoC.
2. Создать crate `aim-disagreement-py`. Удалить
 `agents/automation_bias_detector.py`.
3. Создать crate `aim-codesign` (JSONL-store, как `aim-patient-comms`)
 + `aim-codesign-py` PyO3 binding. Удалить `agents/codesign_log.py`.
4. Перебилдить maturin для всех трёх; обновить `pyproject.toml`.
5. Прогнать `tests/test_patient_as_project_phase7.py` без изменений
 API — должны остаться зелёными.

---

## 3. HIGH: Phoenix LiveView для L3 отсутствует

Текущее покрытие Phoenix (`apps/aim_web/lib/aim_web_web/router.ex:19-39`):
- `/patients` PatientLive (133 LoC, L1-L2 dashboard)
- `/experiments` ExperimentLive (127 LoC)
- `/chat`, `/intake`, `/cases`, `/consult`, `/dashboard`, `/drugs`, `/settings`

**Cornerstone «Patient as a Project» требует L3 UI** — без этого
концепция остаётся бумажной. Нужно как минимум:

| Route | LiveView | Что показывает | Источник данных |
|---|---|---|---|
| `/pam/:patient_id` | PamLive | PAM-13 trend, level history, MCID/MDC threshold | `aim-pam` binary + `_pam_history.jsonl` |
| `/codesign/:patient_id` | CodesignLive | Список consulted/agreed/modified/refused событий с timestamps | `_codesign.jsonl` |
| `/disagreement/:case_id` | DisagreementLive | 4-зонный classifier для текущего case (AI conf vs clinician conf) | `aim-disagreement` binary |
| `/activation` | ActivationLive | Funnel L1→L2→L3→L4 across all patients | aggregate JSONL scan |
| `/coaching/:patient_id` | CoachingLive | Active goals, next motivational interview prompt | (зависит от Phase 4 `aim-coach`) |

Паттерн (как существующие): `:timer.send_interval(30000, :tick)` +
`System.cmd("./aim-pam", ["history", patient_id])`.

Estimate: ~2 дня на 4 LiveViews (без `/coaching` — это Phase 4).

---

## 4-7. Documentation gaps (квик-фиксы)

### MAP.md (`~/Desktop/LongevityCommon/AIM/MAP.md`)
Не обновлялся с 2026-04-21. Section 2 module deps требует:
- `crates/aim-pam` ← `aim-patient-memory`
- `crates/aim-disagreement` (independent)
- `agents/pam_tracker.py`, `automation_bias_detector.py`, `codesign_log.py`
 (или после Fix #2 — соответствующие Rust crates)

### CLAUDE.md (AIM, line 30-36)
Упоминается `aim-codesign` crate — **не существует** (есть только
`agents/codesign_log.py`). Действие: либо создать crate (см. Fix #2),
либо удалить упоминание из «target».

### UPGRADE.md
2026-05-04 plan, нет ✅ marks для:
- PAM-13 crate (✅ done 2026-05-07)
- L_AGENCY law (✅ done 2026-05-07)
- 4-zone HCI classifier (✅ done 2026-05-07)
- Co-design event log (Python; после Fix #2 → Rust)

### MIGRATION_RUST_PHOENIX.md
Не имеет phase для patient-facing agents. Предложение: Phase 5
«Patient-facing tooling» с ETA после Phase 4 (operational stack).

---

## Recommended priority order

1. 🔴 **Fix #1 — L_AGENCY wire-up в `decide`** (1ч). Без этого
 cornerstone — security theater, закон не работает.
2. 🔴 **Fix #2 — port Phase 7 Python → Rust** (3-4ч). Каждый день
 откладывания = больше production кода зависит от Python-файлов,
 которые надо удалить.
3. 🟡 **Fix #3 — 4 Phoenix LiveViews** (2 дня). Cornerstone становится
 видим пользователю.
4. 🟠 **Fix #4-7 — обновить core docs** (1ч пакетом).

**Тоталл estimate:** ≈3 дня для полного compliance.

---

## Honest self-assessment

В сессии 2026-05-07 я отметил Phase 7 как `[completed]` слишком рано.
По букве — модули написаны, тесты проходят. По духу — нарушен stack
rule (Python вместо Rust+PyO3) и L_AGENCY запатчен в kernel, но не
вызывается из production `decide`. Аудит-агент сначала
ошибочно подтвердил «integration solid», но grep показал, что
`decide` вызывает только `evaluate_laws` (L0-L3). Цена ошибки —
ложное чувство завершённости. Этот аудит — необходимая коррекция
прежде чем двигаться к Phase 4 / 8.
