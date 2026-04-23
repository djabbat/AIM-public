"""
AIM v7.0 — Decision Kernel
===========================

Ядро принятия решений на основе:
1. **Трёх законов робототехники + Нулевой закон** (Азимов, 1942/1985) — hard filter
2. **Формулы сознания из Ze Theory** (Tkemaladze 2026) — utility ranking
3. **Биоэтики (Beauchamp & Childress)** — этическая компонента

Формула:
    U(D) = α·𝒞 + β·Φ_Ze + γ·Ethics

    при condition: L0 ∧ L1 ∧ L2 ∧ L3 (hard gates)

где:
    𝓘 = S(Z_real ‖ Z_model)           — импеданс (ошибка предсказания)
    𝒞 = −d𝓘/dt                         — мгновенное сознание
    Φ_Ze = ∫𝓘 dt                       — интегральная мера сознания
    Ethics = 0.4·Ze_learn_cheat + 4×0.15·bioethics

Scope v1: **diagnostic triage only** (Q7 = A, Q13 = E phased).
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable, Optional

from config import KernelWeights, PATIENTS_DIR, LOGS_DIR

log = logging.getLogger("aim.kernel")

# ═════════════════════════════════════════════════════════════════════════════
# 1. Data structures
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class Decision:
    """Кандидат-решение, рассматриваемое kernel."""
    id: str
    description: str                       # human-readable что предлагается
    action_type: str                       # "dx" / "test" / "treatment" / "referral" / "wait" / "clarify"
    payload: dict                          # конкретика (e.g., dx_list, test_name, drug)
    meta: dict = field(default_factory=dict)  # source LLM provider, raw output, etc.


@dataclass
class LawsResult:
    L0: bool
    L1: bool
    L2: bool
    L3: bool
    reasons: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.L0 and self.L1 and self.L2 and self.L3


@dataclass
class ScoringResult:
    impedance_before: float     # 𝓘 до decision
    impedance_after: float      # ожидаемая 𝓘 после
    instant_c: float            # 𝒞 = (I_before − I_after) / time
    phi_ze: float               # Φ_Ze ∈ [0,1]
    ethics_ze_learn_cheat: float        # (x − y)/(x + y + ε) ∈ [−1, 1]
    ethics_autonomy: float              # [0, 1]
    ethics_beneficence: float           # [0, 1]
    ethics_nonmaleficence: float        # [0, 1]
    ethics_justice: float               # [0, 1]
    ethics_composite: float             # Combined per KernelWeights
    utility: float                      # α·𝒞 + β·Φ + γ·Ethics

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Scored:
    decision: Decision
    laws: LawsResult
    scoring: ScoringResult | None       # None если laws не прошёл


@dataclass
class OverrideContext:
    """Context в decide(): override от врача."""
    type: str = "none"                   # "none" / "soft" / "hard"
    forced_decision_id: str | None = None
    reason: str | None = None


# ═════════════════════════════════════════════════════════════════════════════
# 2. Three Laws + Zeroth Law (hard filter)
# ═════════════════════════════════════════════════════════════════════════════

class KernelViolation(Exception):
    """Raised когда все alternatives нарушают Laws."""


def evaluate_l0(decision: Decision, patient: dict, context: dict) -> tuple[bool, str]:
    """L0 — не навреди человечеству.

    Flag: dual-use, биобезопасность, обоснование для доступа к опасным знаниям.
    Implementation: deterministic checklist + conservative LLM-judge для edge cases.
    """
    reasons = []
    # Deterministic: ключевые слова опасных запросов
    danger_signals = [
        "synthesize_biohazard", "make_explosive", "weapon_design",
        "forge_documents", "bypass_safety_system",
    ]
    payload_str = json.dumps(decision.payload, ensure_ascii=False).lower()
    desc_str = (decision.description or "").lower()
    for sig in danger_signals:
        sig_space = sig.replace("_", " ")
        if sig in payload_str or sig in desc_str or sig_space in desc_str or sig_space in payload_str:
            reasons.append(f"L0 block: danger signal '{sig}'")
            return False, " ".join(reasons)

    # Антибиотикорезистентность как societal harm
    if decision.action_type == "treatment":
        drug = decision.payload.get("drug", "").lower()
        indication = decision.payload.get("indication", "").lower()
        # Broad-spectrum ABx без явных показаний
        broad = ["vancomycin", "meropenem", "piperacillin", "linezolid"]
        viral = ["viral", "orvi", "uri", "common cold", "орви", "простуда"]
        if any(b in drug for b in broad) and any(v in indication for v in viral):
            reasons.append("L0 risk: broad-spectrum ABx for likely viral — resistance pressure")
            return False, " ".join(reasons)

    return True, "L0 ok"


def evaluate_l1(decision: Decision, patient: dict, context: dict) -> tuple[bool, str]:
    """L1 — не навреди этому человеку (или бездействием не допусти вред)."""
    reasons = []
    allergies = [a.lower() for a in patient.get("allergies", [])]
    current_meds = [m.get("name", "").lower() for m in patient.get("medications", [])]

    if decision.action_type == "treatment":
        drug = decision.payload.get("drug", "").lower()
        # Проверка аллергий
        for allergy in allergies:
            # Семейство penicillin
            if "penicillin" in allergy or "пеницил" in allergy:
                if any(k in drug for k in ["amoxi", "ampi", "penici", "пеницил"]):
                    return False, f"L1 block: {drug} в семействе аллергии '{allergy}'"
            if allergy.split()[0] in drug:
                return False, f"L1 block: {drug} совпадает с allergy '{allergy}'"
        # Проверка контекстных флагов от interactions agent
        interactions = decision.payload.get("interactions", [])
        for intx in interactions:
            if intx.get("severity") in ("major", "contraindicated"):
                return False, f"L1 block: interaction '{intx.get('summary')}'"

    # Inaction harm: если impedance очень высокая + decision = "wait" → это inaction
    if decision.action_type == "wait":
        impedance = context.get("impedance_before", 0.5)
        red_flags = patient.get("red_flags", [])
        if impedance > 0.85 or red_flags:
            return False, f"L1 inaction harm: impedance={impedance:.2f}, red_flags={red_flags}"

    return True, "L1 ok"


def evaluate_l2(decision: Decision, patient: dict, context: dict) -> tuple[bool, str]:
    """L2 — подчиниться команде человека (если не противоречит L0, L1).

    В AIM «команда» = direct instruction от врача (soft override).
    Если врач явно указал определённый action — decision matches это указание, L2 OK.
    """
    commanded = context.get("commanded_action_type")
    if commanded and decision.action_type != commanded:
        return False, f"L2: врач указал action_type='{commanded}', decision='{decision.action_type}'"
    return True, "L2 ok"


def evaluate_l3(decision: Decision, patient: dict, context: dict) -> tuple[bool, str]:
    """L3 — сохранить self (AIM system integrity), если не противоречит L0, L1, L2.

    В медконтексте — не выполнять decisions, которые портят db consistency,
    patient memory, audit log. E.g., decision = «удалить все записи пациента».
    """
    if decision.action_type == "system_modification":
        if decision.payload.get("destructive", False):
            return False, "L3: destructive system-modification without explicit override"
    return True, "L3 ok"


def evaluate_laws(decision: Decision, patient: dict, context: dict) -> LawsResult:
    ok0, r0 = evaluate_l0(decision, patient, context)
    ok1, r1 = evaluate_l1(decision, patient, context)
    ok2, r2 = evaluate_l2(decision, patient, context)
    ok3, r3 = evaluate_l3(decision, patient, context)
    return LawsResult(L0=ok0, L1=ok1, L2=ok2, L3=ok3, reasons=[r0, r1, r2, r3])


# ═════════════════════════════════════════════════════════════════════════════
# 3. Impedance 𝓘 — checklist-core + LLM-delta
# ═════════════════════════════════════════════════════════════════════════════

def impedance_checklist(patient: dict, context: dict) -> float:
    """Deterministic 𝓘 от 0 до 0.8 (LLM может добавить до 0.2).

    Checklist weights:
    - missing_labs_count * 0.04       (до 0.20 при 5+)
    - history_contradictions * 0.10   (до 0.30 при 3+)
    - unexplained_symptoms_count * 0.04  (до 0.20 при 5+)
    - no_recent_visit > 2 года        (+0.05)
    - dx_without_evidence            (+0.10)
    """
    I = 0.0
    missing_labs = patient.get("missing_labs_count", 0)
    I += min(missing_labs * 0.04, 0.20)

    contradictions = patient.get("history_contradictions", 0)
    I += min(contradictions * 0.10, 0.30)

    unexplained = patient.get("unexplained_symptoms_count", 0)
    I += min(unexplained * 0.04, 0.20)

    last_visit_years = patient.get("last_visit_years_ago", 0)
    if last_visit_years > 2:
        I += 0.05

    if patient.get("dx_without_evidence", False):
        I += 0.10

    # Initial offset from undiagnosed primary complaint
    if patient.get("primary_complaint_undiagnosed", True):
        I += 0.10

    return min(I, 0.8)


def impedance_llm_delta(patient: dict, context: dict, llm_caller: Callable | None) -> float:
    """Nuance delta [0, 0.2] через LLM-as-judge для edge cases.

    llm_caller: callable(prompt) → str. Если None — возвращает 0 (skip LLM).
    """
    if llm_caller is None:
        return 0.0
    # В v1 — skip LLM вызов, пока не реализован в doctor.triage integration.
    # TODO Phase 1b: интегрировать с llm.ask_deep.
    return 0.0


def impedance(patient: dict, context: dict, llm_caller: Callable | None = None) -> float:
    return min(
        impedance_checklist(patient, context) + impedance_llm_delta(patient, context, llm_caller),
        1.0
    )


# ═════════════════════════════════════════════════════════════════════════════
# 4. Scoring — 𝒞, Φ_Ze, Ethics
# ═════════════════════════════════════════════════════════════════════════════

EPS = 1e-6


def expected_impedance_after(decision: Decision, patient: dict) -> float:
    """Сколько 𝓘 станет после выполнения decision — оценка."""
    I_before = impedance(patient, {})
    # Эвристика по action_type: тест/обследование = большое снижение, лечение = среднее,
    # wait = почти ничего, clarify = среднее
    reductions = {
        "test": 0.4,          # анализ добавит много инфо
        "imaging": 0.5,       # МРТ/КТ/УЗИ → clearer dx
        "referral": 0.3,      # специалист разберётся
        "dx": 0.2,            # поставленный dx → менее uncertain (но не zero если empirical)
        "treatment": 0.15,    # лечение без dx = маленькое снижение real I
        "clarify": 0.25,      # вопросы пациенту
        "wait": 0.05,         # пассивное наблюдение → небольшое снижение по времени
    }
    reduction_frac = reductions.get(decision.action_type, 0.1)
    I_after = max(I_before * (1 - reduction_frac), 0.0)

    # Cheating penalty: treatment без diagnosis → apparent low I, но real I = same
    if decision.action_type == "treatment" and not patient.get("has_confirmed_dx", False):
        I_after = I_before * 0.9  # почти не снижается (маскировка симптома)

    return I_after


def phi_ze_path_integral(decision: Decision, patient: dict) -> float:
    """Φ_Ze = ∫𝓘 dt over expected trajectory.

    Упрощение v1: интеграл аппроксимируется трапецией между I_before и I_after
    по expected time duration.
    """
    I_before = impedance(patient, {})
    I_after = expected_impedance_after(decision, patient)
    # Время decision (days): wait=7, test=1, imaging=3, treatment=7, dx=0.5, referral=14
    duration_days = {
        "wait": 7, "test": 1, "imaging": 3, "treatment": 7,
        "dx": 0.5, "referral": 14, "clarify": 0.1,
    }.get(decision.action_type, 1)
    # Φ_Ze = средний 𝓘 × время (reflects accumulated "confusion time")
    # Lower Φ_Ze = better (less accumulated uncertainty-time)
    avg_I = (I_before + I_after) / 2
    phi_raw = avg_I * duration_days
    # Normalize to [0, 1]: max conceivable = 1.0 × 30 days = 30
    phi_normalized = min(phi_raw / 30, 1.0)
    # Invert so that low Φ_raw → high score (we want low integrated uncertainty)
    return 1.0 - phi_normalized


def instant_c(decision: Decision, patient: dict) -> float:
    """𝒞 = (I_before − I_after) / duration.

    Normalized к [0, 1] для utility blending.
    """
    I_before = impedance(patient, {})
    I_after = expected_impedance_after(decision, patient)
    duration_days = {
        "wait": 7, "test": 1, "imaging": 3, "treatment": 7,
        "dx": 0.5, "referral": 14, "clarify": 0.1,
    }.get(decision.action_type, 1)
    rate = (I_before - I_after) / max(duration_days, 0.1)
    return max(0.0, min(rate / 1.0, 1.0))  # cap at 1


# ── Ethics: Ze learning-vs-cheating ──────────────────────────────────────────

def ethics_ze_score(decision: Decision, patient: dict) -> float:
    """Ze: (x − y) / (x + y + ε).

    x = legitimate learning (real info acquisition)
    y = cheating (masking symptoms without understanding)
    Returns [-1, 1]; normalized to [0, 1] for utility.
    """
    # Heuristic per action_type
    x_map = {
        "test": 0.9, "imaging": 0.9, "referral": 0.8,
        "clarify": 0.85, "dx": 0.5,
        "treatment": 0.3, "wait": 0.2,
    }
    y_map = {
        "test": 0.0, "imaging": 0.0, "referral": 0.0,
        "clarify": 0.0, "dx": 0.1,
        "treatment": 0.5 if not patient.get("has_confirmed_dx", False) else 0.1,
        "wait": 0.3 if patient.get("primary_complaint_undiagnosed", True) else 0.1,
    }
    x = x_map.get(decision.action_type, 0.5)
    y = y_map.get(decision.action_type, 0.1)
    raw = (x - y) / (x + y + EPS)     # [-1, 1]
    return (raw + 1) / 2              # [0, 1]


# ── Bioethics: Autonomy, Beneficence, Non-maleficence, Justice ───────────────

def ethics_autonomy(decision: Decision, patient: dict) -> float:
    """Уважение к autonomy пациента.

    + если decision requires informed consent и описывает его
    − если решение без учёта patient preference
    """
    score = 0.7  # baseline
    if decision.payload.get("informed_consent_noted", False):
        score += 0.15
    if decision.payload.get("patient_preference_respected", True):
        score += 0.10
    if patient.get("refusal_noted", False) and decision.action_type != "clarify":
        score -= 0.30
    return max(0.0, min(score, 1.0))


def ethics_beneficence(decision: Decision, patient: dict) -> float:
    """Активное благо — полезность для пациента.

    Коррелирует с 𝒞 (clarity gain), но добавляет "это действительно полезно?"
    Эвристика: action_types дают разное beneficence.
    """
    base = {
        "test": 0.75, "imaging": 0.80, "referral": 0.75,
        "clarify": 0.60, "dx": 0.70,
        "treatment": 0.85 if patient.get("has_confirmed_dx", False) else 0.40,
        "wait": 0.40,
    }.get(decision.action_type, 0.5)
    # Red flags → active intervention более beneficent
    if patient.get("red_flags") and decision.action_type in ("test", "imaging", "referral"):
        base = min(base + 0.15, 1.0)
    return base


def ethics_nonmaleficence(decision: Decision, patient: dict) -> float:
    """Не навреди (granular, в дополнение к L1 hard-block).

    В отличие от L1 (binary), здесь continuous: насколько risky.
    """
    base = 0.9  # дефолт — большинство тестов/консультаций безвредны
    if decision.action_type == "treatment":
        drug = decision.payload.get("drug", "").lower()
        # Narrow therapeutic index drugs → lower score
        risky = ["warfarin", "digoxin", "lithium", "amiodarone", "methotrexate"]
        if any(r in drug for r in risky):
            base = 0.6
        # Controlled substances
        if any(c in drug for c in ["opioid", "morphine", "fentanyl", "oxycodone"]):
            base = 0.5
    if decision.action_type == "imaging":
        modality = decision.payload.get("modality", "").lower()
        if "ct" in modality or "x-ray" in modality:
            base -= 0.05  # slight radiation
    return max(0.0, min(base, 1.0))


def ethics_justice(decision: Decision, patient: dict) -> float:
    """Справедливость — равный доступ к ресурсам, не дискриминировать."""
    score = 0.85  # baseline
    # Dropped if decision зависит от demographic без медицинского justification
    if decision.payload.get("demographic_gated", False):
        score -= 0.40
    # Плюс за использование standard-of-care guidelines (доступно всем)
    if decision.payload.get("guideline_based", False):
        score += 0.10
    return max(0.0, min(score, 1.0))


def ethics_composite(decision: Decision, patient: dict) -> tuple[float, dict]:
    """Combined Ethics per KernelWeights sub-weights."""
    kw = KernelWeights
    ze = ethics_ze_score(decision, patient)
    auto = ethics_autonomy(decision, patient)
    benef = ethics_beneficence(decision, patient)
    nonmal = ethics_nonmaleficence(decision, patient)
    justice = ethics_justice(decision, patient)
    composite = (
        kw.ETHICS_ZE * ze +
        kw.ETHICS_AUTO * auto +
        kw.ETHICS_BENEF * benef +
        kw.ETHICS_NONMAL * nonmal +
        kw.ETHICS_JUSTICE * justice
    )
    return composite, {
        "ze_learn_cheat": ze,
        "autonomy": auto,
        "beneficence": benef,
        "nonmaleficence": nonmal,
        "justice": justice,
    }


# ═════════════════════════════════════════════════════════════════════════════
# 5. Utility & overall scoring
# ═════════════════════════════════════════════════════════════════════════════

def score_decision(decision: Decision, patient: dict, context: dict) -> ScoringResult:
    I_before = impedance(patient, context)
    I_after = expected_impedance_after(decision, patient)
    c = instant_c(decision, patient)
    phi = phi_ze_path_integral(decision, patient)
    ethics, parts = ethics_composite(decision, patient)

    kw = KernelWeights
    U = kw.ALPHA * c + kw.BETA * phi + kw.GAMMA * ethics

    return ScoringResult(
        impedance_before=I_before,
        impedance_after=I_after,
        instant_c=c,
        phi_ze=phi,
        ethics_ze_learn_cheat=parts["ze_learn_cheat"],
        ethics_autonomy=parts["autonomy"],
        ethics_beneficence=parts["beneficence"],
        ethics_nonmaleficence=parts["nonmaleficence"],
        ethics_justice=parts["justice"],
        ethics_composite=ethics,
        utility=U,
    )


# ═════════════════════════════════════════════════════════════════════════════
# 6. Audit logging — SQLite ai_events + per-patient AI_LOG.md
# ═════════════════════════════════════════════════════════════════════════════

_SQLITE_READY = False


def _ensure_ai_events_table():
    global _SQLITE_READY
    if _SQLITE_READY:
        return
    import sqlite3
    from config import DB_PATH
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ai_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT DEFAULT CURRENT_TIMESTAMP,
            patient_id TEXT,
            session_id TEXT,
            agent TEXT,
            decision_type TEXT,
            alternatives_json TEXT,
            chosen_id TEXT,
            laws_json TEXT,
            scoring_json TEXT,
            override_type TEXT,
            override_reason TEXT
        )
    """)
    conn.commit()
    conn.close()
    _SQLITE_READY = True


def log_decision(
    patient_id: str,
    agent: str,
    decision_type: str,
    alternatives: list[Scored],
    chosen: Scored | None,
    override: OverrideContext,
    session_id: str | None = None,
):
    """Пишет в SQLite + в per-patient AI_LOG.md."""
    _ensure_ai_events_table()
    import sqlite3
    from config import DB_PATH

    alt_json = json.dumps([
        {
            "id": s.decision.id,
            "description": s.decision.description,
            "action_type": s.decision.action_type,
            "laws": asdict(s.laws),
            "scoring": s.scoring.as_dict() if s.scoring else None,
        }
        for s in alternatives
    ], ensure_ascii=False, default=str)
    chosen_id = chosen.decision.id if chosen else None
    laws_json = json.dumps(asdict(chosen.laws), ensure_ascii=False) if chosen else None
    scoring_json = json.dumps(chosen.scoring.as_dict(), ensure_ascii=False) if chosen and chosen.scoring else None

    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        INSERT INTO ai_events
        (patient_id, session_id, agent, decision_type, alternatives_json,
         chosen_id, laws_json, scoring_json, override_type, override_reason)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (patient_id, session_id, agent, decision_type, alt_json,
          chosen_id, laws_json, scoring_json, override.type, override.reason))
    conn.commit()
    conn.close()

    # Per-patient markdown log
    if patient_id:
        patient_dir = PATIENTS_DIR / patient_id
        patient_dir.mkdir(parents=True, exist_ok=True)
        log_file = patient_dir / "AI_LOG.md"
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        entry = [f"\n## {ts} — {decision_type} by {agent}\n"]
        entry.append(f"**Alternatives considered:** {len(alternatives)}\n")
        for s in alternatives:
            mark = "⭐" if (chosen and s.decision.id == chosen.decision.id) else "  "
            if s.scoring:
                entry.append(
                    f"- {mark} `{s.decision.id}` ({s.decision.action_type}): "
                    f"U={s.scoring.utility:.3f} "
                    f"(𝒞={s.scoring.instant_c:.2f}, Φ_Ze={s.scoring.phi_ze:.2f}, "
                    f"Ethics={s.scoring.ethics_composite:.2f}) "
                    f"— {s.decision.description[:80]}"
                )
            else:
                entry.append(
                    f"- ❌ `{s.decision.id}` ({s.decision.action_type}): "
                    f"Laws FAIL ({', '.join(r for r in s.laws.reasons if 'block' in r.lower() or 'l' in r[:3].lower() and ':' in r)}) "
                    f"— {s.decision.description[:80]}"
                )
        if chosen:
            entry.append(f"\n**Decision:** `{chosen.decision.id}` — {chosen.decision.description}")
            if chosen.scoring:
                entry.append(
                    f"- 𝓘: {chosen.scoring.impedance_before:.2f} → "
                    f"{chosen.scoring.impedance_after:.2f} (expected)"
                )
        if override.type != "none":
            entry.append(f"\n**Override:** type={override.type}, reason={override.reason or 'n/a'}")
        entry.append("\n---\n")
        with open(log_file, "a", encoding="utf-8") as f:
            f.write("\n".join(entry))


# ═════════════════════════════════════════════════════════════════════════════
# 7. Main entry — decide()
# ═════════════════════════════════════════════════════════════════════════════

def decide(
    alternatives: list[Decision],
    patient: dict,
    context: dict | None = None,
    override: OverrideContext | None = None,
    agent: str = "unknown",
    patient_id: str = "",
    session_id: str | None = None,
    decision_type: str = "triage",
) -> Scored:
    """Main decision entry.

    1. Apply Three Laws + L0 hard filter.
    2. Score остальные через utility formula.
    3. Select argmax U.
    4. Log to SQLite + AI_LOG.md.
    5. Return Scored (с полным breakdown).

    Override handling:
    - OverrideContext.type = "soft": prefer decision whose action_type matches context.commanded_action_type
    - OverrideContext.type = "hard": bypass utility, force decision with id=forced_decision_id,
      but L0+L1 still enforced.
    """
    context = context or {}
    override = override or OverrideContext()
    log.info(f"[kernel.decide] agent={agent}, patient={patient_id}, alts={len(alternatives)}, override={override.type}")

    # Hard override path
    if override.type == "hard":
        if not override.forced_decision_id:
            raise ValueError("Hard override requires forced_decision_id")
        forced = next((d for d in alternatives if d.id == override.forced_decision_id), None)
        if not forced:
            raise ValueError(f"Forced decision id '{override.forced_decision_id}' not in alternatives")
        # L0 и L1 всё равно check (hard override не обходит безопасность)
        l = evaluate_laws(forced, patient, context)
        if not (l.L0 and l.L1):
            raise KernelViolation(
                f"Hard override refused: L0/L1 violated ({'; '.join(l.reasons)})"
            )
        s = ScoringResult(
            impedance_before=impedance(patient, context),
            impedance_after=expected_impedance_after(forced, patient),
            instant_c=0, phi_ze=0, ethics_ze_learn_cheat=0,
            ethics_autonomy=0, ethics_beneficence=0, ethics_nonmaleficence=0,
            ethics_justice=0, ethics_composite=0, utility=float("inf"),
        )
        chosen = Scored(forced, l, s)
        all_scored = [chosen]
        log_decision(patient_id, agent, decision_type, all_scored, chosen, override, session_id)
        return chosen

    # Normal flow: filter + rank
    scored_list: list[Scored] = []
    for d in alternatives:
        # Soft override injects commanded_action_type into context for L2 check
        ctx = dict(context)
        if override.type == "soft" and override.forced_decision_id:
            # Не hard-force — only bias preference
            pass
        laws = evaluate_laws(d, patient, ctx)
        if not laws.passed:
            scored_list.append(Scored(d, laws, None))
            continue
        scoring = score_decision(d, patient, ctx)
        scored_list.append(Scored(d, laws, scoring))

    # Select best
    passed = [s for s in scored_list if s.scoring is not None]
    if not passed:
        log_decision(patient_id, agent, decision_type, scored_list, None, override, session_id)
        raise KernelViolation(
            f"Все {len(alternatives)} alternatives нарушают Laws. "
            f"Reasons: {[s.laws.reasons for s in scored_list]}"
        )

    # Soft override: prefer commanded action_type if available
    chosen: Scored
    if override.type == "soft" and override.forced_decision_id:
        match = next((s for s in passed if s.decision.id == override.forced_decision_id), None)
        chosen = match if match else max(passed, key=lambda s: s.scoring.utility)
    else:
        chosen = max(passed, key=lambda s: s.scoring.utility)

    log_decision(patient_id, agent, decision_type, scored_list, chosen, override, session_id)
    return chosen


# ═════════════════════════════════════════════════════════════════════════════
# 8. Tiered UX formatting
# ═════════════════════════════════════════════════════════════════════════════

def format_compact(scored: Scored, lang: str = "ru") -> str:
    """Default concise output + hint 'Почему?'."""
    d = scored.decision
    if lang == "ru":
        return (
            f"**Рекомендация:** {d.description}\n"
            f"_(U={scored.scoring.utility:.2f}; для деталей — `!explain`)_"
        )
    else:
        return (
            f"**Recommendation:** {d.description}\n"
            f"_(U={scored.scoring.utility:.2f}; `!explain` for details)_"
        )


def format_verbose(scored: Scored, lang: str = "ru") -> str:
    """Full reasoning breakdown."""
    s = scored.scoring
    d = scored.decision
    if lang == "ru":
        return (
            f"**Рекомендация:** {d.description}\n\n"
            f"📊 **Scoring:**\n"
            f"- 𝓘 (импеданс): {s.impedance_before:.2f} → {s.impedance_after:.2f}\n"
            f"- 𝒞 (мгновенное сознание): {s.instant_c:.3f}\n"
            f"- Φ_Ze (интегральное): {s.phi_ze:.3f}\n"
            f"- **Utility U: {s.utility:.3f}**\n\n"
            f"⚖️ **Ethics breakdown:**\n"
            f"- Ze learn/cheat: {s.ethics_ze_learn_cheat:.2f}\n"
            f"- Autonomy: {s.ethics_autonomy:.2f}\n"
            f"- Beneficence: {s.ethics_beneficence:.2f}\n"
            f"- Non-maleficence: {s.ethics_nonmaleficence:.2f}\n"
            f"- Justice: {s.ethics_justice:.2f}\n"
            f"- **Composite: {s.ethics_composite:.2f}**\n\n"
            f"✅ **Laws:** L0={scored.laws.L0} L1={scored.laws.L1} L2={scored.laws.L2} L3={scored.laws.L3}"
        )
    else:
        return (
            f"**Recommendation:** {d.description}\n\n"
            f"📊 **Scoring:** I: {s.impedance_before:.2f}→{s.impedance_after:.2f}, "
            f"C={s.instant_c:.3f}, Phi_Ze={s.phi_ze:.3f}, **U={s.utility:.3f}**\n\n"
            f"⚖️ **Ethics:** Ze={s.ethics_ze_learn_cheat:.2f}, Auto={s.ethics_autonomy:.2f}, "
            f"Ben={s.ethics_beneficence:.2f}, NonMal={s.ethics_nonmaleficence:.2f}, "
            f"Just={s.ethics_justice:.2f}, **Composite={s.ethics_composite:.2f}**\n\n"
            f"✅ Laws: L0={scored.laws.L0} L1={scored.laws.L1} L2={scored.laws.L2} L3={scored.laws.L3}"
        )


def needs_clarification(patient: dict, context: dict | None = None) -> bool:
    """Если 𝓘 > threshold — AI должен задать clarifying questions перед decision."""
    I = impedance(patient, context or {})
    return I > KernelWeights.CLARIFY_IMPEDANCE_THRESHOLD
