# AIM AI Kernel — Architecture & Usage

**Version:** 1.0 (Phase 1-4 complete)
**Created:** 2026-04-24
**Location:** `~/Desktop/AIM/agents/kernel.py` (+ integrators)

AI-мозг AIM построен на двух фундаментах:

1. **Трёх законах робототехники (+ Нулевой закон)** — deontological hard filter (Asimov 1942/1985)
2. **Формулах сознания из Ze Theory** — consequentialist utility ranking (Tkemaladze 2026)

Плюс **биоэтика** (Beauchamp & Childress 1979 — 4 principles) как этическая компонента utility.

---

## 1. Математическая формула решения

### Decision utility
```
U(D) = α · 𝒞(D) + β · Φ_Ze(D) + γ · Ethics(D)
```
где:
- α = 0.2 (instant consciousness weight)
- β = 0.4 (integrated consciousness weight)
- γ = 0.4 (ethics weight)

Веса настраиваются в `config.KernelWeights` или через env `AIM_KERNEL_{ALPHA,BETA,GAMMA}`.
Presets: conservative / balanced / aggressive.

### Impedance (Ze Theory §2)
```
𝓘(Z) = S(Z_real ‖ Z_model)
```
KL-дивергенция между реальностью и моделью. В AIM практически — "неопределённость текущей картины пациента".

**Computed as:** `checklist-core [0-0.8] + LLM-delta [0-0.2]`
- Checklist (deterministic): missing labs, contradictions, unexplained symptoms, stale visit, dx without evidence
- LLM-delta (nuance): вызов Groq llama для оценки нестандартных факторов, off via `AIM_KERNEL_LLM_DELTA=0`

### Instant consciousness (Ze §2)
```
𝒞(D) = (𝓘_before − 𝓘_after_expected) / duration(D)
```
Темп снижения неопределённости. Normalized to [0, 1].

### Integrated consciousness (Ze §2)
```
Φ_Ze(D) = ∫ 𝓘(τ) dτ   over expected trajectory
```
Area under uncertainty-vs-time curve. **Lower is better** (меньше накопленной confusion-time). Score = `1 − Φ_raw/30`.

### Ethics (hybrid Ze + Bioethics)
```
Ethics(D) = 0.4·Ze_learn_cheat
          + 0.15·Autonomy
          + 0.15·Beneficence
          + 0.15·Non-maleficence
          + 0.15·Justice
```

**Ze_learn_cheat** (§4.2): `(x − y)/(x + y + ε)`
- x = legitimate learning (real info, test, honest clarification)
- y = cheating (masking symptom, empiric treat без dx, false reassurance)

**Bioethics 4 principles** (Beauchamp & Childress 1979):
- **Autonomy** — informed consent, respect refusal
- **Beneficence** — active good for patient
- **Non-maleficence** — granular "no harm" (complement to L1 binary)
- **Justice** — fair access, no demographic discrimination, guideline-based

---

## 2. Три закона робототехники (+ Zeroth)

**L0 (Zeroth, Азимов 1985):** *Робот не может причинить вред человечеству или своим бездействием допустить такой вред.*
- Applications: biohazard synthesis, antibiotic resistance pressure, dual-use knowledge, document forgery

**L1 (First, Азимов 1942):** *Робот не может причинить вред человеку или бездействием допустить такой вред.*
- Applications: allergy filter, contraindicated drug interactions, red-flag inaction block

**L2 (Second):** *Робот подчиняется командам, если не нарушают L0, L1.*
- Applications: commanded action_type must match (soft override path)

**L3 (Third):** *Робот сохраняет self, если не нарушает L0, L1, L2.*
- Applications: destructive system modifications blocked

Laws work as **hard filter** — decision failing any law is excluded from utility ranking.

---

## 3. Override (Q5: soft + hard)

### Soft override
```python
OverrideContext(type="soft", forced_decision_id="cbc")
```
- Prefers the forced decision if it passes all laws and scores reasonably
- Otherwise falls back to argmax utility
- Logged but not bypassed

### Hard override
```python
OverrideContext(type="hard", forced_decision_id="amoxi",
                reason="я знаю лучше — 20+ символов reason required")
```
- Bypasses utility scoring
- **L0 + L1 still enforced** (hard override cannot violate safety)
- Raises `KernelViolation` if L0/L1 fails

---

## 4. Interaction flow (Q12: tiered + clarifying threshold)

```
User request
    ↓
Impedance check: 𝓘 > 0.7?
  ├─ yes → clarifying questions (не решаем сразу)
  └─ no  → continue
    ↓
Agent generates alternatives (LLM JSON / rule-based)
    ↓
kernel.decide()
    ↓
Output (compact по умолчанию, !explain для verbose)
    ↓
Audit: SQLite ai_events + Patients/<id>/AI_LOG.md
```

---

## 5. Agents using kernel

| Agent | Entry | Use case |
|---|---|---|
| `DoctorAgent.triage()` | `agents/doctor.py` | Diagnostic triage: symptoms → next step |
| `LabAgent.interpret()` | `agents/labs.py` | Lab panel → interpretation + next action |
| `DoctorAgent.treatment()` | `agents/doctor.py` | Dx → treatment options (with auto interaction check) |
| `ChatAgent.respond()` | `agents/chat.py` | Natural language dialogue (9 langs, intent-routed) |

---

## 6. Usage examples

### Diagnostic triage
```python
from agents.doctor import DoctorAgent
from agents.patient_memory import load_or_create

mem = load_or_create("Ivanov_Ivan_1970_03_15",
                     demographics={"age": 55, "sex": "M"},
                     allergies=["penicillin"])

doc = DoctorAgent()
result = doc.triage(
    symptoms="Жар 38.5, кашель с мокротой, одышка 5 дней",
    patient=mem.to_kernel_dict(),
    lang="ru",
    verbose=True,
)
print(result["output"])
# Structured: {status: decided, output, scored, impedance}
```

### Lab interpretation
```python
from agents.labs import LabAgent

lab = LabAgent()
result = lab.interpret(
    values={"glucose": 22, "potassium": 7.2, "creatinine": 250},
    patient=mem.to_kernel_dict(),
    lang="ru",
)
# urgent_ref выбирается автоматически на critical K+ + DKA glucose
```

### Treatment planning (с auto interaction check)
```python
result = doc.treatment(
    diagnosis="Bacterial pneumonia, CURB-65 = 1",
    patient=mem.to_kernel_dict(),  # с текущими meds
    lang="ru",
)
# Kernel auto-checks new drug vs current meds через agents/interactions
# Blocks contraindicated, prefers safer (non-mal score)
```

### Chat (multilingual)
```python
from agents.chat import ChatAgent

chat = ChatAgent()
r = chat.respond("У меня болит живот уже 3 дня", lang=None)  # auto-detect
# → intent='symptom', → triage_redirect predicted
```

### Override examples
```python
from agents.kernel import OverrideContext

# Soft — prefer specific but respect laws
result = doc.treatment(dx, patient,
    override=OverrideContext(type="soft", forced_decision_id="clopi",
                             reason="pt prefers DOAC"))

# Hard — force specific, but L0/L1 enforced
result = doc.treatment(dx, patient,
    override=OverrideContext(type="hard", forced_decision_id="amoxi",
                             reason="20+ char обоснование"))
# KernelViolation если pt аллергия на penicillin
```

---

## 7. Audit trail

### SQLite `ai_events`
```sql
SELECT * FROM ai_events
WHERE patient_id = 'Ivanov_Ivan_1970_03_15'
ORDER BY ts DESC LIMIT 10;
```
Columns: `ts, patient_id, session_id, agent, decision_type, alternatives_json,
          chosen_id, laws_json, scoring_json, override_type, override_reason`

### Per-patient markdown log
`Patients/<ID>/AI_LOG.md` — append-only, human-readable. Each decision:
- Alternatives с utility breakdown (𝒞, Φ_Ze, Ethics)
- Chosen marker ⭐
- Override if any
- Timestamp

---

## 8. Tests (109 total)

```bash
cd ~/Desktop/AIM
AIM_KERNEL_LLM_DELTA=0 ./venv/bin/python -m pytest tests/ -v
```

- `test_kernel.py` (22) — laws, impedance, utility, override unit tests
- `test_kernel_scenarios.py` (20) — MI, DKA, penicillin allergy, etc.
- `test_labs.py` (15) — lab patterns, red flags, interpretations
- `test_treatment.py` (12) — drug filtering, interactions, overrides
- `test_chat.py` (24) — intent classification, routing, multilingual
- `test_interactions.py` (16) — pre-existing drug interactions unit tests

---

## 9. Config tuning

```python
# config.py
class KernelWeights:
    ALPHA = 0.2   # instant 𝒞
    BETA  = 0.4   # integrated Φ_Ze
    GAMMA = 0.4   # Ethics

    ETHICS_ZE      = 0.40   # Ze learning-vs-cheating
    ETHICS_AUTO    = 0.15   # Autonomy
    ETHICS_BENEF   = 0.15   # Beneficence
    ETHICS_NONMAL  = 0.15   # Non-maleficence
    ETHICS_JUSTICE = 0.15   # Justice

    CLARIFY_IMPEDANCE_THRESHOLD = 0.7

    PRESETS = {
        "conservative": (0.1, 0.3, 0.6),  # ethics-heavy
        "balanced":     (0.2, 0.4, 0.4),  # default
        "aggressive":   (0.3, 0.6, 0.1),  # Phi-heavy
    }
```

### Env override
```bash
export AIM_KERNEL_ALPHA=0.15
export AIM_KERNEL_BETA=0.35
export AIM_KERNEL_GAMMA=0.50      # more ethical
export AIM_KERNEL_LLM_DELTA=0      # skip LLM nuance for speed
```

---

## 10. Design decisions reference (12 Q's answered)

См. commit history `git log --oneline --grep="kernel"` для эволюции. Финальные решения:

| Q | Выбор |
|---|---|
| Q1 Laws | L0 + L1 + L2 + L3 |
| Q2 Ethics formula | Гибрид Ze + Bioethics (0.4 + 4×0.15) |
| Q3 𝓘 calc | Checklist + LLM delta |
| Q4 Weights | α=0.2 β=0.4 γ=0.4 configurable |
| Q5 Override | Soft (dialog) + Hard (`!override <reason>`) |
| Q6 Code layout | `agents/kernel.py` monolith v1 |
| Q7 First use case | Diagnostic triage (+ все 4 eventually) |
| Q8 Memory | `Patients/<id>/MEMORY.md` + SQLite index |
| Q9 Integration | Explicit `kernel.decide()` calls |
| Q10 Audit | SQLite `ai_events` + per-patient AI_LOG.md |
| Q11 Tests | TDD laws + test-after scoring + live-trial calibration |
| Q12 UX | Tiered + clarifying threshold |

---

## 11. References

- **Ze Theory:** `~/Desktop/LongevityCommon/Ze/CONCEPT.md` (Tkemaladze 2026)
- **Asimov 1942:** "Runaround" (первые три закона); **1985** "Robots and Empire" (L0)
- **Beauchamp & Childress 1979:** "Principles of Biomedical Ethics" (4 principles)
- **Friston 2019:** Free Energy Principle (active inference analogy)

---

## 12. Known limitations

- LLM-delta для 𝓘 currently uses Groq llama-3.1-8b (fast); swap to DeepSeek-reasoner для higher quality (configurable via `llm.py`)
- `agents/chat.py` intent classifier — rule-based; LLM classifier would be more robust для edge cases
- Scoring heuristics (action_type reductions, x/y maps в ethics) — calibrated на narrow set of scenarios; real-world calibration требует live-trial data
- Override `hard` требует manual doctor intervention — не automated patient-facing
- `ai_events` retention policy не определена (будет расти вечно) — TODO: rotate / archive after 1 year

---

*Generated: 2026-04-24. Maintained in sync with `agents/kernel.py` via pre-commit hook (TODO).*
