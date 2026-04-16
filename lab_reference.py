"""
AIM v7.0 — Lab Reference Ranges
База лабораторных норм. Единицы — SI (mmol/L, g/L и т.д.) если не указано иначе.
Структура: {analyte: {unit, low, high, critical_low, critical_high, notes}}
"""

from typing import Optional

# ── Полная база норм ──────────────────────────────────────────────────────────

LAB_RANGES: dict[str, dict] = {

    # ── Общий анализ крови ────────────────────────────────────────────────────
    "hemoglobin_m": {
        "display": "Гемоглобин (муж)", "unit": "g/L",
        "low": 130, "high": 175, "critical_low": 70, "critical_high": 200,
        "category": "CBC",
    },
    "hemoglobin_f": {
        "display": "Гемоглобин (жен)", "unit": "g/L",
        "low": 120, "high": 160, "critical_low": 70, "critical_high": 200,
        "category": "CBC",
    },
    "hematocrit_m": {
        "display": "Гематокрит (муж)", "unit": "%",
        "low": 40, "high": 52, "critical_low": 20, "critical_high": 60,
        "category": "CBC",
    },
    "hematocrit_f": {
        "display": "Гематокрит (жен)", "unit": "%",
        "low": 36, "high": 47, "critical_low": 20, "critical_high": 60,
        "category": "CBC",
    },
    "rbc_m": {
        "display": "Эритроциты (муж)", "unit": "×10¹²/L",
        "low": 4.5, "high": 5.9, "critical_low": 2.0, "critical_high": 7.0,
        "category": "CBC",
    },
    "rbc_f": {
        "display": "Эритроциты (жен)", "unit": "×10¹²/L",
        "low": 3.8, "high": 5.2, "critical_low": 2.0, "critical_high": 7.0,
        "category": "CBC",
    },
    "wbc": {
        "display": "Лейкоциты", "unit": "×10⁹/L",
        "low": 4.0, "high": 11.0, "critical_low": 2.0, "critical_high": 30.0,
        "category": "CBC",
    },
    "platelets": {
        "display": "Тромбоциты", "unit": "×10⁹/L",
        "low": 150, "high": 400, "critical_low": 50, "critical_high": 1000,
        "category": "CBC",
    },
    "mcv": {
        "display": "MCV (ср. объём эр.)", "unit": "fL",
        "low": 80, "high": 100, "critical_low": None, "critical_high": None,
        "category": "CBC",
    },
    "mch": {
        "display": "MCH (ср. Hb в эр.)", "unit": "pg",
        "low": 27, "high": 33, "critical_low": None, "critical_high": None,
        "category": "CBC",
    },
    "mchc": {
        "display": "MCHC", "unit": "g/L",
        "low": 320, "high": 360, "critical_low": None, "critical_high": None,
        "category": "CBC",
    },
    "esr": {
        "display": "СОЭ", "unit": "mm/h",
        "low": 1, "high": 20, "critical_low": None, "critical_high": 100,
        "category": "CBC",
        "notes": "до 15 мм/ч у мужчин, до 20 мм/ч у женщин",
    },
    "neutrophils": {
        "display": "Нейтрофилы", "unit": "%",
        "low": 48, "high": 78, "critical_low": 20, "critical_high": 90,
        "category": "Лейкоформула",
    },
    "lymphocytes": {
        "display": "Лимфоциты", "unit": "%",
        "low": 19, "high": 37, "critical_low": 10, "critical_high": 60,
        "category": "Лейкоформула",
    },
    "monocytes": {
        "display": "Моноциты", "unit": "%",
        "low": 3, "high": 11, "critical_low": None, "critical_high": 20,
        "category": "Лейкоформула",
    },
    "eosinophils": {
        "display": "Эозинофилы", "unit": "%",
        "low": 1, "high": 5, "critical_low": None, "critical_high": 20,
        "category": "Лейкоформула",
    },
    "basophils": {
        "display": "Базофилы", "unit": "%",
        "low": 0, "high": 1, "critical_low": None, "critical_high": None,
        "category": "Лейкоформула",
    },

    # ── Биохимия ─────────────────────────────────────────────────────────────
    "glucose": {
        "display": "Глюкоза (натощак)", "unit": "mmol/L",
        "low": 3.9, "high": 5.6, "critical_low": 2.5, "critical_high": 22.0,
        "category": "Биохимия",
    },
    "hba1c": {
        "display": "HbA1c", "unit": "%",
        "low": None, "high": 5.7, "critical_low": None, "critical_high": 14.0,
        "category": "Биохимия",
        "notes": "5.7–6.4% предиабет; ≥6.5% диабет",
    },
    "insulin": {
        "display": "Инсулин", "unit": "мкЕд/мл",
        "low": 2.6, "high": 24.9, "critical_low": None, "critical_high": None,
        "category": "Биохимия",
    },
    "homa_ir": {
        "display": "HOMA-IR", "unit": "усл. ед.",
        "low": None, "high": 2.7, "critical_low": None, "critical_high": None,
        "category": "Биохимия",
        "notes": ">2.7 — инсулинорезистентность; вычисляется: глюкоза(ммоль/л)×инсулин(мкЕд/мл)/22.5",
    },
    "total_cholesterol": {
        "display": "Холестерин общий", "unit": "mmol/L",
        "low": None, "high": 5.2, "critical_low": None, "critical_high": 10.0,
        "category": "Липидограмма",
        "notes": "желательно <5.2; пограничный 5.2–6.2; высокий >6.2",
    },
    "ldl": {
        "display": "ЛПНП", "unit": "mmol/L",
        "low": None, "high": 3.4, "critical_low": None, "critical_high": 8.0,
        "category": "Липидограмма",
        "notes": "<2.6 оптимально; 2.6–3.4 нормально; >3.4 высокий",
    },
    "hdl_m": {
        "display": "ЛПВП (муж)", "unit": "mmol/L",
        "low": 1.0, "high": None, "critical_low": 0.5, "critical_high": None,
        "category": "Липидограмма",
    },
    "hdl_f": {
        "display": "ЛПВП (жен)", "unit": "mmol/L",
        "low": 1.3, "high": None, "critical_low": 0.5, "critical_high": None,
        "category": "Липидограмма",
    },
    "triglycerides": {
        "display": "Триглицериды", "unit": "mmol/L",
        "low": None, "high": 1.7, "critical_low": None, "critical_high": 11.3,
        "category": "Липидограмма",
        "notes": "1.7–2.3 пограничный; >2.3 высокий",
    },

    # ── Функция почек ─────────────────────────────────────────────────────────
    "creatinine_m": {
        "display": "Креатинин (муж)", "unit": "μmol/L",
        "low": 62, "high": 115, "critical_low": None, "critical_high": 600,
        "category": "Почки",
    },
    "creatinine_f": {
        "display": "Креатинин (жен)", "unit": "μmol/L",
        "low": 44, "high": 97, "critical_low": None, "critical_high": 600,
        "category": "Почки",
    },
    "urea": {
        "display": "Мочевина", "unit": "mmol/L",
        "low": 2.8, "high": 7.2, "critical_low": None, "critical_high": 35.0,
        "category": "Почки",
    },
    "uric_acid_m": {
        "display": "Мочевая кислота (муж)", "unit": "μmol/L",
        "low": 200, "high": 430, "critical_low": None, "critical_high": 700,
        "category": "Почки",
    },
    "uric_acid_f": {
        "display": "Мочевая кислота (жен)", "unit": "μmol/L",
        "low": 140, "high": 360, "critical_low": None, "critical_high": 700,
        "category": "Почки",
    },
    "egfr": {
        "display": "рСКФ (CKD-EPI)", "unit": "мл/мин/1.73м²",
        "low": 90, "high": None, "critical_low": 15, "critical_high": None,
        "category": "Почки",
        "notes": "60–89 мл/мин — умеренное снижение; <60 — ХБП",
    },

    # ── Функция печени ────────────────────────────────────────────────────────
    "alt": {
        "display": "АЛТ", "unit": "U/L",
        "low": None, "high": 40, "critical_low": None, "critical_high": 1000,
        "category": "Печень",
        "notes": ">56 U/L — патология; у женщин верхняя граница 35 U/L",
    },
    "ast": {
        "display": "АСТ", "unit": "U/L",
        "low": None, "high": 40, "critical_low": None, "critical_high": 1000,
        "category": "Печень",
    },
    "ggt": {
        "display": "ГГТ", "unit": "U/L",
        "low": None, "high": 55, "critical_low": None, "critical_high": None,
        "category": "Печень",
        "notes": "у женщин: <38 U/L",
    },
    "alp": {
        "display": "Щелочная фосфатаза", "unit": "U/L",
        "low": 44, "high": 147, "critical_low": None, "critical_high": 500,
        "category": "Печень",
    },
    "bilirubin_total": {
        "display": "Билирубин общий", "unit": "μmol/L",
        "low": 3.4, "high": 20.5, "critical_low": None, "critical_high": 200,
        "category": "Печень",
    },
    "bilirubin_direct": {
        "display": "Билирубин прямой", "unit": "μmol/L",
        "low": None, "high": 5.1, "critical_low": None, "critical_high": None,
        "category": "Печень",
    },
    "albumin": {
        "display": "Альбумин", "unit": "g/L",
        "low": 35, "high": 50, "critical_low": 20, "critical_high": None,
        "category": "Печень",
    },
    "total_protein": {
        "display": "Белок общий", "unit": "g/L",
        "low": 64, "high": 83, "critical_low": 40, "critical_high": None,
        "category": "Печень",
    },

    # ── Щитовидная железа ─────────────────────────────────────────────────────
    "tsh": {
        "display": "ТТГ", "unit": "мМЕ/л",
        "low": 0.4, "high": 4.0, "critical_low": 0.01, "critical_high": 100,
        "category": "Щитовидная железа",
        "notes": "оптимум для функции: 1.0–2.5 мМЕ/л",
    },
    "ft4": {
        "display": "T4 свободный", "unit": "pmol/L",
        "low": 9.0, "high": 25.0, "critical_low": 5.0, "critical_high": None,
        "category": "Щитовидная железа",
    },
    "ft3": {
        "display": "T3 свободный", "unit": "pmol/L",
        "low": 2.6, "high": 5.7, "critical_low": None, "critical_high": None,
        "category": "Щитовидная железа",
    },
    "anti_tpo": {
        "display": "Антитела к ТПО", "unit": "МЕ/мл",
        "low": None, "high": 34, "critical_low": None, "critical_high": None,
        "category": "Щитовидная железа",
    },

    # ── Витамины и минералы ───────────────────────────────────────────────────
    "vitamin_d": {
        "display": "Витамин D (25-OH)", "unit": "nmol/L",
        "low": 75, "high": 250, "critical_low": 25, "critical_high": 500,
        "category": "Витамины",
        "notes": "дефицит <50; недостаточность 50–75; оптимум 100–200",
    },
    "vitamin_b12": {
        "display": "Витамин B12", "unit": "pmol/L",
        "low": 148, "high": 740, "critical_low": 74, "critical_high": None,
        "category": "Витамины",
    },
    "folate": {
        "display": "Фолат (сывороточный)", "unit": "nmol/L",
        "low": 7.0, "high": 45.0, "critical_low": 3.0, "critical_high": None,
        "category": "Витамины",
    },
    "iron": {
        "display": "Железо", "unit": "μmol/L",
        "low": 9.0, "high": 30.0, "critical_low": 3.0, "critical_high": None,
        "category": "Витамины",
    },
    "ferritin_m": {
        "display": "Ферритин (муж)", "unit": "ng/mL",
        "low": 30, "high": 400, "critical_low": 10, "critical_high": None,
        "category": "Витамины",
    },
    "ferritin_f": {
        "display": "Ферритин (жен)", "unit": "ng/mL",
        "low": 15, "high": 200, "critical_low": 7, "critical_high": None,
        "category": "Витамины",
    },
    "tibc": {
        "display": "ОЖСС", "unit": "μmol/L",
        "low": 45, "high": 75, "critical_low": None, "critical_high": None,
        "category": "Витамины",
    },
    "magnesium": {
        "display": "Магний", "unit": "mmol/L",
        "low": 0.74, "high": 1.03, "critical_low": 0.5, "critical_high": 2.0,
        "category": "Электролиты",
    },
    "calcium_total": {
        "display": "Кальций общий", "unit": "mmol/L",
        "low": 2.10, "high": 2.60, "critical_low": 1.75, "critical_high": 3.5,
        "category": "Электролиты",
    },
    "potassium": {
        "display": "Калий", "unit": "mmol/L",
        "low": 3.5, "high": 5.1, "critical_low": 2.5, "critical_high": 6.5,
        "category": "Электролиты",
    },
    "sodium": {
        "display": "Натрий", "unit": "mmol/L",
        "low": 136, "high": 145, "critical_low": 120, "critical_high": 160,
        "category": "Электролиты",
    },
    "phosphorus": {
        "display": "Фосфор", "unit": "mmol/L",
        "low": 0.87, "high": 1.45, "critical_low": None, "critical_high": None,
        "category": "Электролиты",
    },

    # ── Гормоны ───────────────────────────────────────────────────────────────
    "cortisol_am": {
        "display": "Кортизол (утро)", "unit": "nmol/L",
        "low": 138, "high": 635, "critical_low": 50, "critical_high": 2000,
        "category": "Гормоны",
    },
    "dhea_s_m": {
        "display": "ДГЭА-С (муж)", "unit": "μmol/L",
        "low": 2.2, "high": 15.2, "critical_low": None, "critical_high": None,
        "category": "Гормоны",
    },
    "dhea_s_f": {
        "display": "ДГЭА-С (жен)", "unit": "μmol/L",
        "low": 1.6, "high": 12.2, "critical_low": None, "critical_high": None,
        "category": "Гормоны",
    },
    "testosterone_m": {
        "display": "Тестостерон (муж)", "unit": "nmol/L",
        "low": 9.9, "high": 27.8, "critical_low": None, "critical_high": None,
        "category": "Гормоны",
    },
    "testosterone_f": {
        "display": "Тестостерон (жен)", "unit": "nmol/L",
        "low": 0.22, "high": 2.9, "critical_low": None, "critical_high": None,
        "category": "Гормоны",
    },
    "igf1": {
        "display": "ИФР-1 (IGF-1)", "unit": "ng/mL",
        "low": None, "high": None, "critical_low": None, "critical_high": None,
        "category": "Гормоны",
        "notes": "норма зависит от возраста; для 40 лет: 102–280 ng/mL",
    },
    "insulin_like_growth": {
        "display": "ИФР-1 (40 лет)", "unit": "ng/mL",
        "low": 102, "high": 280, "critical_low": None, "critical_high": None,
        "category": "Гормоны",
    },

    # ── Воспаление / иммунитет ────────────────────────────────────────────────
    "crp": {
        "display": "СРБ (высокочувствительный)", "unit": "mg/L",
        "low": None, "high": 3.0, "critical_low": None, "critical_high": 200,
        "category": "Воспаление",
        "notes": "<1.0 низкий риск ССЗ; 1–3 умеренный; >3 высокий риск",
    },
    "esr_westergren": {
        "display": "СОЭ (Вестергрен)", "unit": "mm/h",
        "low": None, "high": 20, "critical_low": None, "critical_high": 100,
        "category": "Воспаление",
        "notes": "муж: <15; жен: <20; пожилые: муж <20, жен <30",
    },
    "fibrinogen": {
        "display": "Фибриноген", "unit": "g/L",
        "low": 2.0, "high": 4.0, "critical_low": 1.0, "critical_high": 10.0,
        "category": "Воспаление",
    },
    "il6": {
        "display": "ИЛ-6", "unit": "pg/mL",
        "low": None, "high": 7.0, "critical_low": None, "critical_high": None,
        "category": "Воспаление",
    },
    "homocysteine": {
        "display": "Гомоцистеин", "unit": "μmol/L",
        "low": None, "high": 15.0, "critical_low": None, "critical_high": None,
        "category": "Воспаление",
        "notes": "оптимум <10; 15–30 умеренная гипергомоцистеинемия",
    },

    # ── Коагулограмма ─────────────────────────────────────────────────────────
    "pt_inr": {
        "display": "МНО (INR)", "unit": "ед.",
        "low": 0.8, "high": 1.2, "critical_low": None, "critical_high": None,
        "category": "Коагуляция",
        "notes": "терапевтический диапазон при варфарине: 2.0–3.0",
    },
    "aptt": {
        "display": "АЧТВ", "unit": "сек",
        "low": 25, "high": 37, "critical_low": None, "critical_high": 100,
        "category": "Коагуляция",
    },
    "d_dimer": {
        "display": "Д-димер", "unit": "мкг/мл FEU",
        "low": None, "high": 0.5, "critical_low": None, "critical_high": None,
        "category": "Коагуляция",
    },
}

# ── Вспомогательные функции ───────────────────────────────────────────────────

def evaluate(analyte: str, value: float) -> dict:
    """
    Оценить значение аналита.
    Возвращает: status (normal/low/high/critical_low/critical_high/unknown),
                reference (строка норм), display, unit, notes
    """
    if analyte not in LAB_RANGES:
        return {"status": "unknown", "analyte": analyte, "value": value}

    ref = LAB_RANGES[analyte]
    low  = ref.get("low")
    high = ref.get("high")
    crit_low  = ref.get("critical_low")
    crit_high = ref.get("critical_high")

    status = "normal"
    if crit_low is not None and value < crit_low:
        status = "critical_low"
    elif crit_high is not None and value > crit_high:
        status = "critical_high"
    elif low is not None and value < low:
        status = "low"
    elif high is not None and value > high:
        status = "high"

    # Строка референсного диапазона
    parts = []
    if low is not None:
        parts.append(f"{low}")
    if high is not None:
        parts.append(f"{high}")
    ref_str = "–".join(parts) if parts else "—"

    return {
        "analyte": analyte,
        "display": ref.get("display", analyte),
        "value": value,
        "unit": ref.get("unit", ""),
        "status": status,
        "reference": ref_str,
        "category": ref.get("category", ""),
        "notes": ref.get("notes", ""),
    }


def format_result(result: dict, lang: str = "ru") -> str:
    """Форматировать результат для вывода."""
    status_labels = {
        "ru": {
            "normal": "норма ✅",
            "low": "ниже нормы ↓",
            "high": "выше нормы ↑",
            "critical_low": "КРИТИЧЕСКИ НИЗКО ⚠️",
            "critical_high": "КРИТИЧЕСКИ ВЫСОКО ⚠️",
            "unknown": "неизвестный аналит",
        },
        "en": {
            "normal": "normal ✅",
            "low": "below normal ↓",
            "high": "above normal ↑",
            "critical_low": "CRITICALLY LOW ⚠️",
            "critical_high": "CRITICALLY HIGH ⚠️",
            "unknown": "unknown analyte",
        },
    }
    labels = status_labels.get(lang, status_labels["ru"])
    status_str = labels.get(result["status"], result["status"])

    lines = [
        f"**{result.get('display', result['analyte'])}**: "
        f"{result['value']} {result.get('unit','')} — {status_str}",
    ]
    ref = result.get("reference")
    if ref:
        unit = result.get("unit", "")
        lines.append(f"  Норма: {ref} {unit}")
    notes = result.get("notes")
    if notes:
        lines.append(f"  📌 {notes}")
    return "\n".join(lines)


def batch_evaluate(values: dict[str, float], lang: str = "ru") -> str:
    """
    Оценить набор аналитов.
    values: {"analyte_key": float_value, ...}
    Возвращает отформатированный отчёт.
    """
    results = []
    for analyte, value in values.items():
        r = evaluate(analyte, value)
        results.append((r.get("status", "unknown"), format_result(r, lang)))

    # Сортировка: критические → выше/ниже нормы → нормальные
    order = ["critical_high", "critical_low", "high", "low", "normal", "unknown"]
    results.sort(key=lambda x: order.index(x[0]) if x[0] in order else 99)

    return "\n\n".join(r[1] for r in results)


def list_analytes(category: Optional[str] = None) -> list[str]:
    """Список доступных аналитов (опционально — по категории)."""
    if category:
        return [k for k, v in LAB_RANGES.items() if v.get("category") == category]
    return list(LAB_RANGES.keys())


def categories() -> list[str]:
    """Список всех категорий."""
    return sorted(set(v.get("category", "") for v in LAB_RANGES.values()))


# ── Тесты ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Тест пакетной оценки
    test_values = {
        "glucose":          7.1,   # выше нормы
        "hemoglobin_m":     145,   # норма
        "vitamin_d":        35,    # дефицит (критически низко)
        "creatinine_m":     130,   # выше нормы
        "tsh":              0.2,   # ниже нормы
        "crp":              0.8,   # норма
        "hba1c":            6.1,   # выше нормы (предиабет)
        "potassium":        2.3,   # критически низко
    }
    print("=== Результаты анализов ===\n")
    print(batch_evaluate(test_values, lang="ru"))
    print("\n=== Категории ===")
    print(categories())
