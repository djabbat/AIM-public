"""
AIM v7.0 — Интернационализация
9 языков: RU / EN / FR / ES / AR / ZH / KA / KZ / DA
"""

from config import SUPPORTED_LANGS, DEFAULT_LANG

# ── Строки интерфейса ─────────────────────────────────────────────────────────

STRINGS = {

    # ── Главное меню ──────────────────────────────────────────────────────────
    "menu_title": {
        "ru": "AIM — Ассистент интегративной медицины",
        "en": "AIM — Assistant of Integrative Medicine",
        "fr": "AIM — Assistant de Médecine Intégrative",
        "es": "AIM — Asistente de Medicina Integrativa",
        "ar": "AIM — مساعد الطب التكاملي",
        "zh": "AIM — 整合医学助手",
        "ka": "AIM — ინტეგრაციული მედიცინის ასისტენტი",
        "kz": "AIM — Интегративтік медицина көмекшісі",
        "da": "AIM — Assistent for Integrativ Medicin",
    },
    "m1": {
        "ru": "1. Новый пациент",
        "en": "1. New patient",
        "fr": "1. Nouveau patient",
        "es": "1. Nuevo paciente",
        "ar": "1. مريض جديد",
        "zh": "1. 新患者",
        "ka": "1. ახალი პაციენტი",
        "kz": "1. Жаңа пациент",
        "da": "1. Ny patient",
    },
    "m2": {
        "ru": "2. Открыть пациента",
        "en": "2. Open patient",
        "fr": "2. Ouvrir un patient",
        "es": "2. Abrir paciente",
        "ar": "2. فتح ملف مريض",
        "zh": "2. 打开患者",
        "ka": "2. პაციენტის გახსნა",
        "kz": "2. Пациентті ашу",
        "da": "2. Åbn patient",
    },
    "m3": {
        "ru": "3. Анализы (OCR/PDF)",
        "en": "3. Lab results (OCR/PDF)",
        "fr": "3. Analyses (OCR/PDF)",
        "es": "3. Análisis (OCR/PDF)",
        "ar": "3. نتائج المختبر (OCR/PDF)",
        "zh": "3. 检验结果 (OCR/PDF)",
        "ka": "3. ანალიზები (OCR/PDF)",
        "kz": "3. Талдаулар (OCR/PDF)",
        "da": "3. Laboratorieresultater (OCR/PDF)",
    },
    "m4": {
        "ru": "4. Диагностика",
        "en": "4. Diagnosis",
        "fr": "4. Diagnostic",
        "es": "4. Diagnóstico",
        "ar": "4. التشخيص",
        "zh": "4. 诊断",
        "ka": "4. დიაგნოსტიკა",
        "kz": "4. Диагностика",
        "da": "4. Diagnose",
    },
    "m5": {
        "ru": "5. Протокол лечения",
        "en": "5. Treatment protocol",
        "fr": "5. Protocole de traitement",
        "es": "5. Protocolo de tratamiento",
        "ar": "5. بروتوكول العلاج",
        "zh": "5. 治疗方案",
        "ka": "5. მკურნალობის პროტოკოლი",
        "kz": "5. Емдеу хаттамасы",
        "da": "5. Behandlingsprotokol",
    },
    "m6": {
        "ru": "6. Перевести документ",
        "en": "6. Translate document",
        "fr": "6. Traduire un document",
        "es": "6. Traducir documento",
        "ar": "6. ترجمة مستند",
        "zh": "6. 翻译文件",
        "ka": "6. დოკუმენტის თარგმნა",
        "kz": "6. Құжатты аудару",
        "da": "6. Oversæt dokument",
    },
    "m7": {
        "ru": "7. AI-консультация",
        "en": "7. AI consultation",
        "fr": "7. Consultation IA",
        "es": "7. Consulta IA",
        "ar": "7. استشارة ذكاء اصطناعي",
        "zh": "7. AI 咨询",
        "ka": "7. AI კონსულტაცია",
        "kz": "7. AI кеңес",
        "da": "7. AI-konsultation",
    },
    "m8": {
        "ru": "8. Настройки",
        "en": "8. Settings",
        "fr": "8. Paramètres",
        "es": "8. Configuración",
        "ar": "8. الإعدادات",
        "zh": "8. 设置",
        "ka": "8. პარამეტრები",
        "kz": "8. Параметрлер",
        "da": "8. Indstillinger",
    },
    "mq": {
        "ru": "0. Выход",
        "en": "0. Exit",
        "fr": "0. Quitter",
        "es": "0. Salir",
        "ar": "0. خروج",
        "zh": "0. 退出",
        "ka": "0. გასვლა",
        "kz": "0. Шығу",
        "da": "0. Afslut",
    },

    # ── Статусы ───────────────────────────────────────────────────────────────
    "thinking": {
        "ru": "Думаю...",
        "en": "Thinking...",
        "fr": "Réflexion...",
        "es": "Pensando...",
        "ar": "أفكر...",
        "zh": "思考中...",
        "ka": "ვფიქრობ...",
        "kz": "Ойлануда...",
        "da": "Tænker...",
    },
    "error": {
        "ru": "Ошибка",
        "en": "Error",
        "fr": "Erreur",
        "es": "Error",
        "ar": "خطأ",
        "zh": "错误",
        "ka": "შეცდომა",
        "kz": "Қате",
        "da": "Fejl",
    },
    "patient_not_found": {
        "ru": "Пациент не найден",
        "en": "Patient not found",
        "fr": "Patient introuvable",
        "es": "Paciente no encontrado",
        "ar": "المريض غير موجود",
        "zh": "未找到患者",
        "ka": "პაციენტი ვერ მოიძებნა",
        "kz": "Пациент табылмады",
        "da": "Patient ikke fundet",
    },
    "providers_status": {
        "ru": "Статус провайдеров",
        "en": "Providers status",
        "fr": "Statut des fournisseurs",
        "es": "Estado de proveedores",
        "ar": "حالة المزودين",
        "zh": "提供商状态",
        "ka": "პროვაიდერების სტატუსი",
        "kz": "Провайдерлер күйі",
        "da": "Udbyderstatus",
    },
    "lang_changed": {
        "ru": "Язык изменён",
        "en": "Language changed",
        "fr": "Langue changée",
        "es": "Idioma cambiado",
        "ar": "تم تغيير اللغة",
        "zh": "语言已更改",
        "ka": "ენა შეიცვალა",
        "kz": "Тіл өзгертілді",
        "da": "Sprog ændret",
    },

    # ── Системные промпты для LLM ─────────────────────────────────────────────
    "system_doctor": {
        "ru": "Ты — опытный врач-специалист по интегративной медицине. Отвечай на русском языке. Давай точные, клинически обоснованные ответы.",
        "en": "You are an experienced integrative medicine specialist. Answer in English. Provide accurate, clinically grounded responses.",
        "fr": "Vous êtes un spécialiste expérimenté en médecine intégrative. Répondez en français. Donnez des réponses précises et cliniquement fondées.",
        "es": "Eres un especialista experimentado en medicina integrativa. Responde en español. Proporciona respuestas precisas y clínicamente fundamentadas.",
        "ar": "أنت متخصص ذو خبرة في الطب التكاملي. أجب باللغة العربية. قدم إجابات دقيقة ومستندة سريريًا.",
        "zh": "你是一位经验丰富的整合医学专家。用中文回答。提供准确、有临床依据的回答。",
        "ka": "შენ ხარ გამოცდილი ინტეგრაციული მედიცინის სპეციალისტი. უპასუხე ქართულად. გაეცი ზუსტი, კლინიკურად დასაბუთებული პასუხები.",
        "kz": "Сіз — интегративтік медицина саласындағы тәжірибелі маман. Қазақ тілінде жауап беріңіз. Дәл, клиникалық негізделген жауаптар беріңіз.",
        "da": "Du er en erfaren specialist i integrativ medicin. Svar på dansk. Giv præcise, klinisk begrundede svar.",
    },
    "system_translator": {
        "ru": "Ты — профессиональный медицинский переводчик. Переводи точно, сохраняя медицинскую терминологию.",
        "en": "You are a professional medical translator. Translate accurately, preserving medical terminology.",
        "fr": "Vous êtes un traducteur médical professionnel. Traduisez avec précision en préservant la terminologie médicale.",
        "es": "Eres un traductor médico profesional. Traduce con precisión, preservando la terminología médica.",
        "ar": "أنت مترجم طبي محترف. ترجم بدقة مع الحفاظ على المصطلحات الطبية.",
        "zh": "你是一位专业医学翻译。准确翻译，保留医学术语。",
        "ka": "შენ ხარ პროფესიონალი სამედიცინო მთარგმნელი. თარგმნე ზუსტად, სამედიცინო ტერმინოლოგიის შენარჩუნებით.",
        "kz": "Сіз — кәсіби медициналық аудармашысыз. Медициналық терминологияны сақтай отырып, дәл аударыңыз.",
        "da": "Du er en professionel medicinsk oversætter. Oversæt nøjagtigt og bevar den medicinske terminologi.",
    },
}

# ── Функция доступа ───────────────────────────────────────────────────────────

def t(key: str, lang: str = DEFAULT_LANG) -> str:
    """
    Вернуть строку для ключа и языка.
    Fallback: English → ключ.
    """
    entry = STRINGS.get(key, {})
    return entry.get(lang) or entry.get("en") or key


def lang_name(code: str) -> str:
    """Вернуть читаемое название языка по коду."""
    names = {
        "ru": "Русский", "en": "English", "fr": "Français",
        "es": "Español", "ar": "العربية", "zh": "中文",
        "ka": "ქართული", "kz": "Қазақша", "da": "Dansk",
    }
    return names.get(code, code)


def lang_menu() -> str:
    """Список языков для меню выбора."""
    lines = []
    for i, code in enumerate(SUPPORTED_LANGS):
        lines.append(f"  {i+1}. [{code}] {lang_name(code)}")
    return "\n".join(lines)
