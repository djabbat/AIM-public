defmodule AimWeb.I18n do
  @moduledoc """
  Lightweight i18n. 6 UN languages + Georgian.

  - en (English)
  - fr (French)
  - es (Spanish)
  - ru (Russian)
  - zh (Chinese, Simplified)
  - ar (Arabic, RTL)
  - ka (Georgian)
  """

  @default :en
  @locales [:en, :fr, :es, :ru, :zh, :ar, :ka]

  @rtl ~w(ar)

  @names %{
    en: "English",
    fr: "Français",
    es: "Español",
    ru: "Русский",
    zh: "中文",
    ar: "العربية",
    ka: "ქართული"
  }

  @strings %{
    "app.title" => %{
      en: "AIM",
      fr: "AIM",
      es: "AIM",
      ru: "AIM",
      zh: "AIM",
      ar: "AIM",
      ka: "AIM"
    },
    "nav.home" => %{
      en: "Home",
      fr: "Accueil",
      es: "Inicio",
      ru: "Главная",
      zh: "首页",
      ar: "الرئيسية",
      ka: "მთავარი"
    },
    "nav.chat" => %{
      en: "Chat",
      fr: "Discuter",
      es: "Chat",
      ru: "Чат",
      zh: "聊天",
      ar: "محادثة",
      ka: "ჩატი"
    },
    "nav.intake" => %{
      en: "Intake",
      fr: "Admission",
      es: "Admisión",
      ru: "Приём",
      zh: "接诊",
      ar: "الاستقبال",
      ka: "მიღება"
    },
    "nav.cases" => %{
      en: "Cases",
      fr: "Cas",
      es: "Casos",
      ru: "Случаи",
      zh: "病例",
      ar: "الحالات",
      ka: "შემთხვევები"
    },
    "nav.consult" => %{
      en: "Consultation",
      fr: "Consultation",
      es: "Consulta",
      ru: "Консультация",
      zh: "咨询",
      ar: "استشارة",
      ka: "კონსულტაცია"
    },
    "home.heading" => %{
      en: "AIM — Assistant of Integrative Medicine",
      fr: "AIM — Assistant de Médecine Intégrative",
      es: "AIM — Asistente de Medicina Integrativa",
      ru: "AIM — Ассистент интегративной медицины",
      zh: "AIM — 整合医学助手",
      ar: "AIM — مساعد الطب التكاملي",
      ka: "AIM — ინტეგრაციული მედიცინის ასისტენტი"
    },
    "home.tagline" => %{
      en: "AI doctor's workbench. Native Rust core, Phoenix LiveView UI, no Docker, multi-LLM (DeepSeek, Groq, Claude, Gemini, local Ollama).",
      fr: "Cabinet de médecin assisté par IA. Cœur Rust natif, interface Phoenix LiveView, sans Docker, multi-LLM.",
      es: "Banco de trabajo médico con IA. Núcleo Rust nativo, UI Phoenix LiveView, sin Docker, multi-LLM.",
      ru: "Врачебный рабочий стол с ИИ. Нативное ядро на Rust, интерфейс Phoenix LiveView, без Docker, мульти-LLM.",
      zh: "AI 医生工作台。原生 Rust 内核，Phoenix LiveView 界面，无 Docker，多 LLM。",
      ar: "محطة عمل طبيب مع الذكاء الاصطناعي. نواة Rust، واجهة Phoenix LiveView، بدون Docker.",
      ka: "ექიმის AI სამუშაო ადგილი. Rust ბირთვი, Phoenix LiveView ინტერფეისი, Docker-ის გარეშე."
    },
    "home.cta.dashboard" => %{
      en: "Open dashboard →",
      fr: "Ouvrir le tableau de bord →",
      es: "Abrir panel →",
      ru: "Открыть дашборд →",
      zh: "打开仪表盘 →",
      ar: "افتح لوحة التحكم ←",
      ka: "გახსენი დეშბორდი →"
    },
    "home.cta.chat" => %{
      en: "Ask the AI",
      fr: "Demander à l'IA",
      es: "Preguntar a la IA",
      ru: "Спросить ИИ",
      zh: "询问 AI",
      ar: "اسأل الذكاء الاصطناعي",
      ka: "ჰკითხე AI-ს"
    },
    "home.feature.diagnostics" => %{
      en: "Differential diagnosis · lab interpretation · drug interactions",
      fr: "Diagnostic différentiel · interprétation des analyses · interactions médicamenteuses",
      es: "Diagnóstico diferencial · interpretación de laboratorio · interacciones medicamentosas",
      ru: "Дифференциальная диагностика · интерпретация анализов · лекарственные взаимодействия",
      zh: "鉴别诊断 · 化验解读 · 药物相互作用",
      ar: "التشخيص التفريقي · تفسير المختبر · تفاعلات الأدوية",
      ka: "დიფერენციალური დიაგნოზი · ლაბის ინტერპრეტაცია · წამლების ურთიერთქმედება"
    },
    "home.feature.privacy" => %{
      en: "Per-user provider keys · patient data never crosses the network · GDPR-aware",
      fr: "Clés par utilisateur · les données patients ne quittent jamais le réseau · conforme RGPD",
      es: "Claves por usuario · los datos del paciente nunca salen de la red · cumple GDPR",
      ru: "Ключи провайдера у каждого пользователя · данные пациента не уходят в сеть · GDPR-aware",
      zh: "用户自带密钥 · 患者数据不离开本地 · 符合 GDPR",
      ar: "مفاتيح لكل مستخدم · بيانات المريض لا تغادر الشبكة · GDPR",
      ka: "მომხმარებლის გასაღებები · პაციენტის მონაცემები არ ტოვებენ ქსელს · GDPR"
    },
    "home.feature.stack" => %{
      en: "178 Rust crates · 2531 tests · 0 warnings · native systemd",
      fr: "178 crates Rust · 2531 tests · 0 avertissements · systemd natif",
      es: "178 crates Rust · 2531 pruebas · 0 advertencias · systemd nativo",
      ru: "178 Rust-крейтов · 2531 тестов · 0 предупреждений · нативный systemd",
      zh: "178 个 Rust crate · 2531 项测试 · 0 警告 · 原生 systemd",
      ar: "178 crate من Rust · 2531 اختبار · 0 تحذيرات",
      ka: "178 Rust crate · 2531 ტესტი · 0 გაფრთხილება"
    },
    "home.menu.dashboard" => %{
      en: "Dashboard",
      fr: "Tableau de bord",
      es: "Panel",
      ru: "Дашборд",
      zh: "仪表盘",
      ar: "لوحة التحكم",
      ka: "დეშბორდი"
    },
    "home.menu.drugs" => %{
      en: "Drug interactions",
      fr: "Interactions médicamenteuses",
      es: "Interacciones",
      ru: "Лекарственные взаимодействия",
      zh: "药物相互作用",
      ar: "تفاعلات الأدوية",
      ka: "წამლების ურთიერთქმედება"
    },
    "home.menu.settings" => %{
      en: "Settings",
      fr: "Paramètres",
      es: "Configuración",
      ru: "Настройки",
      zh: "设置",
      ar: "الإعدادات",
      ka: "პარამეტრები"
    },
    "chat.heading" => %{
      en: "Chat",
      fr: "Discussion",
      es: "Chat",
      ru: "Чат",
      zh: "聊天",
      ar: "محادثة",
      ka: "ჩატი"
    },
    "chat.todo" => %{
      en: "TODO: connect to AimOrchestrator.chat/2 and aim-llm :8770.",
      fr: "TODO : connecter à AimOrchestrator.chat/2 et aim-llm :8770.",
      es: "TODO: conectar a AimOrchestrator.chat/2 y aim-llm :8770.",
      ru: "TODO: подключить к AimOrchestrator.chat/2 и aim-llm :8770.",
      zh: "TODO：连接到 AimOrchestrator.chat/2 和 aim-llm :8770。",
      ar: "TODO: ربط بـ AimOrchestrator.chat/2 و aim-llm :8770.",
      ka: "TODO: დაკავშირება AimOrchestrator.chat/2-სა და aim-llm :8770-სთან."
    },
    "intake.heading" => %{
      en: "Patient intake",
      fr: "Admission du patient",
      es: "Admisión del paciente",
      ru: "Приём пациента",
      zh: "患者接诊",
      ar: "استقبال المريض",
      ka: "პაციენტის მიღება"
    },
    "cases.heading" => %{
      en: "Case list",
      fr: "Liste des cas",
      es: "Lista de casos",
      ru: "Список случаев",
      zh: "病例列表",
      ar: "قائمة الحالات",
      ka: "შემთხვევების სია"
    },
    "case.heading" => %{
      en: "Case",
      fr: "Cas",
      es: "Caso",
      ru: "Случай",
      zh: "病例",
      ar: "حالة",
      ka: "შემთხვევა"
    },
    "common.todo" => %{
      en: "TODO",
      fr: "À FAIRE",
      es: "PENDIENTE",
      ru: "TODO",
      zh: "待办",
      ar: "قيد الإنجاز",
      ka: "TODO"
    },
    "lang.label" => %{
      en: "Language",
      fr: "Langue",
      es: "Idioma",
      ru: "Язык",
      zh: "语言",
      ar: "اللغة",
      ka: "ენა"
    },
    # ── Dashboard ────────────────────────────────────────────────────────
    "dashboard.heading" => %{
      en: "Dashboard",
      fr: "Tableau de bord",
      es: "Panel",
      ru: "Дашборд",
      zh: "仪表盘",
      ar: "لوحة التحكم",
      ka: "დეშბორდი"
    },
    "dashboard.health" => %{
      en: "System health",
      fr: "État du système",
      es: "Estado del sistema",
      ru: "Состояние системы",
      zh: "系统健康",
      ar: "صحة النظام",
      ka: "სისტემის მდგომარეობა"
    },
    "dashboard.projects" => %{
      en: "Projects",
      fr: "Projets",
      es: "Proyectos",
      ru: "Проекты",
      zh: "项目",
      ar: "المشاريع",
      ka: "პროექტები"
    },
    "dashboard.deadlines" => %{
      en: "Deadlines",
      fr: "Échéances",
      es: "Plazos",
      ru: "Дедлайны",
      zh: "截止日期",
      ar: "المواعيد النهائية",
      ka: "ვადები"
    },
    "dashboard.no_projects" => %{
      en: "(no active projects)",
      fr: "(pas de projet actif)",
      es: "(sin proyectos activos)",
      ru: "(нет активных проектов)",
      zh: "(无活跃项目)",
      ar: "(لا توجد مشاريع نشطة)",
      ka: "(აქტიური პროექტები არ არის)"
    },
    "dashboard.no_deadlines" => %{
      en: "(no upcoming deadlines)",
      fr: "(aucune échéance à venir)",
      es: "(sin plazos próximos)",
      ru: "(нет ближайших дедлайнов)",
      zh: "(无即将到期)",
      ar: "(لا توجد مواعيد قادمة)",
      ka: "(მოახლოებული ვადები არ არის)"
    },
    "dashboard.refreshed" => %{
      en: "Refreshed at",
      fr: "Actualisé à",
      es: "Actualizado",
      ru: "Обновлено",
      zh: "刷新于",
      ar: "تم التحديث",
      ka: "განახლდა"
    },
    # ── Drug interactions ────────────────────────────────────────────────
    "drugs.heading" => %{
      en: "Drug interaction check",
      fr: "Vérification d'interactions médicamenteuses",
      es: "Verificación de interacciones",
      ru: "Проверка лекарственных взаимодействий",
      zh: "药物相互作用检查",
      ar: "فحص تفاعلات الأدوية",
      ka: "წამლების ურთიერთქმედების შემოწმება"
    },
    "drugs.prompt" => %{
      en: "Enter drugs separated by commas (e.g.: warfarin, ibuprofen, omeprazole):",
      fr: "Entrez les médicaments séparés par des virgules :",
      es: "Ingrese medicamentos separados por comas:",
      ru: "Введите препараты через запятую:",
      zh: "输入药物（逗号分隔）：",
      ar: "أدخل الأدوية مفصولة بفواصل:",
      ka: "შეიყვანეთ წამლები მძიმით გამოყოფილი:"
    },
    "drugs.check" => %{
      en: "Check",
      fr: "Vérifier",
      es: "Verificar",
      ru: "Проверить",
      zh: "检查",
      ar: "فحص",
      ka: "შემოწმება"
    },
    "drugs.checking" => %{
      en: "Checking…",
      fr: "Vérification…",
      es: "Verificando…",
      ru: "Проверка…",
      zh: "检查中…",
      ar: "جاري الفحص…",
      ka: "მოწმდება…"
    },
    "drugs.clear" => %{
      en: "Clear",
      fr: "Effacer",
      es: "Limpiar",
      ru: "Очистить",
      zh: "清除",
      ar: "مسح",
      ka: "გასუფთავება"
    },
    "drugs.regimen" => %{
      en: "Regimen",
      fr: "Schéma",
      es: "Régimen",
      ru: "Схема",
      zh: "方案",
      ar: "النظام",
      ka: "სქემა"
    },
    "drugs.findings" => %{
      en: "Findings",
      fr: "Résultats",
      es: "Hallazgos",
      ru: "Найденные взаимодействия",
      zh: "发现",
      ar: "النتائج",
      ka: "ნაპოვნი ურთიერთქმედებები"
    },
    "drugs.severity" => %{
      en: "Severity",
      fr: "Sévérité",
      es: "Gravedad",
      ru: "Тяжесть",
      zh: "严重程度",
      ar: "الشدة",
      ka: "სიმძიმე"
    },
    "drugs.note" => %{
      en: "Note",
      fr: "Remarque",
      es: "Nota",
      ru: "Описание",
      zh: "说明",
      ar: "ملاحظة",
      ka: "შენიშვნა"
    },
    # ── Settings ─────────────────────────────────────────────────────────
    "settings.heading" => %{
      en: "Settings",
      fr: "Paramètres",
      es: "Configuración",
      ru: "Настройки",
      zh: "设置",
      ar: "الإعدادات",
      ka: "პარამეტრები"
    },
    "settings.keys" => %{
      en: "Provider API keys",
      fr: "Clés API des fournisseurs",
      es: "Claves API de proveedores",
      ru: "API-ключи провайдеров",
      zh: "提供商 API 密钥",
      ar: "مفاتيح API",
      ka: "პროვაიდერების API გასაღებები"
    },
    "settings.keys_hint" => %{
      en: "Each user holds their own keys. Billing goes to YOUR provider account; the hub never sees the key. Stored locally with chmod 0600.",
      fr: "Chaque utilisateur détient ses propres clés. La facturation est sur VOTRE compte fournisseur ; le hub ne voit jamais la clé.",
      es: "Cada usuario tiene sus propias claves. La facturación va a SU cuenta de proveedor; el hub nunca ve la clave.",
      ru: "У каждого пользователя свои ключи. Биллинг идёт на ВАШ аккаунт; хаб ключей не видит. Хранение локально (chmod 0600).",
      zh: "每个用户持有自己的密钥。账单计入您自己的提供商账户；hub 从不接触密钥。",
      ar: "لكل مستخدم مفاتيحه الخاصة. الفوترة على حسابك أنت؛ المركز لا يرى المفتاح.",
      ka: "თითო მომხმარებელი ფლობს თავის გასაღებებს. ბილინგი თქვენი ანგარიშზე; hub-ი გასაღებს ვერ ხედავს."
    },
    "settings.key_placeholder" => %{
      en: "paste API key here",
      fr: "collez la clé API ici",
      es: "pegue la clave API aquí",
      ru: "вставьте сюда API-ключ",
      zh: "在此粘贴 API 密钥",
      ar: "الصق المفتاح هنا",
      ka: "ჩასვით API გასაღები აქ"
    },
    "settings.save" => %{
      en: "Save",
      fr: "Enregistrer",
      es: "Guardar",
      ru: "Сохранить",
      zh: "保存",
      ar: "حفظ",
      ka: "შენახვა"
    },
    "settings.clear" => %{
      en: "Clear",
      fr: "Supprimer",
      es: "Borrar",
      ru: "Удалить",
      zh: "清除",
      ar: "مسح",
      ka: "წაშლა"
    },
    "settings.clear_all" => %{
      en: "Clear all keys",
      fr: "Supprimer toutes les clés",
      es: "Borrar todas las claves",
      ru: "Удалить все ключи",
      zh: "清除所有密钥",
      ar: "مسح كل المفاتيح",
      ka: "ყველა გასაღების წაშლა"
    }
  }

  def default, do: @default
  def locales, do: @locales
  def names, do: @names
  def name(locale), do: Map.get(@names, locale, to_string(locale))
  def rtl?(locale), do: to_string(locale) in @rtl

  @doc "Translate `key` to `locale`, falling back to default. Unknown key → key itself."
  def t(key, locale) when is_atom(locale) do
    case Map.get(@strings, key) do
      nil ->
        key

      translations ->
        Map.get(translations, locale) ||
          Map.get(translations, @default) ||
          key
    end
  end

  def t(key, locale) when is_binary(locale) do
    t(key, parse(locale))
  end

  @doc "Coerce arbitrary input (string/atom) to a supported locale, default if unknown."
  def parse(nil), do: @default
  def parse(loc) when is_atom(loc), do: if(loc in @locales, do: loc, else: @default)

  def parse(loc) when is_binary(loc) do
    a = String.downcase(loc) |> String.split("-") |> hd() |> safe_atom()
    if a in @locales, do: a, else: @default
  end

  defp safe_atom(s) do
    try do
      String.to_existing_atom(s)
    rescue
      ArgumentError -> @default
    end
  end
end
