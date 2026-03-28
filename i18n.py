"""
AIM v6.0 — i18n.py
Мультиязычные строки интерфейса. Источник истины для CLI и GUI.
Языки: RU (русский) / KA (грузинский) / EN (английский) / KZ (казахский)

Использование:
    from i18n import t, set_lang
    set_lang("ru")
    print(t("m1"))   # "Список пациентов"
    print(t("welcome"))
"""

import os
from typing import Dict, Optional
from config import cfg

# ============================================================================
# Текущий язык
# ============================================================================

_current_lang: str = cfg.DEFAULT_LANG


def set_lang(lang: str):
    """Установить язык интерфейса"""
    global _current_lang
    if lang in cfg.SUPPORTED_LANGS:
        _current_lang = lang
    else:
        raise ValueError(f"Неподдерживаемый язык: {lang}. Доступно: {cfg.SUPPORTED_LANGS}")


def get_lang() -> str:
    return _current_lang


def t(key: str, lang: str = None, **kwargs) -> str:
    """
    Получить строку по ключу.
    Если ключ не найден — возвращает ключ в скобках [key].

    Args:
        key:    Ключ строки
        lang:   Язык (если None — использует текущий)
        kwargs: Аргументы для форматирования (str.format(**kwargs))
    """
    lang = lang or _current_lang
    lang_dict = STRINGS.get(lang, STRINGS["ru"])
    result = lang_dict.get(key) or STRINGS["ru"].get(key) or f"[{key}]"
    if kwargs:
        try:
            result = result.format(**kwargs)
        except (KeyError, IndexError):
            pass
    return result


# ============================================================================
# Строки интерфейса
# ============================================================================
# Ключи меню: m1..m9, mw, mgui (дополнительные)
# Ключи системы: welcome, loading, error, success, ...
# ============================================================================

STRINGS: Dict[str, Dict[str, str]] = {

    # ========================================================================
    # РУССКИЙ
    # ========================================================================
    "ru": {
        # Главное меню
        "m1": "Список пациентов",
        "m2": "Новый пациент",
        "m3": "Поиск пациента",
        "m4": "AI-консультация",
        "m5": "Анализ лабораторных данных",
        "m6": "Байесовская диагностика",
        "m7": "Протоколы лечения",
        "m8": "Ze-статус / HRV",
        "m9": "Отчёты и экспорт",
        "mw": "Выход",
        "mgui": "Настройки",

        # Подменю пациента
        "mp1": "Просмотр данных пациента",
        "mp2": "Добавить анализ",
        "mp3": "AI-анализ анализов",
        "mp4": "История диагнозов",
        "mp5": "Назначения и рецепты",
        "mp6": "Записи на приём",
        "mp7": "Ze/HRV данные",
        "mpb": "Назад",

        # Системные
        "welcome": "Добро пожаловать в AIM v{version}",
        "loading": "Загрузка...",
        "processing": "Обработка...",
        "error": "Ошибка: {message}",
        "success": "Готово",
        "confirm": "Подтвердить? (д/н): ",
        "yes": "д",
        "no": "н",
        "back": "Назад",
        "exit": "Выход",
        "not_found": "Не найдено",
        "saved": "Сохранено",
        "cancelled": "Отменено",
        "choose_lang": "Выберите язык / Choose language / აირჩიეთ ენა / Тілді таңдаңыз:",

        # Пациенты
        "patients_title": "=== ПАЦИЕНТЫ ===",
        "patient_id": "ID",
        "patient_name": "Имя",
        "patient_age": "Возраст",
        "patient_sex": "Пол",
        "patient_ze": "Ze-статус",
        "patient_bio_age": "Биол. возраст",
        "no_patients": "Пациентов не найдено",
        "patient_created": "Пациент создан: {name}",
        "search_prompt": "Введите имя или фамилию для поиска: ",

        # AI
        "ai_thinking": "AI анализирует...",
        "ai_title": "=== AI-КОНСУЛЬТАЦИЯ ===",
        "ai_prompt": "Ваш вопрос (или Enter для выхода): ",
        "ai_no_key": "DeepSeek API недоступен. Проверьте ~/.aim_env",

        # Анализы
        "lab_title": "=== ЛАБОРАТОРНЫЕ ДАННЫЕ ===",
        "lab_input": "Введите или вставьте данные анализов: ",
        "lab_analyzing": "Анализ лабораторных данных...",
        "lab_no_data": "Лабораторных данных не найдено",

        # Ze/HRV
        "ze_title": "=== Ze-СТАТУС / HRV ===",
        "ze_status_label": "Ze-статус",
        "ze_high": "Высокий — отличный биологический резерв",
        "ze_medium": "Средний — умеренный резерв, профилактика",
        "ze_low": "Низкий — сниженный резерв, активное лечение",
        "ze_critical": "Критический — минимальный резерв",

        # Диагностика
        "diag_title": "=== ДИФФЕРЕНЦИАЛЬНАЯ ДИАГНОСТИКА ===",
        "diag_symptoms": "Введите симптомы (через запятую): ",
        "diag_running": "Байесовский анализ...",

        # Протоколы
        "treatment_title": "=== ПРОТОКОЛЫ ЛЕЧЕНИЯ ===",

        # Отчёты
        "report_title": "=== ОТЧЁТЫ ===",
        "report_generated": "Отчёт создан: {path}",

        # Ошибки
        "err_db": "Ошибка базы данных: {message}",
        "err_llm": "LLM недоступен: {message}",
        "err_file": "Ошибка файла: {message}",
        "err_permission": "Нет прав доступа: {resource}",

        # Версия/инфо
        "version": "AIM v{version}",
        "system_info": "Система: AIM v{version} | Пациентов: {patients} | Язык: {lang}",
        "doctor": "Врач: Д-р Джаба Ткемаладзе",
    },

    # ========================================================================
    # ГРУЗИНСКИЙ
    # ========================================================================
    "ka": {
        # მთავარი მენიუ
        "m1": "პაციენტების სია",
        "m2": "ახალი პაციენტი",
        "m3": "პაციენტის ძიება",
        "m4": "AI-კონსულტაცია",
        "m5": "ლაბორატორიული მონაცემების ანალიზი",
        "m6": "ბაიესური დიაგნოსტიკა",
        "m7": "მკურნალობის პროტოკოლები",
        "m8": "Ze-სტატუსი / HRV",
        "m9": "ანგარიშები და ექსპორტი",
        "mw": "გასვლა",
        "mgui": "პარამეტრები",

        # სისტემური
        "welcome": "კეთილი იყოს თქვენი მობრძანება AIM v{version}-ში",
        "loading": "იტვირთება...",
        "processing": "მუშავდება...",
        "error": "შეცდომა: {message}",
        "success": "დასრულდა",
        "confirm": "დაადასტურეთ? (დ/არ): ",
        "yes": "დ",
        "no": "არ",
        "back": "უკან",
        "exit": "გასვლა",
        "not_found": "ვერ მოიძებნა",
        "saved": "შენახულია",
        "cancelled": "გაუქმდა",
        "choose_lang": "Выберите язык / Choose language / აირჩიეთ ენა / Тілді таңдаңыз:",

        # პაციენტები
        "patients_title": "=== პაციენტები ===",
        "no_patients": "პაციენტები ვერ მოიძებნა",
        "ai_thinking": "AI აანალიზებს...",
        "ai_title": "=== AI-კონსულტაცია ===",
        "ai_prompt": "თქვენი კითხვა (ან Enter გასვლისთვის): ",
        "ze_title": "=== Ze-სტატუსი / HRV ===",
        "ze_high": "მაღალი — შესანიშნავი ბიოლოგიური რეზერვი",
        "ze_medium": "საშუალო — ზომიერი რეზერვი, პრევენცია",
        "ze_low": "დაბალი — შემცირებული რეზერვი",
        "ze_critical": "კრიტიკული — მინიმალური რეზერვი",
        "version": "AIM v{version}",
        "doctor": "ექიმი: დოქ. ჯაბა თქემალაძე",
    },

    # ========================================================================
    # АНГЛИЙСКИЙ
    # ========================================================================
    "en": {
        # Main menu
        "m1": "Patient List",
        "m2": "New Patient",
        "m3": "Search Patient",
        "m4": "AI Consultation",
        "m5": "Lab Data Analysis",
        "m6": "Bayesian Diagnostics",
        "m7": "Treatment Protocols",
        "m8": "Ze-Status / HRV",
        "m9": "Reports & Export",
        "mw": "Exit",
        "mgui": "Settings",

        # System
        "welcome": "Welcome to AIM v{version}",
        "loading": "Loading...",
        "processing": "Processing...",
        "error": "Error: {message}",
        "success": "Done",
        "confirm": "Confirm? (y/n): ",
        "yes": "y",
        "no": "n",
        "back": "Back",
        "exit": "Exit",
        "not_found": "Not found",
        "saved": "Saved",
        "cancelled": "Cancelled",
        "choose_lang": "Выберите язык / Choose language / აირჩიეთ ენა / Тілді таңдаңыз:",

        # Patients
        "patients_title": "=== PATIENTS ===",
        "no_patients": "No patients found",
        "patient_created": "Patient created: {name}",
        "search_prompt": "Enter name to search: ",

        # AI
        "ai_thinking": "AI is analyzing...",
        "ai_title": "=== AI CONSULTATION ===",
        "ai_prompt": "Your question (or Enter to exit): ",
        "ai_no_key": "DeepSeek API unavailable. Check ~/.aim_env",

        # Ze/HRV
        "ze_title": "=== Ze-STATUS / HRV ===",
        "ze_high": "High — excellent biological reserve",
        "ze_medium": "Medium — moderate reserve, prevention",
        "ze_low": "Low — reduced reserve, active treatment",
        "ze_critical": "Critical — minimal reserve",

        # Diagnosis
        "diag_title": "=== DIFFERENTIAL DIAGNOSIS ===",
        "diag_symptoms": "Enter symptoms (comma-separated): ",
        "diag_running": "Bayesian analysis...",

        # Version
        "version": "AIM v{version}",
        "system_info": "System: AIM v{version} | Patients: {patients} | Lang: {lang}",
        "doctor": "Physician: Dr. Jaba Tkemaladze",
    },

    # ========================================================================
    # КАЗАХСКИЙ
    # ========================================================================
    "kz": {
        # Басты мәзір
        "m1": "Пациенттер тізімі",
        "m2": "Жаңа пациент",
        "m3": "Пациентті іздеу",
        "m4": "AI кеңесі",
        "m5": "Зертханалық деректерді талдау",
        "m6": "Байесиандық диагностика",
        "m7": "Емдеу хаттамалары",
        "m8": "Ze-мәртебесі / HRV",
        "m9": "Есептер және экспорт",
        "mw": "Шығу",
        "mgui": "Параметрлер",

        # Жүйелік
        "welcome": "AIM v{version}-ге қош келдіңіз",
        "loading": "Жүктелуде...",
        "processing": "Өңделуде...",
        "error": "Қате: {message}",
        "success": "Дайын",
        "confirm": "Растайсыз ба? (и/ж): ",
        "yes": "и",
        "no": "ж",
        "back": "Артқа",
        "exit": "Шығу",
        "not_found": "Табылмады",
        "saved": "Сақталды",
        "cancelled": "Болдырылмады",
        "choose_lang": "Выберите язык / Choose language / აირჩიეთ ენა / Тілді таңдаңыз:",

        # Пациенттер
        "patients_title": "=== ПАЦИЕНТТЕР ===",
        "no_patients": "Пациенттер табылмады",

        # AI
        "ai_thinking": "AI талдауда...",
        "ai_title": "=== AI КЕҢЕС ===",
        "ai_prompt": "Сұрағыңыз (немесе шығу үшін Enter): ",

        # Ze/HRV
        "ze_title": "=== Ze-МӘРТЕБЕСІ / HRV ===",
        "ze_high": "Жоғары — өте жақсы биологиялық резерв",
        "ze_medium": "Орташа — қалыпты резерв, профилактика",
        "ze_low": "Төмен — резерв азайған",
        "ze_critical": "Критикалық — минималды резерв",

        # Нұсқа
        "version": "AIM v{version}",
        "doctor": "Дәрігер: Д-р Джаба Ткемаладзе",
    },
}


# ============================================================================
# Выбор языка (интерактивный)
# ============================================================================

def choose_language_interactive() -> str:
    """Интерактивный выбор языка при запуске"""
    print("\n" + t("choose_lang", "ru"))
    print("  1. Русский")
    print("  2. ქართული")
    print("  3. English")
    print("  4. Қазақша")

    choice = input("\nВыбор / Choice / არჩევანი / Таңдау [1-4, Enter=RU]: ").strip()

    lang_map = {"1": "ru", "2": "ka", "3": "en", "4": "kz", "": "ru"}
    selected = lang_map.get(choice, "ru")
    set_lang(selected)
    return selected


# ============================================================================
# CLI тест
# ============================================================================

if __name__ == "__main__":
    for lang in cfg.SUPPORTED_LANGS:
        set_lang(lang)
        print(f"\n[{lang.upper()}]")
        print(f"  welcome: {t('welcome', version='6.0')}")
        print(f"  m1: {t('m1')}")
        print(f"  m4: {t('m4')}")
        print(f"  ze_high: {t('ze_high')}")
    print("\ni18n.py — OK")
