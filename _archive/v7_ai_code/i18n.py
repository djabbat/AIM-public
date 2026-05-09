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
    "m9": {
        "ru": "9. Проверка лекарственных взаимодействий",
        "en": "9. Drug interaction check",
        "fr": "9. Vérification d'interactions médicamenteuses",
        "es": "9. Verificación de interacciones medicamentosas",
        "ar": "9. فحص التفاعلات الدوائية",
        "zh": "9. 药物相互作用检查",
        "ka": "9. წამლის ურთიერთქმედების შემოწმება",
        "kz": "9. Дәрілік өзара әсерді тексеру",
        "da": "9. Tjek af lægemiddelinteraktioner",
    },
    "m9_prompt": {
        "ru": "Введите список препаратов через запятую (например: warfarin, ibuprofen, omeprazole):",
        "en": "Enter drugs separated by commas (e.g.: warfarin, ibuprofen, omeprazole):",
        "fr": "Entrez les médicaments séparés par des virgules (ex: warfarin, ibuprofen, omeprazole):",
        "es": "Ingrese medicamentos separados por comas (ej: warfarin, ibuprofen, omeprazole):",
        "ar": "أدخل الأدوية مفصولة بفواصل (مثال: warfarin, ibuprofen, omeprazole):",
        "zh": "输入以逗号分隔的药物(例如:warfarin, ibuprofen, omeprazole):",
        "ka": "შეიყვანეთ წამლები მძიმით გამოყოფილი (მაგ: warfarin, ibuprofen, omeprazole):",
        "kz": "Дәрілерді үтірмен бөліп енгізіңіз (мысал: warfarin, ibuprofen, omeprazole):",
        "da": "Indtast lægemidler adskilt med kommaer (f.eks.: warfarin, ibuprofen, omeprazole):",
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

    # ── AIM AI free-form REPL UI (ai_loop_repl.py) ───────────────────────────
    "repl_banner_title": {
        "en": "AIM AI · free-form ReAct loop · DeepSeek-V4 + 33 tools",
        "fr": "AIM AI · boucle ReAct libre · DeepSeek-V4 + 33 outils",
        "es": "AIM AI · bucle ReAct libre · DeepSeek-V4 + 33 herramientas",
        "ar": "AIM AI · حلقة ReAct حرة · DeepSeek-V4 + 33 أداة",
        "zh": "AIM AI · 自由 ReAct 循环 · DeepSeek-V4 + 33 个工具",
        "ru": "AIM AI · свободный ReAct-цикл · DeepSeek-V4 + 33 инструмента",
        "ka": "AIM AI · თავისუფალი ReAct ციკლი · DeepSeek-V4 + 33 ხელსაწყო",
    },
    "repl_banner_queue_hint": {
        "en": "You can submit new queries while AI is working — they'll queue up.",
        "fr": "Vous pouvez soumettre de nouvelles requêtes pendant que l'IA travaille — elles seront mises en file d'attente.",
        "es": "Puede enviar nuevas consultas mientras la IA trabaja — se pondrán en cola.",
        "ar": "يمكنك إرسال طلبات جديدة أثناء عمل الذكاء الاصطناعي — ستوضع في قائمة الانتظار.",
        "zh": "AI 工作时您可以提交新请求 — 它们将排队等待处理。",
        "ru": "Можно вводить новые запросы пока AI отвечает — встанут в очередь.",
        "ka": "შეგიძლიათ ახალი შეკითხვები შეიყვანოთ AI-ის მუშაობისას — ისინი რიგში დადგებიან.",
    },
    "repl_banner_slash_hint": {
        "en": "/clear — reset context · /history — show memory · /language — change UI language · /help",
        "fr": "/clear — réinit. contexte · /history — afficher mémoire · /language — changer langue · /help",
        "es": "/clear — reiniciar contexto · /history — ver memoria · /language — cambiar idioma · /help",
        "ar": "/clear — إعادة تعيين السياق · /history — عرض الذاكرة · /language — تغيير اللغة · /help",
        "zh": "/clear — 重置上下文 · /history — 显示记忆 · /language — 切换语言 · /help",
        "ru": "/clear — сбросить контекст · /history — показать память · /language — сменить язык · /help",
        "ka": "/clear — კონტექსტის გასუფთავება · /history — მეხსიერების ჩვენება · /language — ენის შეცვლა · /help",
    },
    "repl_banner_select_hint": {
        "en": "Mouse selection + Ctrl+Shift+C — copy · PgUp/PgDn — scroll · End — to bottom",
        "fr": "Sélection souris + Ctrl+Maj+C — copier · PgUp/PgDn — défiler · Fin — au bas",
        "es": "Selección con ratón + Ctrl+Shift+C — copiar · PgUp/PgDn — desplazar · Fin — al final",
        "ar": "تحديد بالماوس + Ctrl+Shift+C — نسخ · PgUp/PgDn — تمرير · End — للأسفل",
        "zh": "鼠标选择 + Ctrl+Shift+C — 复制 · PgUp/PgDn — 滚动 · End — 到底部",
        "ru": "Выделение мышью + Ctrl+Shift+C — копировать · PgUp/PgDn — листать · End — к концу",
        "ka": "მაუსით მონიშვნა + Ctrl+Shift+C — კოპირება · PgUp/PgDn — გადახვევა · End — ბოლოში",
    },
    "repl_input_title": {
        "en": "you ▸  Enter — submit · Alt+Enter — newline · Ctrl-C — interrupt · Ctrl-D — quit",
        "fr": "vous ▸  Entrée — envoyer · Alt+Entrée — nouvelle ligne · Ctrl-C — interrompre · Ctrl-D — quitter",
        "es": "tú ▸  Enter — enviar · Alt+Enter — nueva línea · Ctrl-C — interrumpir · Ctrl-D — salir",
        "ar": "أنت ▸  Enter — إرسال · Alt+Enter — سطر جديد · Ctrl-C — مقاطعة · Ctrl-D — خروج",
        "zh": "你 ▸  Enter — 提交 · Alt+Enter — 换行 · Ctrl-C — 中断 · Ctrl-D — 退出",
        "ru": "you ▸  Enter — отправить · Alt+Enter — новая строка · Ctrl-C — прервать · Ctrl-D — выход",
        "ka": "თქვენ ▸  Enter — გაგზავნა · Alt+Enter — ახალი ხაზი · Ctrl-C — შეწყვეტა · Ctrl-D — გასვლა",
    },
    "repl_status_thinking": {
        "en": "AIM thinking…",  "fr": "AIM réfléchit…",  "es": "AIM pensando…",
        "ar": "AIM يفكر…",      "zh": "AIM 思考中…",        "ru": "AIM думает…",
        "ka": "AIM ფიქრობს…",
    },
    "repl_status_idle": {
        "en": "idle",  "fr": "inactif",  "es": "inactivo",
        "ar": "خامل",  "zh": "空闲",     "ru": "ожидание",  "ka": "მოლოდინი",
    },
    "repl_status_interrupt_hint": {
        "en": "Ctrl-C to interrupt",         "fr": "Ctrl-C pour interrompre",
        "es": "Ctrl-C para interrumpir",     "ar": "Ctrl-C للمقاطعة",
        "zh": "Ctrl-C 中断",                  "ru": "Ctrl-C прервать",
        "ka": "Ctrl-C შეწყვეტისთვის",
    },
    "repl_status_warn_hung": {
        "en": "no tool_call",     "fr": "pas de tool_call",
        "es": "sin tool_call",    "ar": "لا توجد tool_call",
        "zh": "无 tool_call",      "ru": "нет tool_call",
        "ka": "არცერთი tool_call",
    },
    "repl_status_warn_hung_q": {
        "en": "(LLM thinking or stuck?)",   "fr": "(LLM réfléchit ou bloqué ?)",
        "es": "(¿LLM pensando o atascado?)", "ar": "(LLM يفكر أم عالق؟)",
        "zh": "(LLM 思考中还是卡住了?)",      "ru": "(LLM думает или завис?)",
        "ka": "(LLM ფიქრობს თუ გაიჭედა?)",
    },
    "repl_status_warn_long": {
        "en": "long — Ctrl-C to interrupt",
        "fr": "longtemps — Ctrl-C pour interrompre",
        "es": "demasiado — Ctrl-C para interrumpir",
        "ar": "طويل — Ctrl-C للمقاطعة",
        "zh": "时间过长 — Ctrl-C 中断",
        "ru": "долго — Ctrl-C прервать",
        "ka": "ხანგრძლივი — Ctrl-C შეწყვეტისთვის",
    },
    "repl_interrupt_requested": {
        "en": "⏹ interrupt requested...",
        "fr": "⏹ interruption demandée...",
        "es": "⏹ interrupción solicitada...",
        "ar": "⏹ تم طلب المقاطعة...",
        "zh": "⏹ 已请求中断...",
        "ru": "⏹ запрошено прерывание...",
        "ka": "⏹ შეწყვეტის მოთხოვნა გაიგზავნა...",
    },
    "repl_interrupted": {
        "en": "⏹ interrupted by user (Ctrl-C)",
        "fr": "⏹ interrompu par l'utilisateur (Ctrl-C)",
        "es": "⏹ interrumpido por el usuario (Ctrl-C)",
        "ar": "⏹ تمت المقاطعة بواسطة المستخدم (Ctrl-C)",
        "zh": "⏹ 用户中断 (Ctrl-C)",
        "ru": "⏹ прервано пользователем (Ctrl-C)",
        "ka": "⏹ შეწყვეტილია მომხმარებლის მიერ (Ctrl-C)",
    },
    "repl_empty_answer": {
        "en": "(empty answer)",  "fr": "(réponse vide)",
        "es": "(respuesta vacía)", "ar": "(إجابة فارغة)",
        "zh": "(空响应)",          "ru": "(пустой ответ)",
        "ka": "(ცარიელი პასუხი)",
    },
    "repl_worker_silent": {
        "en": "worker finished without an answer (AI exited the loop without emit final — check max_iters or logs in ~/.cache/aim/sessions/)",
        "fr": "worker terminé sans réponse (l'IA est sortie de la boucle sans emit final — vérifier max_iters ou les logs dans ~/.cache/aim/sessions/)",
        "es": "worker terminó sin respuesta (la IA salió del bucle sin emit final — verifica max_iters o los logs en ~/.cache/aim/sessions/)",
        "ar": "انتهى العامل دون إجابة (خرج الذكاء الاصطناعي من الحلقة دون emit final — تحقق من max_iters أو السجلات في ~/.cache/aim/sessions/)",
        "zh": "worker 结束但无答复 (AI 退出循环未 emit final — 检查 max_iters 或 ~/.cache/aim/sessions/ 日志)",
        "ru": "worker завершился без ответа (AI вышел из цикла без emit final — проверь max_iters или logs в ~/.cache/aim/sessions/)",
        "ka": "worker დასრულდა პასუხის გარეშე (AI გამოვიდა ციკლიდან emit final-ის გარეშე — შეამოწმე max_iters ან logs ~/.cache/aim/sessions/-ში)",
    },
    "repl_cmd_clear_done": {
        "en": "  ⟳ conversation context and output cleared",
        "fr": "  ⟳ contexte de conversation et sortie effacés",
        "es": "  ⟳ contexto de conversación y salida borrados",
        "ar": "  ⟳ تم مسح سياق المحادثة والإخراج",
        "zh": "  ⟳ 对话上下文和输出已清除",
        "ru": "  ⟳ контекст разговора и вывод очищены",
        "ka": "  ⟳ საუბრის კონტექსტი და გამონატანი გასუფთავდა",
    },
    "repl_cmd_history_header": {
        "en": "[conversation: {n} turns in memory]",
        "fr": "[conversation: {n} tours en mémoire]",
        "es": "[conversación: {n} turnos en memoria]",
        "ar": "[محادثة: {n} دور في الذاكرة]",
        "zh": "[对话: 内存中 {n} 轮]",
        "ru": "[conversation: {n} ходов в памяти]",
        "ka": "[საუბარი: {n} რაუნდი მეხსიერებაში]",
    },
    "repl_cmd_help_text": {
        "en": "  /clear    — reset context and output\n"
              "  /history  — show remembered turns\n"
              "  /language — switch UI language (7 options)\n"
              "  /help     — this help",
        "fr": "  /clear    — réinitialiser contexte et sortie\n"
              "  /history  — afficher les tours mémorisés\n"
              "  /language — changer la langue (7 options)\n"
              "  /help     — cette aide",
        "es": "  /clear    — reiniciar contexto y salida\n"
              "  /history  — mostrar turnos recordados\n"
              "  /language — cambiar idioma (7 opciones)\n"
              "  /help     — esta ayuda",
        "ar": "  /clear    — إعادة تعيين السياق والإخراج\n"
              "  /history  — عرض الأدوار المحفوظة\n"
              "  /language — تغيير اللغة (7 خيارات)\n"
              "  /help     — هذه المساعدة",
        "zh": "  /clear    — 重置上下文和输出\n"
              "  /history  — 显示记忆的对话\n"
              "  /language — 切换界面语言 (7 种)\n"
              "  /help     — 此帮助",
        "ru": "  /clear    — очистить контекст и вывод\n"
              "  /history  — показать запомненные ходы\n"
              "  /language — сменить язык интерфейса (7 вариантов)\n"
              "  /help     — эта справка",
        "ka": "  /clear    — კონტექსტისა და გამონატანის გასუფთავება\n"
              "  /history  — დამახსოვრებული რაუნდების ჩვენება\n"
              "  /language — ენის შეცვლა (7 ვარიანტი)\n"
              "  /help     — ეს დახმარება",
    },
    "repl_lang_select_header": {
        "en": "Select interface language:",
        "fr": "Choisissez la langue de l'interface:",
        "es": "Seleccione el idioma de la interfaz:",
        "ar": "اختر لغة الواجهة:",
        "zh": "选择界面语言:",
        "ru": "Выберите язык интерфейса:",
        "ka": "აირჩიეთ ინტერფეისის ენა:",
    },
    "repl_lang_select_hint": {
        "en": "Type the language code (en/fr/es/ar/zh/ru/ka) and press Enter.",
        "fr": "Tapez le code de langue (en/fr/es/ar/zh/ru/ka) et appuyez sur Entrée.",
        "es": "Escriba el código de idioma (en/fr/es/ar/zh/ru/ka) y presione Enter.",
        "ar": "اكتب رمز اللغة (en/fr/es/ar/zh/ru/ka) واضغط Enter.",
        "zh": "输入语言代码 (en/fr/es/ar/zh/ru/ka) 并按 Enter。",
        "ru": "Введите код языка (en/fr/es/ar/zh/ru/ka) и нажмите Enter.",
        "ka": "შეიყვანეთ ენის კოდი (en/fr/es/ar/zh/ru/ka) და დააჭირეთ Enter.",
    },
    "repl_lang_set_to": {
        "en": "Language switched to: {name} ({code})",
        "fr": "Langue changée: {name} ({code})",
        "es": "Idioma cambiado a: {name} ({code})",
        "ar": "تم تغيير اللغة إلى: {name} ({code})",
        "zh": "语言已切换到: {name} ({code})",
        "ru": "Язык переключён на: {name} ({code})",
        "ka": "ენა გადართულია: {name} ({code})",
    },
    "repl_lang_unknown": {
        "en": "Unknown language code: {code}. Available: en, fr, es, ar, zh, ru, ka",
        "fr": "Code de langue inconnu: {code}. Disponibles: en, fr, es, ar, zh, ru, ka",
        "es": "Código de idioma desconocido: {code}. Disponibles: en, fr, es, ar, zh, ru, ka",
        "ar": "رمز لغة غير معروف: {code}. المتاحة: en, fr, es, ar, zh, ru, ka",
        "zh": "未知语言代码: {code}。可用: en, fr, es, ar, zh, ru, ka",
        "ru": "Неизвестный код языка: {code}. Доступны: en, fr, es, ar, zh, ru, ka",
        "ka": "უცნობი ენის კოდი: {code}. ხელმისაწვდომი: en, fr, es, ar, zh, ru, ka",
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
