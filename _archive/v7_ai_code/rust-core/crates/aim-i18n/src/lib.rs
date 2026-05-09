//! aim-i18n — 7-locale lookup for short user-facing strings.
//!
//! UN-6 + Georgian only:
//! - `en` — English (canonical key form, fallback)
//! - `fr` — French
//! - `es` — Spanish
//! - `ar` — Arabic
//! - `zh` — Chinese (simplified)
//! - `ru` — Russian
//! - `ka` — Georgian
//!
//! API:
//! - [`Locale`] enum
//! - [`t(key, lang)`] — string lookup; falls back to English on miss
//! - [`detect(accept_language)`] — parse RFC 7231 `Accept-Language`
//!   header → best [`Locale`] (used by both Phoenix and Rust HTTP layer)
//!
//! The table is intentionally small — only strings that appear in the
//! Hive landing, the AIM web topbar, and the cron `info_line`. Larger
//! per-page text lives in Phoenix Gettext `priv/gettext/`.

use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
pub enum Locale {
    En,
    Fr,
    Es,
    Ar,
    Zh,
    Ru,
    Ka,
}

impl Locale {
    pub fn code(&self) -> &'static str {
        match self {
            Locale::En => "en",
            Locale::Fr => "fr",
            Locale::Es => "es",
            Locale::Ar => "ar",
            Locale::Zh => "zh",
            Locale::Ru => "ru",
            Locale::Ka => "ka",
        }
    }

    pub fn label(&self) -> &'static str {
        match self {
            Locale::En => "English",
            Locale::Fr => "Français",
            Locale::Es => "Español",
            Locale::Ar => "العربية",
            Locale::Zh => "中文",
            Locale::Ru => "Русский",
            Locale::Ka => "ქართული",
        }
    }

    /// True if this locale renders right-to-left.
    pub fn rtl(&self) -> bool {
        matches!(self, Locale::Ar)
    }

    pub fn parse(s: &str) -> Option<Self> {
        let head = s.split(|c: char| c == '-' || c == '_').next()?;
        match head.to_ascii_lowercase().as_str() {
            "en" => Some(Locale::En),
            "fr" => Some(Locale::Fr),
            "es" => Some(Locale::Es),
            "ar" => Some(Locale::Ar),
            "zh" => Some(Locale::Zh),
            "ru" => Some(Locale::Ru),
            "ka" => Some(Locale::Ka),
            _ => None,
        }
    }

    pub const ALL: &'static [Locale] = &[
        Locale::En,
        Locale::Fr,
        Locale::Es,
        Locale::Ar,
        Locale::Zh,
        Locale::Ru,
        Locale::Ka,
    ];
}

/// Parse an RFC 7231 `Accept-Language` header and return the best
/// supported [`Locale`]. Returns `Locale::En` if nothing matches.
pub fn detect(accept_language: &str) -> Locale {
    let mut best: Option<(Locale, f32)> = None;
    for chunk in accept_language.split(',') {
        let chunk = chunk.trim();
        if chunk.is_empty() {
            continue;
        }
        let mut parts = chunk.split(';');
        let tag = parts.next().unwrap().trim();
        let mut q: f32 = 1.0;
        for ext in parts {
            let ext = ext.trim();
            if let Some(rest) = ext.strip_prefix("q=") {
                if let Ok(v) = rest.parse::<f32>() {
                    q = v;
                }
            }
        }
        if let Some(loc) = Locale::parse(tag) {
            match best {
                None => best = Some((loc, q)),
                Some((_, bq)) if q > bq => best = Some((loc, q)),
                _ => {}
            }
        }
    }
    best.map(|(l, _)| l).unwrap_or(Locale::En)
}

/// Lookup a key in the i18n table. Returns:
/// - the translation for the requested locale if present
/// - English fallback if the locale is missing for that key
/// - `None` if the key is unknown (caller decides what to render —
///   echoing the key is one option for debug visibility)
pub fn t<'a>(key: &'a str, lang: Locale) -> &'a str {
    match lookup(key, lang) {
        Some(s) => s,
        None => key,
    }
}

/// Strict lookup. Returns `None` if the key is not in the table at all
/// (in any locale, including English).
pub fn lookup(key: &str, lang: Locale) -> Option<&'static str> {
    use once_cell::sync::Lazy;
    static TABLE: Lazy<BTreeMap<&'static str, BTreeMap<Locale, &'static str>>> =
        Lazy::new(build_table);
    let row = TABLE.get(key)?;
    row.get(&lang).copied().or_else(|| row.get(&Locale::En).copied())
}

fn build_table() -> BTreeMap<&'static str, BTreeMap<Locale, &'static str>> {
    let mut t: BTreeMap<&'static str, BTreeMap<Locale, &'static str>> = BTreeMap::new();
    for &(key, en, fr, es, ar, zh, ru, ka) in TRANSLATIONS {
        let mut row = BTreeMap::new();
        row.insert(Locale::En, en);
        row.insert(Locale::Fr, fr);
        row.insert(Locale::Es, es);
        row.insert(Locale::Ar, ar);
        row.insert(Locale::Zh, zh);
        row.insert(Locale::Ru, ru);
        row.insert(Locale::Ka, ka);
        t.insert(key, row);
    }
    t
}

/// (key, en, fr, es, ar, zh, ru, ka)
const TRANSLATIONS: &[(
    &str,
    &str,
    &str,
    &str,
    &str,
    &str,
    &str,
    &str,
)] = &[
    (
        "nav.hive",
        "Hive",
        "Ruche",
        "Colmena",
        "الخلية",
        "蜂巢",
        "Улей",
        "სკა",
    ),
    (
        "nav.diagnostics",
        "Diagnostics",
        "Diagnostics",
        "Diagnóstico",
        "التشخيص",
        "诊断",
        "Диагностика",
        "დიაგნოსტიკა",
    ),
    (
        "nav.dashboard",
        "Dashboard",
        "Tableau de bord",
        "Panel",
        "لوحة التحكم",
        "仪表板",
        "Панель",
        "მთავარი პანელი",
    ),
    (
        "nav.ecosystem",
        "Ecosystem",
        "Écosystème",
        "Ecosistema",
        "النظام البيئي",
        "生态系统",
        "Экосистема",
        "ეკოსისტემა",
    ),
    (
        "nav.donate",
        "Donate",
        "Faire un don",
        "Donar",
        "تبرع",
        "捐赠",
        "Поддержать",
        "შემოწირულობა",
    ),
    (
        "support.title",
        "Support AIM",
        "Soutenir AIM",
        "Apoyar AIM",
        "ادعم AIM",
        "支持 AIM",
        "Поддержать AIM",
        "AIM-ის მხარდაჭერა",
    ),
    (
        "support.body",
        "AIM is an open-source non-profit project from Georgia Longevity Alliance.",
        "AIM est un projet open source à but non lucratif de la Georgia Longevity Alliance.",
        "AIM es un proyecto sin ánimo de lucro de código abierto de Georgia Longevity Alliance.",
        "AIM مشروع غير ربحي مفتوح المصدر من تحالف جورجيا للطول العمر.",
        "AIM 是 Georgia Longevity Alliance 的开源非营利项目。",
        "AIM — некоммерческий open-source проект от Georgia Longevity Alliance.",
        "AIM არის ღია წყაროიანი არაკომერციული პროექტი Georgia Longevity Alliance-ისგან.",
    ),
    (
        "donate.button",
        "♥ Donate to GLA",
        "♥ Faire un don à GLA",
        "♥ Donar a GLA",
        "♥ تبرع لـ GLA",
        "♥向 GLA 捐赠",
        "♥ Поддержать GLA",
        "♥ შემოწირულობა GLA-ს",
    ),
    (
        "loading",
        "loading…",
        "chargement…",
        "cargando…",
        "جارٍ التحميل…",
        "加载中…",
        "загрузка…",
        "იტვირთება…",
    ),
    (
        "queen.health",
        "queen health",
        "santé de la reine",
        "salud de la reina",
        "صحة الملكة",
        "蜂后状态",
        "состояние королевы",
        "დედის ჯანმრთელობა",
    ),
    (
        "dp.budget",
        "differential privacy budget",
        "budget de confidentialité différentielle",
        "presupuesto de privacidad diferencial",
        "ميزانية الخصوصية التفاضلية",
        "差分隐私预算",
        "бюджет дифференциальной приватности",
        "დიფერენციალური კონფიდენციალურობის ბიუჯეტი",
    ),
];

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn locale_codes() {
        assert_eq!(Locale::En.code(), "en");
        assert_eq!(Locale::Ka.code(), "ka");
    }

    #[test]
    fn locale_parse_basic() {
        assert_eq!(Locale::parse("en"), Some(Locale::En));
        assert_eq!(Locale::parse("EN"), Some(Locale::En));
        assert_eq!(Locale::parse("ka"), Some(Locale::Ka));
        assert_eq!(Locale::parse("zh-CN"), Some(Locale::Zh));
        assert_eq!(Locale::parse("ar_AE"), Some(Locale::Ar));
        assert_eq!(Locale::parse("fr-FR"), Some(Locale::Fr));
        assert_eq!(Locale::parse("xx"), None);
    }

    #[test]
    fn rtl_only_arabic() {
        assert!(Locale::Ar.rtl());
        assert!(!Locale::En.rtl());
        assert!(!Locale::Ka.rtl());
    }

    #[test]
    fn detect_picks_highest_q() {
        // Russian wins q=0.9 over English q=0.5
        let l = detect("en;q=0.5, ru;q=0.9, *;q=0.1");
        assert_eq!(l, Locale::Ru);
    }

    #[test]
    fn detect_first_match_when_q_equal() {
        let l = detect("ka, ru");
        assert_eq!(l, Locale::Ka);
    }

    #[test]
    fn detect_falls_back_to_english_when_unknown() {
        let l = detect("xx, yy, zz");
        assert_eq!(l, Locale::En);
    }

    #[test]
    fn detect_handles_empty() {
        assert_eq!(detect(""), Locale::En);
        assert_eq!(detect(",,"), Locale::En);
    }

    #[test]
    fn t_returns_lang_specific() {
        assert_eq!(t("nav.hive", Locale::En), "Hive");
        assert_eq!(t("nav.hive", Locale::Ka), "სკა");
        assert_eq!(t("nav.hive", Locale::Ar), "الخلية");
        assert_eq!(t("nav.hive", Locale::Zh), "蜂巢");
    }

    #[test]
    fn t_unknown_key_echoes() {
        assert_eq!(t("not.a.real.key", Locale::Ka), "not.a.real.key");
    }

    #[test]
    fn donate_button_translated_for_all() {
        for &loc in Locale::ALL {
            let s = t("donate.button", loc);
            assert!(!s.is_empty());
            assert!(s.contains("♥") || loc == Locale::En);
        }
    }

    #[test]
    fn locale_label_non_empty_all() {
        for &loc in Locale::ALL {
            assert!(!loc.label().is_empty());
        }
    }
}
