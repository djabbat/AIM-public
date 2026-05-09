//! aim-lang — translation, language detection, term explanation, simplification.
//!
//! Port of `agents/lang.py`. The Python original delegates to `llm.ask` and
//! `llm._detect_lang`. Both are abstracted here behind traits ([`Llm`],
//! [`LangDetector`]) so the agent is testable without an LLM call.

use std::collections::HashMap;

use once_cell::sync::Lazy;
use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum LangError {
    #[error("llm error: {0}")]
    Llm(String),
}

pub type Result<T> = std::result::Result<T, LangError>;

// ── supported languages ─────────────────────────────────────────────────────

/// AIM's 9 supported languages: UN-6 (en/ru/fr/es/ar/zh) + ka + kz + da.
pub const SUPPORTED_LANGS: &[&str] = &["ru", "en", "fr", "es", "ar", "zh", "ka", "kz", "da"];

pub static LANG_NAMES: Lazy<HashMap<&'static str, &'static str>> = Lazy::new(|| {
    let mut m = HashMap::new();
    m.insert("ru", "Русский");
    m.insert("en", "English");
    m.insert("fr", "Français");
    m.insert("es", "Español");
    m.insert("ar", "العربية");
    m.insert("zh", "中文");
    m.insert("ka", "ქართული");
    m.insert("kz", "Қазақша");
    m.insert("da", "Dansk");
    m
});

pub fn lang_name(code: &str) -> &str {
    LANG_NAMES.get(code).copied().unwrap_or(code)
}

pub fn is_supported(code: &str) -> bool {
    SUPPORTED_LANGS.iter().any(|&l| l == code)
}

// ── translation kinds ───────────────────────────────────────────────────────

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum TranslationType {
    Medical,
    Scientific,
    Patient,
    General,
}

impl TranslationType {
    pub fn parse(s: &str) -> Self {
        match s {
            "medical" => Self::Medical,
            "scientific" => Self::Scientific,
            "patient" => Self::Patient,
            _ => Self::General,
        }
    }

    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Medical => "medical",
            Self::Scientific => "scientific",
            Self::Patient => "patient",
            Self::General => "general",
        }
    }

    /// Verbatim system prompt for `(type, target_lang)`. RU and EN have
    /// dedicated prompts; everything else falls back to EN.
    pub fn system_prompt(&self, target_lang: &str) -> &'static str {
        match (self, target_lang) {
            (Self::Medical, "ru") => "Ты — медицинский переводчик с 20-летним опытом. Переводи точно, сохраняя медицинскую терминологию. Не добавляй комментарии и пояснения, только перевод.",
            (Self::Medical, _) => "You are a medical translator with 20 years of experience. Translate accurately, preserving medical terminology. Do not add comments or explanations, only the translation.",
            (Self::Scientific, "ru") => "Ты — научный переводчик. Сохраняй академический стиль, терминологию, структуру. Переводи дословно, без упрощений.",
            (Self::Scientific, _) => "You are a scientific translator. Preserve academic style, terminology, structure. Translate literally, without simplification.",
            (Self::Patient, "ru") => "Ты — медицинский переводчик для пациентов. Переводи понятным, доступным языком. Медицинские термины объясняй в скобках.",
            (Self::Patient, _) => "You are a medical translator for patients. Translate in plain, accessible language. Explain medical terms in parentheses.",
            (Self::General, "ru") => "Ты — профессиональный переводчик. Переводи точно и естественно.",
            (Self::General, _) => "You are a professional translator. Translate accurately and naturally.",
        }
    }
}

// ── traits ──────────────────────────────────────────────────────────────────

pub trait Llm: Send + Sync {
    fn ask(&self, system: &str, prompt: &str, lang: &str) -> Result<String>;
}

pub trait LangDetector: Send + Sync {
    fn detect(&self, text: &str) -> String;
}

/// Heuristic detector: returns the first language code whose unicode range
/// matches the majority of letters in `text`. Useful as a default and for
/// tests; production wires up `llm._detect_lang`.
pub struct CharsetDetector;

impl LangDetector for CharsetDetector {
    fn detect(&self, text: &str) -> String {
        let mut counts: HashMap<&'static str, usize> = HashMap::new();
        for c in text.chars() {
            let bucket = match c {
                'а'..='я' | 'А'..='Я' | 'ё' | 'Ё' => "ru",
                'a'..='z' | 'A'..='Z' => "en",
                '\u{0600}'..='\u{06FF}' => "ar",
                '\u{4E00}'..='\u{9FFF}' => "zh",
                '\u{10A0}'..='\u{10FF}' => "ka",
                _ => continue,
            };
            *counts.entry(bucket).or_insert(0) += 1;
        }
        counts
            .into_iter()
            .max_by_key(|&(_, n)| n)
            .map(|(k, _)| k.to_string())
            .unwrap_or_else(|| "en".to_string())
    }
}

// ── agent ───────────────────────────────────────────────────────────────────

pub struct LangAgent<'a> {
    pub llm: &'a dyn Llm,
    pub detector: &'a dyn LangDetector,
}

impl<'a> LangAgent<'a> {
    pub fn new(llm: &'a dyn Llm, detector: &'a dyn LangDetector) -> Self {
        Self { llm, detector }
    }

    pub fn detect(&self, text: &str) -> String {
        self.detector.detect(text)
    }

    /// Translate `text` into `target_lang`. Returns:
    ///   • `""` for empty/whitespace input
    ///   • `"[Неподдерживаемый язык: <code>]"` for unsupported targets
    ///   • the original text when source == target
    ///   • LLM result otherwise
    pub fn translate(
        &self,
        text: &str,
        target_lang: &str,
        translation_type: TranslationType,
        source_lang: Option<&str>,
    ) -> Result<String> {
        if text.trim().is_empty() {
            return Ok(String::new());
        }
        if !is_supported(target_lang) {
            return Ok(format!("[Неподдерживаемый язык: {}]", target_lang));
        }
        let owned_src;
        let src: &str = match source_lang {
            Some(s) => s,
            None => {
                owned_src = self.detector.detect(text);
                &owned_src
            }
        };
        if src == target_lang {
            return Ok(text.to_string());
        }
        let system = translation_type.system_prompt(target_lang);
        let target_name = lang_name(target_lang);
        let prompt = format!(
            "Переведи следующий текст на язык: {} [{}].\nТип перевода: {}.\n\nТекст:\n{}",
            target_name,
            target_lang,
            translation_type.as_str(),
            text
        );
        self.llm.ask(system, &prompt, target_lang)
    }

    /// Explain a medical term in plain language. RU/EN have canned prompts;
    /// any other code falls back to EN.
    pub fn explain_term(&self, term: &str, lang: &str) -> Result<String> {
        if term.trim().is_empty() {
            return Ok(String::new());
        }
        let system = match lang {
            "ru" => "Ты — врач. Объясни медицинский термин простым языком. 2–3 предложения.",
            _ => "You are a doctor. Explain the medical term in plain language. 2–3 sentences.",
        };
        let prompt = format!("Объясни медицинский термин: {}", term);
        self.llm.ask(system, &prompt, lang)
    }

    /// Rewrite medical text in patient-friendly language.
    pub fn simplify(&self, text: &str, lang: &str) -> Result<String> {
        if text.trim().is_empty() {
            return Ok(String::new());
        }
        let system = match lang {
            "ru" => "Перепиши медицинский текст простым языком для пациента. Избегай терминов или объясняй их в скобках. Сохрани все важные факты.",
            _ => "Rewrite the medical text in plain language for a patient. Avoid jargon or explain terms in parentheses. Preserve all important facts.",
        };
        let prompt = format!("Упрости для пациента:\n\n{}", text);
        self.llm.ask(system, &prompt, lang)
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct LangInfo {
    pub code: String,
    pub name: String,
}

pub fn available_langs() -> Vec<LangInfo> {
    SUPPORTED_LANGS
        .iter()
        .map(|c| LangInfo {
            code: c.to_string(),
            name: lang_name(c).to_string(),
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use parking_lot::Mutex;

    // ── stubs ───────────────────────────────────────────────────────────────

    struct ScriptedLlm {
        canned: Mutex<String>,
        calls: Mutex<Vec<(String, String, String)>>,
    }
    impl ScriptedLlm {
        fn new(canned: &str) -> Self {
            Self {
                canned: Mutex::new(canned.into()),
                calls: Mutex::new(Vec::new()),
            }
        }
    }
    impl Llm for ScriptedLlm {
        fn ask(&self, system: &str, prompt: &str, lang: &str) -> Result<String> {
            self.calls.lock().push((system.into(), prompt.into(), lang.into()));
            Ok(self.canned.lock().clone())
        }
    }

    struct FixedDetector(&'static str);
    impl LangDetector for FixedDetector {
        fn detect(&self, _text: &str) -> String {
            self.0.into()
        }
    }

    // ── helpers ─────────────────────────────────────────────────────────────

    #[test]
    fn supported_langs_contains_all_nine() {
        assert_eq!(SUPPORTED_LANGS.len(), 9);
        for code in ["ru", "en", "fr", "es", "ar", "zh", "ka", "kz", "da"] {
            assert!(is_supported(code), "missing {}", code);
        }
    }

    #[test]
    fn lang_name_known_and_unknown() {
        assert_eq!(lang_name("ka"), "ქართული");
        assert_eq!(lang_name("xx"), "xx");
    }

    // ── TranslationType ─────────────────────────────────────────────────────

    #[test]
    fn translation_type_parse_branches() {
        assert_eq!(TranslationType::parse("medical"), TranslationType::Medical);
        assert_eq!(TranslationType::parse("scientific"), TranslationType::Scientific);
        assert_eq!(TranslationType::parse("patient"), TranslationType::Patient);
        assert_eq!(TranslationType::parse("general"), TranslationType::General);
        assert_eq!(TranslationType::parse(""), TranslationType::General);
    }

    #[test]
    fn translation_type_system_prompt_ru_en_distinct() {
        let ru = TranslationType::Medical.system_prompt("ru");
        let en = TranslationType::Medical.system_prompt("en");
        assert!(ru.contains("медицинский"));
        assert!(en.contains("medical"));
        assert_ne!(ru, en);
    }

    #[test]
    fn translation_type_system_prompt_unknown_falls_back_to_en() {
        let fr = TranslationType::Medical.system_prompt("fr");
        let en = TranslationType::Medical.system_prompt("en");
        assert_eq!(fr, en);
    }

    // ── CharsetDetector ─────────────────────────────────────────────────────

    #[test]
    fn detector_picks_russian_for_cyrillic() {
        assert_eq!(CharsetDetector.detect("Привет, мир"), "ru");
    }

    #[test]
    fn detector_picks_english_for_latin() {
        assert_eq!(CharsetDetector.detect("Hello world"), "en");
    }

    #[test]
    fn detector_picks_georgian_for_mkhedruli() {
        assert_eq!(CharsetDetector.detect("გამარჯობა"), "ka");
    }

    #[test]
    fn detector_picks_arabic() {
        assert_eq!(CharsetDetector.detect("مرحبا"), "ar");
    }

    #[test]
    fn detector_picks_chinese() {
        assert_eq!(CharsetDetector.detect("你好"), "zh");
    }

    #[test]
    fn detector_defaults_to_english_on_empty() {
        assert_eq!(CharsetDetector.detect(""), "en");
        assert_eq!(CharsetDetector.detect("12345"), "en");
    }

    // ── translate ───────────────────────────────────────────────────────────

    #[test]
    fn translate_empty_returns_empty() {
        let llm = ScriptedLlm::new("ignored");
        let det = FixedDetector("en");
        let agent = LangAgent::new(&llm, &det);
        let r = agent.translate("   ", "ru", TranslationType::General, None).unwrap();
        assert_eq!(r, "");
        assert!(llm.calls.lock().is_empty());
    }

    #[test]
    fn translate_unsupported_target_returns_diagnostic() {
        let llm = ScriptedLlm::new("ignored");
        let det = FixedDetector("en");
        let agent = LangAgent::new(&llm, &det);
        let r = agent.translate("hi", "xx", TranslationType::General, None).unwrap();
        assert!(r.contains("Неподдерживаемый язык"));
        assert!(r.contains("xx"));
    }

    #[test]
    fn translate_passes_through_when_source_equals_target() {
        let llm = ScriptedLlm::new("ignored");
        let det = FixedDetector("ru");
        let agent = LangAgent::new(&llm, &det);
        let r = agent.translate("Привет", "ru", TranslationType::General, None).unwrap();
        assert_eq!(r, "Привет");
        assert!(llm.calls.lock().is_empty());
    }

    #[test]
    fn translate_uses_explicit_source_lang_when_provided() {
        let llm = ScriptedLlm::new("translated");
        let det = FixedDetector("zh"); // would mis-detect
        let agent = LangAgent::new(&llm, &det);
        let _ = agent
            .translate("hello", "ru", TranslationType::Medical, Some("en"))
            .unwrap();
        let prompt = &llm.calls.lock()[0].1;
        assert!(prompt.contains("[ru]"));
        assert!(prompt.contains("Тип перевода: medical"));
    }

    #[test]
    fn translate_uses_translation_type_system_prompt() {
        let llm = ScriptedLlm::new("ok");
        let det = FixedDetector("en");
        let agent = LangAgent::new(&llm, &det);
        let _ = agent.translate("text", "ru", TranslationType::Patient, None).unwrap();
        let system = &llm.calls.lock()[0].0;
        assert_eq!(system, TranslationType::Patient.system_prompt("ru"));
    }

    // ── explain_term ────────────────────────────────────────────────────────

    #[test]
    fn explain_term_empty_returns_empty() {
        let llm = ScriptedLlm::new("ignored");
        let det = FixedDetector("en");
        let agent = LangAgent::new(&llm, &det);
        assert_eq!(agent.explain_term("  ", "ru").unwrap(), "");
    }

    #[test]
    fn explain_term_uses_lang_specific_system() {
        let llm = ScriptedLlm::new("ok");
        let det = FixedDetector("en");
        let agent = LangAgent::new(&llm, &det);
        agent.explain_term("apoptosis", "ru").unwrap();
        assert!(llm.calls.lock()[0].0.contains("Объясни"));
        agent.explain_term("apoptosis", "en").unwrap();
        assert!(llm.calls.lock()[1].0.contains("Explain"));
    }

    // ── simplify ────────────────────────────────────────────────────────────

    #[test]
    fn simplify_empty_returns_empty() {
        let llm = ScriptedLlm::new("ignored");
        let det = FixedDetector("en");
        let agent = LangAgent::new(&llm, &det);
        assert_eq!(agent.simplify("   ", "en").unwrap(), "");
    }

    #[test]
    fn simplify_uses_lang_specific_system() {
        let llm = ScriptedLlm::new("ok");
        let det = FixedDetector("en");
        let agent = LangAgent::new(&llm, &det);
        agent.simplify("clinical text", "ru").unwrap();
        assert!(llm.calls.lock()[0].0.contains("простым языком"));
    }

    // ── available_langs ─────────────────────────────────────────────────────

    #[test]
    fn available_langs_returns_nine_entries_with_names() {
        let v = available_langs();
        assert_eq!(v.len(), 9);
        assert!(v.iter().any(|l| l.code == "ka" && l.name == "ქართული"));
    }
}
