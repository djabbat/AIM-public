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

    # ── Elder-specific adjustments (>65 лет) ─────────────────
    # Лабораторные нормы для пожилых согласно IFCC/EFLM рекомендациям

    ("HGB", "M", "elder"):   RefRange(120,   170,   "g/L", 70, 200, "Гемоглобин"),
    ("HGB", "F", "elder"):   RefRange(110,   155,   "g/L", 70, 200, "Гемоглобин"),
    ("CREA", "M","elder"):   RefRange(62,    124,   "μmol/L", 30, 500, "Креатинин"),
    ("CREA", "F","elder"):   RefRange(44,    104,   "μmol/L", 30, 500, "Креатинин"),
    ("GLU",  "*","elder"):   RefRange(4.4,   7.0,   "mmol/L", 2.2, 22.2, "Глюкоза (пожилые)"),
    ("TSH",  "*","elder"):   RefRange(0.4,   6.0,   "mIU/L", 0.01, 100, "ТТГ (пожилые)"),
    ("VD25", "*","elder"):   RefRange(50,    125,   "nmol/L", None, None, "Витамин D 25(OH)"),
    ("ESR",  "M","elder"):   RefRange(0,     20,    "mm/h", None, None, "СОЭ (пожилые М)"),
    ("ESR",  "F","elder"):   RefRange(0,     30,    "mm/h", None, None, "СОЭ (пожилые Ж)"),
    ("CHOL", "*","elder"):   RefRange(3.1,   6.2,   "mmol/L", None, None, "Холестерин (пожилые)"),

    # ── Child-specific (до 18 лет) ────────────────────────────

    ("HGB", "*", "child"):   RefRange(110,   145,   "g/L", 70, 200, "Гемоглобин (дети)"),
    ("CREA", "*","child"):   RefRange(27,    62,    "μmol/L", 15, 300, "Креатинин (дети)"),
    ("ALP",  "*","child"):   RefRange(100,   400,   "U/L",  None, None, "ЩФ (дети — выше нормы взрослых)"),
    ("TSH",  "*","child"):   RefRange(0.7,   5.7,   "mIU/L", 0.01, 100, "ТТГ (дети)"),
    ("CHOL", "*","child"):   RefRange(2.9,   5.2,   "mmol/L", None, None, "Холестерин (дети)"),

    # ── CBC дополнительно ─────────────────────────────────────

    ("RDW",  "*","adult"):   RefRange(11.5,  14.5,  "%",    None, None, "RDW (ширина распределения эр-тов)"),
    ("MPV",  "*","adult"):   RefRange(7.0,   12.0,  "fL",   None, None, "MPV (средний объём тромбоцита)"),
    ("PDW",  "*","adult"):   RefRange(10,    17,    "%",    None, None, "PDW (ширина распределения тромбоцитов)"),
    ("RETIC","*","adult"):   RefRange(0.5,   1.5,   "%",    None, None, "Ретикулоциты"),
    ("EOS",  "*","adult"):   RefRange(0.02,  0.5,   "×10⁹/L", None, None, "Эозинофилы абс."),
    ("BASO", "*","adult"):   RefRange(0,     0.1,   "×10⁹/L", None, None, "Базофилы абс."),
    ("MONO", "*","adult"):   RefRange(0.2,   0.8,   "×10⁹/L", None, None, "Моноциты абс."),

    # ── Биохимия дополнительно ────────────────────────────────

    ("LDH",  "*","adult"):   RefRange(135,   225,   "U/L",  None, None, "ЛДГ (лактатдегидрогеназа)"),
    ("CK",   "M","adult"):   RefRange(38,    174,   "U/L",  None, None, "КФК общая"),
    ("CK",   "F","adult"):   RefRange(26,    140,   "U/L",  None, None, "КФК общая"),
    ("CK_MB","*","adult"):   RefRange(0,     25,    "U/L",  None, None, "КФК-МВ"),
    ("AMYL", "*","adult"):   RefRange(28,    100,   "U/L",  None, None, "Амилаза"),
    ("LIPASE","*","adult"):  RefRange(7,     60,    "U/L",  None, None, "Липаза"),
    ("CHOL_E","M","adult"):  RefRange(5000,  12000, "U/L",  None, None, "Холинэстераза"),
    ("CHOL_E","F","adult"):  RefRange(5000,  11000, "U/L",  None, None, "Холинэстераза"),
    ("IBIL", "*","adult"):   RefRange(3,     17,    "μmol/L", None, None, "Билирубин непрямой"),

    # ── Кардиомаркеры ─────────────────────────────────────────

    ("TROPI","*","adult"):   RefRange(0,     0.04,  "μg/L", None, None, "Тропонин I"),
    ("TROPT","*","adult"):   RefRange(0,     14,    "ng/L", None, None, "Тропонин T"),
    ("MYO",  "M","adult"):   RefRange(28,    72,    "μg/L", None, None, "Миоглобин"),
    ("MYO",  "F","adult"):   RefRange(25,    58,    "μg/L", None, None, "Миоглобин"),
    ("BNP",  "*","adult"):   RefRange(0,     100,   "pg/mL", None, None, "BNP (мозговой натрийуретический пептид)"),
    ("NTBNP","*","adult"):   RefRange(0,     125,   "pg/mL", None, None, "NT-proBNP"),

    # ── Минералы расширенные ──────────────────────────────────

    ("ZN",   "*","adult"):   RefRange(11,    22,    "μmol/L", None, None, "Цинк"),
    ("CU",   "M","adult"):   RefRange(11,    22,    "μmol/L", None, None, "Медь"),
    ("CU",   "F","adult"):   RefRange(12,    24,    "μmol/L", None, None, "Медь"),
    ("SE",   "*","adult"):   RefRange(0.89,  1.65,  "μmol/L", None, None, "Селен"),
    ("PHOS", "*","adult"):   RefRange(0.87,  1.45,  "mmol/L", None, None, "Фосфор"),
    ("PHOS", "*","child"):   RefRange(1.3,   2.1,   "mmol/L", None, None, "Фосфор (дети)"),
    ("MN",   "*","adult"):   RefRange(7.3,   10.9,  "nmol/L", None, None, "Марганец"),
    ("CR_MIN","*","adult"):  RefRange(0.5,   2.1,   "nmol/L", None, None, "Хром (минерал)"),

    # ── Метаболиты ────────────────────────────────────────────

    ("HCY",  "*","adult"):   RefRange(5,     15,    "μmol/L", None, None, "Гомоцистеин"),
    ("LACT", "*","adult"):   RefRange(0.5,   2.2,   "mmol/L", 0.1, 8.0, "Лактат"),
    ("NH3",  "*","adult"):   RefRange(11,    51,    "μmol/L", None, 100, "Аммоний"),
    ("PYRUVAT","*","adult"): RefRange(0.04,  0.14,  "mmol/L", None, None, "Пируват"),
    ("GFRGB","*","adult"):   RefRange(60,    200,   "mL/min/1.73m²", None, None, "СКФ (рассч. по CKD-EPI)"),

    # ── Витамины расширенные ──────────────────────────────────

    ("VB1",  "*","adult"):   RefRange(74,    222,   "nmol/L", None, None, "Витамин B1 (Тиамин)"),
    ("VB2",  "*","adult"):   RefRange(106,   638,   "nmol/L", None, None, "Витамин B2 (Рибофлавин)"),
    ("VB6",  "*","adult"):   RefRange(20,    125,   "nmol/L", None, None, "Витамин B6 (Пиридоксаль-фосфат)"),
    ("VA",   "*","adult"):   RefRange(0.9,   3.4,   "μmol/L", None, None, "Витамин A (Ретинол)"),
    ("VE",   "*","adult"):   RefRange(11.6,  46.4,  "μmol/L", None, None, "Витамин E (Токоферол)"),
    ("VC",   "*","adult"):   RefRange(23,    114,   "μmol/L", None, None, "Витамин C (Аскорбиновая к-та)"),
    ("VK",   "*","adult"):   RefRange(0.29,  2.64,  "nmol/L", None, None, "Витамин K1"),
    ("VB3",  "*","adult"):   RefRange(30,    85,    "nmol/mL", None, None, "Витамин B3 (Никотиновая к-та)"),
    ("VB7",  "*","adult"):   RefRange(133,   329,   "pmol/L", None, None, "Витамин B7 (Биотин)"),

    # ── Гормоны расширенные ───────────────────────────────────

    ("SHBG", "M","adult"):   RefRange(13,    71,    "nmol/L", None, None, "ГСПГ"),
    ("SHBG", "F","adult"):   RefRange(28,    122,   "nmol/L", None, None, "ГСПГ"),
    ("AMH",  "F","adult"):   RefRange(0.9,   9.5,   "pmol/L", None, None, "АМГ (антимюллеров гормон)"),
    ("PRL",  "M","adult"):   RefRange(0,     360,   "mIU/L",  None, None, "Пролактин"),
    ("PRL",  "F","adult"):   RefRange(60,    530,   "mIU/L",  None, None, "Пролактин"),
    ("PTH",  "*","adult"):   RefRange(1.6,   6.9,   "pmol/L", None, None, "Паратгормон (ПТГ)"),
    ("IGF1", "*","adult"):   RefRange(115,   307,   "μg/L",   None, None, "ИФР-1 (соматомедин-C)"),
    ("ACTH", "*","adult"):   RefRange(1.1,   13.3,  "pmol/L", None, None, "АКТГ (утро)"),
    ("ALD",  "*","adult"):   RefRange(30,    170,   "pmol/L", None, None, "Альдостерон"),
    ("RENIN","*","adult"):   RefRange(3,     29,    "mU/L",   None, None, "Ренин (стоя)"),
    ("FTEST","M","adult"):   RefRange(174,   729,   "pmol/L", None, None, "Тестостерон свободный"),
    ("FTEST","F","adult"):   RefRange(0.29,  3.67,  "pmol/L", None, None, "Тестостерон свободный"),
    ("CALCI","*","adult"):   RefRange(0,     9.5,   "pg/mL",  None, None, "Кальцитонин"),
    ("GH",   "*","adult"):   RefRange(0,     7,     "mIU/L",  None, None, "Гормон роста (ГР)"),
    ("FSH",  "F","elder"):   RefRange(25,    135,   "IU/L",   None, None, "ФСГ (постменопауза)"),
    ("LH",   "F","elder"):   RefRange(7.7,   58.5,  "IU/L",   None, None, "ЛГ (постменопауза)"),
    ("TEST", "M","elder"):   RefRange(6.0,   24.0,  "nmol/L", None, None, "Тестостерон (пожилые М)"),
    ("DHEAS","M","adult"):   RefRange(2.2,   15.2,  "μmol/L", None, None, "ДГЭА-С (мужчины)"),
    ("DHEAS","F","adult"):   RefRange(0.7,   11.0,  "μmol/L", None, None, "ДГЭА-С (женщины)"),
    ("ANDROST","M","adult"): RefRange(1.7,   8.8,   "nmol/L", None, None, "Андростендион"),
    ("ANDROST","F","adult"): RefRange(1.0,   11.5,  "nmol/L", None, None, "Андростендион"),
    ("CORT24","*","adult"):  RefRange(28,    280,   "nmol/day", None, None, "Кортизол (суточная моча)"),

    # ── Антитела расширенные ──────────────────────────────────

    ("ATTG", "*","adult"):   RefRange(0,     115,   "IU/mL",  None, None, "Антитела к тиреоглобулину (АТ-ТГ)"),
    ("TSI",  "*","adult"):   RefRange(0,     1.75,  "IU/L",   None, None, "Тиреостимулирующие иммуноглобулины (ТСИ)"),
    ("ANA",  "*","adult"):   RefRange(0,     0,     "titer <1:80", None, None, "АНА (антинуклеарные антитела)"),
    ("ANTIDSDNA","*","adult"): RefRange(0,   25,    "IU/mL",  None, None, "Антитела к дс-ДНК"),
    ("ANCA", "*","adult"):   RefRange(0,     0,     "негат.",  None, None, "АНЦА (p-ANCA, c-ANCA)"),
    ("ANTICL","*","adult"):  RefRange(0,     15,    "GPL-U/mL", None, None, "Антикардиолипиновые IgG"),
    ("ANTI_B2GP","*","adult"): RefRange(0,   10,    "U/mL",   None, None, "Антитела к β2-гликопротеину I"),
    ("RF",   "*","adult"):   RefRange(0,     14,    "IU/mL",  None, None, "Ревматоидный фактор (РФ)"),
    ("ASLO", "*","adult"):   RefRange(0,     200,   "IU/mL",  None, None, "АСЛО"),
    ("CCP",  "*","adult"):   RefRange(0,     7,     "U/mL",   None, None, "Антитела к ЦЦП (анти-ЦЦП)"),

    # ── Иммунология ───────────────────────────────────────────

    ("IGA",  "*","adult"):   RefRange(0.7,   4.0,   "g/L",    None, None, "Иммуноглобулин A"),
    ("IGG",  "*","adult"):   RefRange(7.0,   16.0,  "g/L",    None, None, "Иммуноглобулин G"),
    ("IGM",  "M","adult"):   RefRange(0.4,   2.3,   "g/L",    None, None, "Иммуноглобулин M"),
    ("IGM",  "F","adult"):   RefRange(0.5,   2.7,   "g/L",    None, None, "Иммуноглобулин M"),
    ("IGE",  "*","adult"):   RefRange(0,     100,   "IU/mL",  None, None, "Иммуноглобулин E (общий)"),
    ("C3",   "*","adult"):   RefRange(0.9,   1.8,   "g/L",    None, None, "Комплемент C3"),
    ("C4",   "*","adult"):   RefRange(0.1,   0.4,   "g/L",    None, None, "Комплемент C4"),
    ("B2M",  "*","adult"):   RefRange(1.1,   2.4,   "mg/L",   None, None, "β2-микроглобулин"),

    # ── Онкомаркеры ───────────────────────────────────────────

    ("PSA",  "M","adult"):   RefRange(0,     4.0,   "ng/mL",  None, None, "ПСА (общий)"),
    ("PSA_F","M","adult"):   RefRange(0,     1.0,   "ng/mL",  None, None, "ПСА свободный"),
    ("CA125","F","adult"):   RefRange(0,     35,    "U/mL",   None, None, "CA 125"),
    ("CA199","*","adult"):   RefRange(0,     37,    "U/mL",   None, None, "CA 19-9"),
    ("CA153","F","adult"):   RefRange(0,     31.3,  "U/mL",   None, None, "CA 15-3"),
    ("AFP",  "*","adult"):   RefRange(0,     8.1,   "ng/mL",  None, None, "АФП (альфа-фетопротеин)"),
    ("CEA",  "*","adult"):   RefRange(0,     3.0,   "ng/mL",  None, None, "РЭА (раково-эмбриональный антиген)"),
    ("CA72_4","*","adult"):  RefRange(0,     6.9,   "U/mL",   None, None, "CA 72-4"),
    ("NSE",  "*","adult"):   RefRange(0,     16.3,  "μg/L",   None, None, "НСЕ (нейрон-специфическая энолаза)"),
    ("PROGRP","*","adult"):  RefRange(0,     63,    "pg/mL",  None, None, "ProGRP (маркер МРЛ)"),

    # ── Гемостаз расширенный ──────────────────────────────────

    ("TT",   "*","adult"):   RefRange(14,    21,    "sec",    None, None, "Тромбиновое время (ТВ)"),
    ("ANTITHR","*","adult"): RefRange(80,    120,   "%",      None, None, "Антитромбин III"),
    ("PROT_C","*","adult"):  RefRange(70,    140,   "%",      None, None, "Протеин C"),
    ("PROT_S","*","adult"):  RefRange(65,    140,   "%",      None, None, "Протеин S"),
    ("PAI1", "*","adult"):   RefRange(0,     50,    "ng/mL",  None, None, "PAI-1 (ингибитор активатора плазминогена)"),

    # ── Моча расширенная ──────────────────────────────────────

    ("UALB", "*","adult"):   RefRange(0,     30,    "mg/day", None, None, "Микроальбуминурия (суточная)"),
    ("MALB_CR","*","adult"): RefRange(0,     3.4,   "mg/mmol", None, None, "Альбумин/Креатинин (разовая)"),
    ("UUREA","*","adult"):   RefRange(250,   600,   "mmol/day", None, None, "Мочевина в моче (суточная)"),
    ("UCREA","*","adult"):   RefRange(7.1,   17.7,  "mmol/day", None, None, "Креатинин в моче (суточная)"),
    ("UNA",  "*","adult"):   RefRange(100,   260,   "mmol/day", None, None, "Натрий в моче (суточная)"),
    ("UK",   "*","adult"):   RefRange(25,    125,   "mmol/day", None, None, "Калий в моче (суточная)"),
    ("UCA",  "*","adult"):   RefRange(2.5,   7.5,   "mmol/day", None, None, "Кальций в моче (суточная)"),

    # ── Специальные биомаркеры ────────────────────────────────

    ("APOB", "*","adult"):   RefRange(0.6,   1.2,   "g/L",    None, None, "Апо-В (аполипопротеин В)"),
    ("APOA1","M","adult"):   RefRange(1.04,  2.02,  "g/L",    None, None, "Апо-А1"),
    ("APOA1","F","adult"):   RefRange(1.08,  2.25,  "g/L",    None, None, "Апо-А1"),
    ("LPA",  "*","adult"):   RefRange(0,     30,    "mg/dL",  None, None, "Лп(а) (липопротеин(а))"),
    ("OXLDL","*","adult"):   RefRange(0,     60,    "U/L",    None, None, "Окисленный ЛПНП"),
    ("IL6",  "*","adult"):   RefRange(0,     7,     "pg/mL",  None, None, "ИЛ-6 (интерлейкин-6)"),
    ("TNF",  "*","adult"):   RefRange(0,     8.1,   "pg/mL",  None, None, "ФНО-α"),
    ("HSCRP","*","adult"):   RefRange(0,     1.0,   "mg/L",   None, None, "вч-СРБ (высокочувствительный)"),
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
    # ── Народные и краткие сокращения (RU) ───────────────────
    "ггц": "GGT", "гамма-гт": "GGT", "гамма гт": "GGT",
    "холес": "CHOL", "хол": "CHOL",
    "сах": "GLU", "глюк": "GLU",
    "лдг": "LDH", "лактатдегидрогеназа": "LDH",
    "кфк": "CK", "кк": "CK", "креатинкиназа": "CK",
    "кфк-мб": "CK_MB", "кфк мб": "CK_MB",
    "амилаза": "AMYL",
    "липаза": "LIPASE",
    "холинэстераза": "CHOL_E",
    "тропонин i": "TROPI", "тропонин т": "TROPT",
    "тропонин": "TROPI",
    "миоглобин": "MYO",
    "мозговой натрийуретический": "BNP",
    "bnp": "BNP", "nt-probnp": "NTBNP", "нт-пробнп": "NTBNP",
    "цинк": "ZN", "zn": "ZN",
    "медь": "CU", "cu": "CU",
    "селен": "SE", "se": "SE",
    "фосфор": "PHOS", "фосфаты": "PHOS",
    "гомоцистеин": "HCY", "hcy": "HCY",
    "лактат": "LACT", "молочная кислота": "LACT",
    "аммоний": "NH3", "аммиак": "NH3",
    "пируват": "PYRUVAT",
    "скф": "GFRGB", "gfr": "GFRGB", "сгф": "GFRGB",
    "b1": "VB1", "тиамин": "VB1",
    "b2": "VB2", "рибофлавин": "VB2",
    "b6": "VB6", "пиридоксин": "VB6",
    "витамин a": "VA", "ретинол": "VA",
    "витамин e": "VE", "токоферол": "VE",
    "витамин c": "VC", "аскорбиновая кислота": "VC", "аскорбат": "VC",
    "витамин k": "VK",
    "b3": "VB3", "никотиновая кислота": "VB3", "ниацин": "VB3",
    "биотин": "VB7", "b7": "VB7",
    "гспг": "SHBG", "shbg": "SHBG", "глобулин связывающий половые гормоны": "SHBG",
    "амг": "AMH", "амh": "AMH", "антимюллеров гормон": "AMH",
    "пролактин": "PRL", "prolactin": "PRL",
    "паратгормон": "PTH", "птг": "PTH", "pth": "PTH",
    "ифр-1": "IGF1", "igf1": "IGF1", "соматомедин": "IGF1",
    "актг": "ACTH", "acth": "ACTH",
    "альдостерон": "ALD",
    "ренин": "RENIN",
    "тестостерон свободный": "FTEST", "своб. тест": "FTEST",
    "кальцитонин": "CALCI",
    "гормон роста": "GH", "gr": "GH", "соматотропин": "GH",
    "ат-тг": "ATTG", "антитела к тиреоглобулину": "ATTG", "attg": "ATTG",
    "тси": "TSI", "tsi": "TSI",
    "ана": "ANA", "ana": "ANA", "антинуклеарные антитела": "ANA",
    "анти-дсднк": "ANTIDSDNA", "антитела к дсднк": "ANTIDSDNA",
    "анца": "ANCA", "anca": "ANCA",
    "антикардиолипин": "ANTICL", "aCl": "ANTICL",
    "β2-гп": "ANTI_B2GP",
    "ревматоидный фактор": "RF", "рф": "RF", "rf": "RF",
    "асло": "ASLO", "aslo": "ASLO",
    "анти-ццп": "CCP", "anti-ccp": "CCP", "ццп": "CCP",
    "иммуноглобулин a": "IGA", "iga": "IGA",
    "иммуноглобулин g": "IGG", "igg": "IGG",
    "иммуноглобулин m": "IGM", "igm": "IGM",
    "иммуноглобулин e": "IGE", "ige": "IGE", "иммуноглобулин е": "IGE",
    "комплемент c3": "C3", "c3": "C3",
    "комплемент c4": "C4", "c4": "C4",
    "β2-микроглобулин": "B2M", "b2m": "B2M",
    "пса": "PSA", "psa": "PSA", "простатспецифический антиген": "PSA",
    "пса своб": "PSA_F", "пса свободный": "PSA_F",
    "са 125": "CA125", "ca125": "CA125", "ca-125": "CA125",
    "са 19-9": "CA199", "ca199": "CA199", "ca19-9": "CA199",
    "са 15-3": "CA153", "ca153": "CA153", "ca15-3": "CA153",
    "афп": "AFP", "afp": "AFP", "альфа-фетопротеин": "AFP",
    "рэа": "CEA", "cea": "CEA", "ркэа": "CEA",
    "нсе": "NSE", "nse": "NSE",
    "тромбиновое время": "TT", "тв": "TT",
    "антитромбин": "ANTITHR", "at iii": "ANTITHR", "атiii": "ANTITHR",
    "протеин c": "PROT_C", "протеин с": "PROT_C",
    "протеин s": "PROT_S",
    "апо-в": "APOB", "apob": "APOB", "аполипопротеин в": "APOB",
    "апо-а1": "APOA1", "apoa1": "APOA1",
    "лп(а)": "LPA", "lp(a)": "LPA", "липопротеин а": "LPA",
    "микроальбуминурия": "UALB",
    "ил-6": "IL6", "il-6": "IL6", "интерлейкин-6": "IL6",
    "фнф-α": "TNF", "tnf": "TNF",
    "вч-срб": "HSCRP", "hscrp": "HSCRP", "высокочувствительный срб": "HSCRP",
    "вчсрб": "HSCRP",
    "rdw": "RDW", "ширина распределения": "RDW",
    "mpv": "MPV", "средний объём тромбоцита": "MPV",
    "ретикулоциты": "RETIC",

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
    "ჰომოცისტეინი": "HCY",
    "ვიტამინი c": "VC",
    "ვიტამინი e": "VE",
    "ვიტამინი a": "VA",
    "ფარათჰორმონი": "PTH",
    "პროლაქტინი": "PRL",
    "თეროიდული სტიმულ. იმ.": "TSI",
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
    """
    Get reference range with priority:
    1. Exact match (sex, age_group)
    2. Any sex for this age_group  — age takes priority for children/elders
    3. This sex for adult
    4. Any sex for adult
    5. Wildcard
    """
    candidates = [
        (param_id, sex,  age_group),
        (param_id, "*",  age_group),
        (param_id, sex,  "adult"),
        (param_id, "*",  "adult"),
        (param_id, sex,  "*"),
        (param_id, "*",  "*"),
    ]
    for key in candidates:
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
