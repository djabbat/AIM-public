"""
AIM v7.0 — Patient Memory
==========================

Per Q8: hybrid format — markdown canonical + SQLite index.

- `Patients/<ID>/MEMORY.md` — human-readable canonical (AI + врач редактируют)
- SQLite table `patient_index` — fast cross-patient queries

Structure MEMORY.md:
  # Memory — <Patient_ID>
  ## Demographics
  ## Allergies
  ## Medications
  ## History (reverse-chron)
  ## Known unknowns
  ## AI decision log → (actual decisions в AI_LOG.md, это только references)
"""
from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from config import PATIENTS_DIR, DB_PATH

# ═════════════════════════════════════════════════════════════════════════════
# Data model
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class PatientMemory:
    """In-memory representation of patient state."""
    id: str
    demographics: dict = field(default_factory=dict)   # age, sex, country
    allergies: list[str] = field(default_factory=list)
    medications: list[dict] = field(default_factory=list)  # [{name, dose, freq}]
    conditions: list[dict] = field(default_factory=list)   # [{dx, since, notes}]
    history: list[str] = field(default_factory=list)       # free-form history items
    known_unknowns: list[str] = field(default_factory=list)
    # derived for kernel scoring
    red_flags: list[str] = field(default_factory=list)
    missing_labs_count: int = 0
    history_contradictions: int = 0
    unexplained_symptoms_count: int = 0
    last_visit_years_ago: float = 0.0
    dx_without_evidence: bool = False
    primary_complaint_undiagnosed: bool = True
    has_confirmed_dx: bool = False

    def to_kernel_dict(self) -> dict:
        """Flat dict для передачи в kernel.impedance / decide."""
        return {
            "id": self.id,
            "age": self.demographics.get("age"),
            "sex": self.demographics.get("sex"),
            "allergies": self.allergies,
            "medications": self.medications,
            "red_flags": self.red_flags,
            "missing_labs_count": self.missing_labs_count,
            "history_contradictions": self.history_contradictions,
            "unexplained_symptoms_count": self.unexplained_symptoms_count,
            "last_visit_years_ago": self.last_visit_years_ago,
            "dx_without_evidence": self.dx_without_evidence,
            "primary_complaint_undiagnosed": self.primary_complaint_undiagnosed,
            "has_confirmed_dx": self.has_confirmed_dx,
        }


# ═════════════════════════════════════════════════════════════════════════════
# SQLite index
# ═════════════════════════════════════════════════════════════════════════════

def _ensure_index_table():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS patient_index (
            patient_id TEXT PRIMARY KEY,
            age INTEGER,
            sex TEXT,
            allergies_json TEXT,
            conditions_json TEXT,
            last_updated TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def _update_index(mem: PatientMemory):
    import json
    _ensure_index_table()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        INSERT OR REPLACE INTO patient_index
        (patient_id, age, sex, allergies_json, conditions_json, last_updated)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        mem.id,
        mem.demographics.get("age"),
        mem.demographics.get("sex"),
        json.dumps(mem.allergies, ensure_ascii=False),
        json.dumps(mem.conditions, ensure_ascii=False, default=str),
        time.strftime("%Y-%m-%d %H:%M:%S"),
    ))
    conn.commit()
    conn.close()


# ═════════════════════════════════════════════════════════════════════════════
# Markdown I/O (canonical)
# ═════════════════════════════════════════════════════════════════════════════

_TEMPLATE = """# Memory — {id}

## Demographics
- Age: {age}
- Sex: {sex}
- Country: {country}

## Allergies
{allergies_bullets}

## Medications
{medications_bullets}

## Conditions
{conditions_bullets}

## History (reverse-chron)
{history_bullets}

## Known unknowns
{unknowns_bullets}

## Derived (для kernel scoring)
- primary_complaint_undiagnosed: {pcu}
- has_confirmed_dx: {hcd}
- missing_labs_count: {mlc}
- history_contradictions: {hc}
- unexplained_symptoms_count: {usc}
- last_visit_years_ago: {lvya}
- dx_without_evidence: {dwe}

---
_Last updated: {ts}. Edit freely; AIM will parse on next read._
"""


def _bullets(items: list[str], empty: str = "_(none)_") -> str:
    if not items:
        return empty
    return "\n".join(f"- {it}" for it in items)


def _bullets_med(meds: list[dict]) -> str:
    if not meds:
        return "_(none)_"
    return "\n".join(
        f"- {m.get('name', '?')} · {m.get('dose', '?')} · {m.get('freq', '?')}"
        for m in meds
    )


def _bullets_cond(conds: list[dict]) -> str:
    if not conds:
        return "_(none)_"
    return "\n".join(
        f"- {c.get('dx', '?')} ({c.get('since', '?')}): {c.get('notes', '')}"
        for c in conds
    )


def write_memory(mem: PatientMemory) -> Path:
    """Сериализует PatientMemory → MEMORY.md. Обновляет SQLite index."""
    patient_dir = PATIENTS_DIR / mem.id
    patient_dir.mkdir(parents=True, exist_ok=True)
    file = patient_dir / "MEMORY.md"
    content = _TEMPLATE.format(
        id=mem.id,
        age=mem.demographics.get("age", "?"),
        sex=mem.demographics.get("sex", "?"),
        country=mem.demographics.get("country", "?"),
        allergies_bullets=_bullets(mem.allergies),
        medications_bullets=_bullets_med(mem.medications),
        conditions_bullets=_bullets_cond(mem.conditions),
        history_bullets=_bullets(mem.history),
        unknowns_bullets=_bullets(mem.known_unknowns),
        pcu=mem.primary_complaint_undiagnosed,
        hcd=mem.has_confirmed_dx,
        mlc=mem.missing_labs_count,
        hc=mem.history_contradictions,
        usc=mem.unexplained_symptoms_count,
        lvya=mem.last_visit_years_ago,
        dwe=mem.dx_without_evidence,
        ts=time.strftime("%Y-%m-%d %H:%M:%S"),
    )
    file.write_text(content, encoding="utf-8")
    _update_index(mem)
    return file


def read_memory(patient_id: str) -> PatientMemory | None:
    """Parse MEMORY.md → PatientMemory."""
    file = PATIENTS_DIR / patient_id / "MEMORY.md"
    if not file.exists():
        return None

    text = file.read_text(encoding="utf-8")
    mem = PatientMemory(id=patient_id)

    # Simple section parser
    sections = {}
    current = None
    for line in text.splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            sections[current] = []
        elif current is not None:
            sections[current].append(line)

    # Demographics
    for line in sections.get("Demographics", []):
        m = re.match(r"^- (\w+):\s*(.+)$", line.strip())
        if m:
            k, v = m.group(1).lower(), m.group(2).strip()
            if k == "age":
                try: mem.demographics["age"] = int(v)
                except: pass
            else:
                mem.demographics[k] = v

    # Allergies
    for line in sections.get("Allergies", []):
        s = line.strip()
        if s.startswith("- ") and not s.startswith("- _"):
            mem.allergies.append(s[2:].strip())

    # Medications
    for line in sections.get("Medications", []):
        s = line.strip()
        if s.startswith("- ") and not s.startswith("- _"):
            parts = [p.strip() for p in s[2:].split("·")]
            med = {"name": parts[0] if parts else "?"}
            if len(parts) > 1: med["dose"] = parts[1]
            if len(parts) > 2: med["freq"] = parts[2]
            mem.medications.append(med)

    # Conditions
    for line in sections.get("Conditions", []):
        s = line.strip()
        if s.startswith("- ") and not s.startswith("- _"):
            m = re.match(r"- (.+?) \((.+?)\):?\s*(.*)$", s)
            if m:
                mem.conditions.append({
                    "dx": m.group(1), "since": m.group(2), "notes": m.group(3)
                })

    # History
    for line in sections.get("History (reverse-chron)", []):
        s = line.strip()
        if s.startswith("- ") and not s.startswith("- _"):
            mem.history.append(s[2:].strip())

    # Unknowns
    for line in sections.get("Known unknowns", []):
        s = line.strip()
        if s.startswith("- ") and not s.startswith("- _"):
            mem.known_unknowns.append(s[2:].strip())

    # Derived
    for line in sections.get("Derived (для kernel scoring)", []):
        m = re.match(r"^- (\w+):\s*(.+)$", line.strip())
        if m:
            k, v = m.group(1), m.group(2).strip()
            if hasattr(mem, k):
                cur = getattr(mem, k)
                try:
                    if isinstance(cur, bool):
                        setattr(mem, k, v.lower() == "true")
                    elif isinstance(cur, int):
                        setattr(mem, k, int(v))
                    elif isinstance(cur, float):
                        setattr(mem, k, float(v))
                except Exception:
                    pass

    # If has_confirmed_dx not set but conditions exist → derive
    if mem.conditions and not mem.has_confirmed_dx:
        mem.has_confirmed_dx = True
        mem.primary_complaint_undiagnosed = False

    _update_index(mem)
    return mem


def load_or_create(patient_id: str, **defaults) -> PatientMemory:
    """Read MEMORY.md, или создать new из defaults если не существует."""
    mem = read_memory(patient_id)
    if mem:
        return mem
    mem = PatientMemory(id=patient_id, **defaults)
    write_memory(mem)
    return mem


def list_patients() -> list[dict]:
    """Query SQLite index → list of patients (for cross-patient analytics)."""
    _ensure_index_table()
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("""
        SELECT patient_id, age, sex, allergies_json, conditions_json, last_updated
        FROM patient_index
        ORDER BY last_updated DESC
    """).fetchall()
    conn.close()
    import json
    return [
        {
            "id": r[0], "age": r[1], "sex": r[2],
            "allergies": json.loads(r[3] or "[]"),
            "conditions": json.loads(r[4] or "[]"),
            "last_updated": r[5],
        }
        for r in rows
    ]
