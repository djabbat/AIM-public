#!/usr/bin/env python3
"""
numerology.py — Нумерологический анализ по дате рождения
=========================================================
Используется проектом Space и AIM для персонализации.

Функции:
  life_path(dob)      → число жизненного пути (1-9, 11, 22, 33)
  expression(dob)     → число выражения (только из даты, без имени)
  birthday_number(dob)→ число дня рождения
  personal_year(dob, year) → персональный год
  numerology_profile(dob) → полный профиль dict
  from_patient_folder(folder_path) → профиль по папке пациента
  from_patient_db(patient_id)      → профиль из БД
"""

from datetime import date
from pathlib import Path
from typing import Optional
import re


# ── Core digit reduction ──────────────────────────────────────

MASTER_NUMBERS = {11, 22, 33}


def reduce(n: int, keep_masters: bool = True) -> int:
    """Reduce number to single digit, keeping master numbers 11, 22, 33."""
    while n > 9:
        if keep_masters and n in MASTER_NUMBERS:
            break
        n = sum(int(d) for d in str(n))
    return n


# ── Core calculations ─────────────────────────────────────────

def life_path(dob: date) -> int:
    """
    Number of life path = reduce(day + month + year).
    Each component reduced first, then summed.
    Example: 15.06.1985 → (1+5) + (6) + (1+9+8+5) = 6+6+23 = 6+6+5 = 17 → 8
    """
    d = reduce(dob.day)
    m = reduce(dob.month)
    y = reduce(sum(int(c) for c in str(dob.year)))
    return reduce(d + m + y)


def birthday_number(dob: date) -> int:
    """Day of birth reduced to single digit (or master number)."""
    return reduce(dob.day)


def personal_year(dob: date, year: Optional[int] = None) -> int:
    """Personal year = reduce(day + month + universal_year)."""
    if year is None:
        year = date.today().year
    universal = reduce(sum(int(c) for c in str(year)))
    return reduce(reduce(dob.day) + reduce(dob.month) + universal)


def attitude_number(dob: date) -> int:
    """Attitude (day + month) — how you present to the world."""
    return reduce(dob.day + dob.month)


def generation_number(dob: date) -> int:
    """Generation number from birth year."""
    return reduce(sum(int(c) for c in str(dob.year)))


# ── Interpretations ───────────────────────────────────────────

LIFE_PATH_MEANING = {
    1:  "Лидер, первопроходец, независимость, индивидуальность",
    2:  "Дипломат, чуткость, сотрудничество, баланс",
    3:  "Творчество, общение, оптимизм, самовыражение",
    4:  "Организованность, труд, стабильность, практичность",
    5:  "Свобода, приключения, перемены, адаптивность",
    6:  "Ответственность, семья, забота, гармония",
    7:  "Аналитик, духовность, поиск истины, интроверт",
    8:  "Амбиции, власть, материальный успех, менеджмент",
    9:  "Гуманизм, сострадание, мудрость, завершение",
    11: "Мастер-интуит, вдохновение, духовный учитель",
    22: "Мастер-строитель, реализация великих планов",
    33: "Мастер-учитель, бескорыстное служение",
}

PERSONAL_YEAR_MEANING = {
    1: "Новый цикл. Время начинать, сеять семена",
    2: "Партнёрство, терпение, детали",
    3: "Рост, творчество, общение",
    4: "Труд, фундамент, здоровье",
    5: "Перемены, свобода, непредсказуемость",
    6: "Семья, ответственность, дом",
    7: "Рефлексия, духовность, уединение",
    8: "Сбор урожая, деньги, карьера",
    9: "Завершение цикла, отпускание, итоги",
    11: "Интуиция, духовные испытания",
    22: "Реализация большого проекта",
}


# ── Full profile ──────────────────────────────────────────────

def numerology_profile(dob: date) -> dict:
    """
    Returns full numerology profile for a date of birth.
    Used by AIM patient intake and Space project.
    """
    lp = life_path(dob)
    bn = birthday_number(dob)
    py = personal_year(dob)
    att = attitude_number(dob)
    gen = generation_number(dob)

    return {
        "dob": dob.isoformat(),
        "life_path": lp,
        "life_path_meaning": LIFE_PATH_MEANING.get(lp, ""),
        "birthday_number": bn,
        "personal_year": py,
        "personal_year_meaning": PERSONAL_YEAR_MEANING.get(py, ""),
        "attitude_number": att,
        "generation_number": gen,
        "is_master": lp in MASTER_NUMBERS,
        "year_analyzed": date.today().year,
    }


def format_profile(profile: dict, lang: str = "ru") -> str:
    """Format numerology profile as human-readable text."""
    lines = [
        f"🔢 НУМЕРОЛОГИЧЕСКИЙ ПРОФИЛЬ",
        f"Дата рождения: {profile['dob']}",
        f"",
        f"Число жизненного пути: {profile['life_path']}"
        + (" ✨ МАСТЕР-ЧИСЛО" if profile['is_master'] else ""),
        f"  → {profile['life_path_meaning']}",
        f"",
        f"Число дня рождения: {profile['birthday_number']}",
        f"Число отношения: {profile['attitude_number']}",
        f"Число поколения: {profile['generation_number']}",
        f"",
        f"Персональный год ({profile['year_analyzed']}): {profile['personal_year']}",
        f"  → {profile['personal_year_meaning']}",
    ]
    return "\n".join(lines)


# ── Patient integration ───────────────────────────────────────

_FOLDER_RE = re.compile(
    r'^[A-Za-zА-Яа-яЁёა-ჿ\-]+_[A-Za-zА-Яа-яЁёა-ჿ\-]+_(\d{4})_(\d{2})_(\d{2})$'
)


def from_patient_folder(folder_path: str) -> Optional[dict]:
    """Extract DOB from folder name and return numerology profile."""
    folder = Path(folder_path)
    m = _FOLDER_RE.match(folder.name)
    if not m:
        return None
    try:
        dob = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        return numerology_profile(dob)
    except ValueError:
        return None


def from_patient_db(patient_id: int) -> Optional[dict]:
    """Load DOB from AIM SQLite DB and return numerology profile."""
    try:
        import db as _db
        conn = _db._get_conn()
        row = conn.execute(
            "SELECT dob FROM patients WHERE id = ?", (patient_id,)
        ).fetchone()
        if row and row[0]:
            dob_str = row[0]  # "YYYY-MM-DD"
            dob = date.fromisoformat(dob_str)
            return numerology_profile(dob)
    except Exception:
        pass
    return None


def enrich_patient_analysis(folder_path: str) -> str:
    """
    Returns numerology section to append to patient analysis.
    Returns empty string if DOB not available.
    """
    profile = from_patient_folder(folder_path)
    if not profile:
        return ""
    return "\n\n" + "=" * 60 + "\n" + format_profile(profile) + "\n"


# ── CLI ───────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        # Accept DD.MM.YYYY or YYYY-MM-DD or patient folder path
        p = Path(arg)
        if p.is_dir():
            prof = from_patient_folder(arg)
        else:
            try:
                if "." in arg:
                    parts = arg.split(".")
                    d = date(int(parts[2]), int(parts[1]), int(parts[0]))
                else:
                    d = date.fromisoformat(arg)
                prof = numerology_profile(d)
            except Exception:
                print(f"Usage: python3 numerology.py 15.06.1985")
                sys.exit(1)
        if prof:
            print(format_profile(prof))
        else:
            print("DOB not found in folder name.")
    else:
        # Demo
        demo = date(1985, 6, 15)
        print(format_profile(numerology_profile(demo)))
