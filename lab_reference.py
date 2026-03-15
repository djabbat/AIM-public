#!/usr/bin/env python3
"""
Reference ranges for clinical lab tests.
Supports age groups, sex, and units.
Sources: WHO, IFCC, national clinical guidelines.
"""

from dataclasses import dataclass
from typing import Optional, Dict, Tuple

# ─────────────────────────────────────────────────────────────
# Reference range for one parameter in one demographic group
# ─────────────────────────────────────────────────────────────
@dataclass
class RefRange:
    low: float
    high: float
    unit: str
    critical_low: Optional[float] = None
    critical_high: Optional[float] = None
    note: str = ""


# ─────────────────────────────────────────────────────────────
# Master reference database
# Key: (parameter_id, sex, age_group)
#   sex: "M" | "F" | "*"
#   age_group: "adult" | "child" | "elder" | "*"
# ─────────────────────────────────────────────────────────────
REFERENCE_DB: Dict[tuple, RefRange] = {

    # ── CBC / Общий анализ крови ──────────────────────────────

    ("WBC", "*", "adult"):   RefRange(4.0,   10.0,  "×10⁹/L", 2.0, 30.0, "Лейкоциты"),
    ("WBC", "*", "child"):   RefRange(6.0,   17.0,  "×10⁹/L", 2.0, 30.0, "Лейкоциты"),
    ("RBC", "M", "adult"):   RefRange(4.5,   5.9,   "×10¹²/L", 2.5, 7.0, "Эритроциты"),
    ("RBC", "F", "adult"):   RefRange(3.9,   5.1,   "×10¹²/L", 2.5, 7.0, "Эритроциты"),
    ("HGB", "M", "adult"):   RefRange(130,   170,   "g/L", 70, 200, "Гемоглобин"),
    ("HGB", "F", "adult"):   RefRange(115,   155,   "g/L", 70, 200, "Гемоглобин"),
    ("HCT", "M", "adult"):   RefRange(0.40,  0.52,  "%", 0.20, 0.65, "Гематокрит"),
    ("HCT", "F", "adult"):   RefRange(0.35,  0.47,  "%", 0.20, 0.65, "Гематокрит"),
    ("MCV", "*", "adult"):   RefRange(80,    100,   "fL", 60, 120, "Средний объём эритроцита"),
    ("MCH", "*", "adult"):   RefRange(27,    34,    "pg", 20, 40, "Ср. содержание Hb в эр-те"),
    ("MCHC","*", "adult"):   RefRange(315,   370,   "g/L", 280, 400, "Ср. концентрация Hb"),
    ("PLT", "*", "adult"):   RefRange(150,   400,   "×10⁹/L", 50, 1000, "Тромбоциты"),
    ("PLT", "*", "child"):   RefRange(150,   450,   "×10⁹/L", 50, 1000, "Тромбоциты"),
    ("NEUT","*", "adult"):   RefRange(1.8,   7.7,   "×10⁹/L", 0.5, 20.0, "Нейтрофилы абс."),
    ("NEUT%","*","adult"):   RefRange(45,    75,    "%",  None, None, "Нейтрофилы %"),
    ("LYMPH","*","adult"):   RefRange(1.0,   4.8,   "×10⁹/L", 0.5, 15.0, "Лимфоциты абс."),
    ("LYMPH%","*","adult"):  RefRange(20,    45,    "%",  None, None, "Лимфоциты %"),
    ("MONO%","*","adult"):   RefRange(2,     10,    "%",  None, None, "Моноциты %"),
    ("EOS%", "*","adult"):   RefRange(0.5,   5.0,   "%",  None, None, "Эозинофилы %"),
    ("BASO%","*","adult"):   RefRange(0,     1.0,   "%",  None, None, "Базофилы %"),
    ("ESR",  "M","adult"):   RefRange(0,     15,    "mm/h", None, None, "СОЭ"),
    ("ESR",  "F","adult"):   RefRange(0,     20,    "mm/h", None, None, "СОЭ"),

    # ── Biochemistry / Биохимия ───────────────────────────────

    ("GLU",  "*","adult"):   RefRange(3.9,   6.1,   "mmol/L", 2.2, 22.2, "Глюкоза"),
    ("GLU",  "*","child"):   RefRange(3.3,   5.5,   "mmol/L", 2.2, 22.2, "Глюкоза"),
    ("HBA1C","*","adult"):   RefRange(4.0,   5.7,   "%",  None, None,  "HbA1c (норма)"),
    ("CREA", "M","adult"):   RefRange(62,    115,   "μmol/L", 30, 500, "Креатинин"),
    ("CREA", "F","adult"):   RefRange(44,    97,    "μmol/L", 30, 500, "Креатинин"),
    ("UREA", "*","adult"):   RefRange(2.5,   8.3,   "mmol/L", None, 35.0, "Мочевина"),
    ("UA",   "M","adult"):   RefRange(200,   420,   "μmol/L", None, 600, "Мочевая кислота"),
    ("UA",   "F","adult"):   RefRange(140,   360,   "μmol/L", None, 600, "Мочевая кислота"),
    ("TBIL", "*","adult"):   RefRange(5,     21,    "μmol/L", None, 340, "Билирубин общий"),
    ("DBIL", "*","adult"):   RefRange(0,     5,     "μmol/L", None, None, "Билирубин прямой"),
    ("ALT",  "*","adult"):   RefRange(0,     40,    "U/L",  None, None, "АЛТ"),
    ("AST",  "*","adult"):   RefRange(0,     40,    "U/L",  None, None, "АСТ"),
    ("ALP",  "*","adult"):   RefRange(44,    147,   "U/L",  None, None, "Щелочная фосфатаза"),
    ("GGT",  "M","adult"):   RefRange(10,    71,    "U/L",  None, None, "ГГТ"),
    ("GGT",  "F","adult"):   RefRange(6,     42,    "U/L",  None, None, "ГГТ"),
    ("TP",   "*","adult"):   RefRange(60,    83,    "g/L",  None, None, "Белок общий"),
    ("ALB",  "*","adult"):   RefRange(35,    52,    "g/L",  None, None, "Альбумин"),
    ("CHOL", "*","adult"):   RefRange(3.1,   5.2,   "mmol/L", None, None, "Холестерин общий"),
    ("LDL",  "*","adult"):   RefRange(0,     3.0,   "mmol/L", None, None, "ЛПНП"),
    ("HDL",  "M","adult"):   RefRange(1.0,   2.0,   "mmol/L", None, None, "ЛПВП"),
    ("HDL",  "F","adult"):   RefRange(1.2,   2.5,   "mmol/L", None, None, "ЛПВП"),
    ("TG",   "*","adult"):   RefRange(0,     1.7,   "mmol/L", None, None, "Триглицериды"),
    ("NA",   "*","adult"):   RefRange(136,   145,   "mmol/L", 120, 160, "Натрий"),
    ("K",    "*","adult"):   RefRange(3.5,   5.1,   "mmol/L", 2.5, 6.5, "Калий"),
    ("CL",   "*","adult"):   RefRange(97,    107,   "mmol/L", None, None, "Хлор"),
    ("CA",   "*","adult"):   RefRange(2.15,  2.55,  "mmol/L", 1.5, 3.5, "Кальций"),
    ("MG",   "*","adult"):   RefRange(0.65,  1.05,  "mmol/L", None, None, "Магний"),
    ("FE",   "M","adult"):   RefRange(11,    30,    "μmol/L", None, None, "Железо"),
    ("FE",   "F","adult"):   RefRange(9,     27,    "μmol/L", None, None, "Железо"),
    ("FERR", "M","adult"):   RefRange(15,    200,   "μg/L",  None, None, "Ферритин"),
    ("FERR", "F","adult"):   RefRange(10,    120,   "μg/L",  None, None, "Ферритин"),
    ("TIBC", "*","adult"):   RefRange(45,    72,    "μmol/L", None, None, "ОЖСС"),
    ("CRP",  "*","adult"):   RefRange(0,     5.0,   "mg/L",  None, None, "СРБ"),
    ("PCT",  "*","adult"):   RefRange(0,     0.05,  "ng/mL", None, None, "Прокальцитонин"),

    # ── Thyroid / Щитовидная железа ──────────────────────────

    ("TSH",  "*","adult"):   RefRange(0.4,   4.0,   "mIU/L", 0.01, 100, "ТТГ"),
    ("T4F",  "*","adult"):   RefRange(12,    22,    "pmol/L", None, None, "Т4 свободный"),
    ("T3F",  "*","adult"):   RefRange(3.1,   6.8,   "pmol/L", None, None, "Т3 свободный"),
    ("TPO",  "*","adult"):   RefRange(0,     34,    "IU/mL", None, None, "Антитела к ТПО"),

    # ── Hormones / Гормоны ────────────────────────────────────

    ("CORT", "*","adult"):   RefRange(138,   635,   "nmol/L", None, None, "Кортизол (утро)"),
    ("INS",  "*","adult"):   RefRange(2.6,   24.9,  "μIU/mL", None, None, "Инсулин"),
    ("HOMA", "*","adult"):   RefRange(0,     2.7,   "ind",  None, None, "HOMA-IR"),
    ("PROG", "F","adult"):   RefRange(0.6,   25.0,  "nmol/L", None, None, "Прогестерон (вариир.)"),
    ("E2",   "F","adult"):   RefRange(37,    1250,  "pmol/L", None, None, "Эстрадиол (вариир.)"),
    ("FSH",  "F","adult"):   RefRange(1.8,   11.3,  "IU/L",  None, None, "ФСГ (фолликул. фаза)"),
    ("LH",   "F","adult"):   RefRange(1.1,   11.6,  "IU/L",  None, None, "ЛГ"),
    ("TEST", "M","adult"):   RefRange(9.9,   27.8,  "nmol/L", None, None, "Тестостерон"),
    ("TEST", "F","adult"):   RefRange(0.3,   2.4,   "nmol/L", None, None, "Тестостерон"),
    ("DHEAS","*","adult"):   RefRange(1.3,   9.8,   "μmol/L", None, None, "ДГЭА-С"),
    ("VD25", "*","adult"):   RefRange(50,    125,   "nmol/L", None, None, "Витамин D 25(OH)"),
    ("VB12", "*","adult"):   RefRange(148,   616,   "pmol/L", None, None, "Витамин B12"),
    ("FOLAT","*","adult"):   RefRange(7,     45,    "nmol/L", None, None, "Фолиевая кислота"),

    # ── Urine / Моча ──────────────────────────────────────────

    ("UPROTEIN","*","adult"): RefRange(0, 0.15,  "g/day", None, None, "Белок в моче (суточный)"),
    ("UGLUCOSE","*","adult"): RefRange(0, 0.8,   "mmol/L", None, None, "Глюкоза в моче"),
    ("UPROT_QT","*","adult"): RefRange(0, 0.14,  "g/L",   None, None, "Белок в моче (разовый)"),

    # ── Coagulation / Гемостаз ────────────────────────────────

    ("PT",   "*","adult"):   RefRange(11,    15,    "sec", None, None, "Протромбиновое время"),
    ("INR",  "*","adult"):   RefRange(0.85,  1.15,  "",   None, None, "МНО"),
    ("APTT", "*","adult"):   RefRange(26,    38,    "sec", None, None, "АПТВ"),
    ("FIB",  "*","adult"):   RefRange(2.0,   4.0,   "g/L", None, None, "Фибриноген"),
    ("DDIMER","*","adult"):  RefRange(0,     0.5,   "μg/mL FEU", None, None, "D-димер"),
}


# ─────────────────────────────────────────────────────────────
# Aliases (alternative names → canonical ID)
# ─────────────────────────────────────────────────────────────
ALIASES: Dict[str, str] = {
    # Russian
    "лейкоциты": "WBC", "лейк": "WBC", "wbc": "WBC",
    "эритроциты": "RBC", "rbc": "RBC",
    "гемоглобин": "HGB", "hgb": "HGB", "hb": "HGB",
    "гематокрит": "HCT", "hct": "HCT",
    "тромбоциты": "PLT", "plt": "PLT",
    "нейтрофилы": "NEUT%", "нейтр": "NEUT%",
    "лимфоциты": "LYMPH%", "лимф": "LYMPH%",
    "моноциты": "MONO%",
    "эозинофилы": "EOS%", "эозин": "EOS%",
    "базофилы": "BASO%",
    "соэ": "ESR", "скорость оседания эритроцитов": "ESR",
    "глюкоза": "GLU", "сахар": "GLU", "glu": "GLU",
    "hba1c": "HBA1C", "гликированный гемоглобин": "HBA1C",
    "креатинин": "CREA", "crea": "CREA",
    "мочевина": "UREA", "urea": "UREA",
    "мочевая кислота": "UA",
    "билирубин общий": "TBIL", "билирубин": "TBIL", "tbil": "TBIL",
    "алт": "ALT", "alt": "ALT", "аланинаминотрансфераза": "ALT",
    "аст": "AST", "ast": "AST",
    "щелочная фосфатаза": "ALP", "алф": "ALP",
    "ггт": "GGT", "γ-гт": "GGT",
    "белок общий": "TP", "белок": "TP",
    "альбумин": "ALB", "alb": "ALB",
    "холестерин": "CHOL", "chol": "CHOL",
    "лпнп": "LDL", "ldl": "LDL",
    "лпвп": "HDL", "hdl": "HDL",
    "триглицериды": "TG", "тг": "TG",
    "натрий": "NA", "na": "NA",
    "калий": "K", "k": "K",
    "кальций": "CA", "ca": "CA",
    "магний": "MG", "mg": "MG",
    "железо": "FE", "fe": "FE",
    "ферритин": "FERR", "ferritin": "FERR",
    "срб": "CRP", "с-реактивный белок": "CRP", "crp": "CRP",
    "ттг": "TSH", "tsh": "TSH", "тиреотропный гормон": "TSH",
    "т4 своб": "T4F", "т4 свободный": "T4F", "ft4": "T4F",
    "т3 своб": "T3F", "ft3": "T3F",
    "антитела к тпо": "TPO", "ат-тпо": "TPO", "антитела тпо": "TPO",
    "кортизол": "CORT", "cortisol": "CORT",
    "инсулин": "INS", "insulin": "INS",
    "витамин d": "VD25", "25(oh)d": "VD25", "vit d": "VD25",
    "витамин b12": "VB12", "b12": "VB12",
    "фолиевая кислота": "FOLAT", "фолат": "FOLAT",
    "мно": "INR", "inr": "INR",
    "d-димер": "DDIMER", "d-dimer": "DDIMER",
    # Georgian (partial)
    "ლეიკოციტები": "WBC",
    "ჰემოგლობინი": "HGB",
    "თრომბოციტები": "PLT",
    "გლუკოზა": "GLU",
    "ქოლესტერინი": "CHOL",
    "კრეატინინი": "CREA",
    "ფერიტინი": "FERR",
    "ვიტ. d": "VD25",
    "ბ12": "VB12",
    "ttg": "TSH",
}


def resolve_param(name: str) -> Optional[str]:
    """Resolve parameter name/alias to canonical ID."""
    key = name.strip().lower()
    # Direct alias lookup
    if key in ALIASES:
        return ALIASES[key]
    # Try uppercase exact match
    up = key.upper()
    if any(k[0] == up for k in REFERENCE_DB):
        return up
    return None


def get_reference(param_id: str, sex: str = "*", age_group: str = "adult") -> Optional[RefRange]:
    """Get reference range, with fallback to sex='*'."""
    for s in [sex, "*"]:
        for ag in [age_group, "adult", "*"]:
            key = (param_id, s, ag)
            if key in REFERENCE_DB:
                return REFERENCE_DB[key]
    return None


STATUS_EMOJI = {
    "critical_low":  "🔴 КРИТИЧЕСКИ НИЗКО",
    "low":           "🟡 НИЖЕ НОРМЫ",
    "normal":        "🟢 НОРМА",
    "high":          "🟡 ВЫШЕ НОРМЫ",
    "critical_high": "🔴 КРИТИЧЕСКИ ВЫСОКО",
    "unknown":       "⚪ НЕТ РЕФЕРЕНСА",
}


@dataclass
class LabResult:
    param_id: str
    name: str
    value: float
    unit: str
    status: str      # critical_low / low / normal / high / critical_high / unknown
    ref: Optional[RefRange]
    deviation_pct: float = 0.0  # % above/below nearest boundary


def evaluate(param_id: str, value: float, sex: str = "*",
             age_group: str = "adult") -> LabResult:
    """Evaluate a single lab value against reference range."""
    ref = get_reference(param_id, sex, age_group)
    name = (ref.note if ref else param_id)

    if ref is None:
        return LabResult(param_id, name, value, "", "unknown", None, 0.0)

    if ref.critical_low is not None and value < ref.critical_low:
        status = "critical_low"
        dev = (ref.critical_low - value) / ref.critical_low * 100
    elif value < ref.low:
        status = "low"
        dev = (ref.low - value) / ref.low * 100
    elif ref.critical_high is not None and value > ref.critical_high:
        status = "critical_high"
        dev = (value - ref.critical_high) / ref.critical_high * 100
    elif value > ref.high:
        status = "high"
        dev = (value - ref.high) / ref.high * 100
    else:
        status = "normal"
        dev = 0.0

    return LabResult(param_id, name, value, ref.unit, status, ref, round(dev, 1))
