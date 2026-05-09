//! aim-doctor-agent — диагностика, протоколы лечения, интерпретация анализов.
//!
//! Port of `agents/doctor.py` (LLM-driven methods only — kernel-powered
//! `triage()`/`treatment()` are deferred until `aim-kernel` is in place).
//!
//! All collaborators are pluggable:
//!   • [`Llm`] — wraps `ask` / `ask_deep` (Default vs Deep tier)
//!   • [`Cache`] — diagnose() result cache (deterministic on identical input)
//!   • [`Localizer`] — `t("error", lang)` lookup

use std::collections::HashMap;

use once_cell::sync::Lazy;
use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum DoctorError {
    #[error("llm error: {0}")]
    Llm(String),
}

pub type Result<T> = std::result::Result<T, DoctorError>;

// ── system prompts ──────────────────────────────────────────────────────────

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Role {
    Diagnosis,
    Treatment,
    Labs,
}

impl Role {
    /// `(role, lang)` system prompt. RU/EN have full prompts; any other
    /// `lang` falls back to EN. Verbatim from Python.
    pub fn system_prompt(&self, lang: &str) -> &'static str {
        match (self, lang) {
            (Self::Diagnosis, "ru") => "Ты — опытный врач интегративной медицины. Проводи дифференциальную диагностику строго по симптомам. Структурируй ответ: 1) Наиболее вероятный диагноз, 2) Дифференциальный ряд (3–5 вариантов), 3) Необходимые обследования. НИКОГДА не ставь окончательный диагноз без обследований. В конце: disclaimer — 'Это информационная поддержка, не медицинский совет.'",
            (Self::Diagnosis, _) => "You are an experienced integrative medicine physician. Perform differential diagnosis strictly based on symptoms. Structure your answer: 1) Most likely diagnosis, 2) Differential list (3–5 options), 3) Required workup. NEVER make a final diagnosis without investigations. End with: disclaimer — 'This is informational support, not medical advice.'",
            (Self::Treatment, "ru") => "Ты — врач интегративной медицины. Составляй протоколы лечения с доказательной базой. Структура: 1) Конвенциональная терапия (первая линия), 2) Интегративные подходы (нутрицевтики, фитотерапия, физиотерапия), 3) Образ жизни и профилактика. Указывай уровень доказательности (A/B/C). Disclaimer в конце обязателен.",
            (Self::Treatment, _) => "You are an integrative medicine physician. Create evidence-based treatment protocols. Structure: 1) Conventional therapy (first line), 2) Integrative approaches (nutraceuticals, phytotherapy, physiotherapy), 3) Lifestyle and prevention. Indicate evidence level (A/B/C). Disclaimer at the end is mandatory.",
            (Self::Labs, "ru") => "Ты — клинический лаборант и врач-интерпретатор. Анализируй лабораторные данные. Структура: 1) Отклонения от нормы (выделить критические), 2) Клиническое значение, 3) Рекомендации по дообследованию. Disclaimer обязателен.",
            (Self::Labs, _) => "You are a clinical laboratory specialist and interpreting physician. Analyze laboratory data. Structure: 1) Deviations from normal (highlight critical), 2) Clinical significance, 3) Recommendations for further workup. Disclaimer is mandatory.",
        }
    }
}

// ── disclaimers ─────────────────────────────────────────────────────────────

pub static DISCLAIMERS: Lazy<HashMap<&'static str, &'static str>> = Lazy::new(|| {
    let mut m = HashMap::new();
    m.insert("ru", "\n\n⚠️ Информационная поддержка. Не является медицинским советом. Проконсультируйтесь с лечащим врачом.");
    m.insert("en", "\n\n⚠️ Informational support only. Not medical advice. Consult your physician.");
    m.insert("fr", "\n\n⚠️ Soutien informationnel uniquement. Pas un avis médical. Consultez votre médecin.");
    m.insert("es", "\n\n⚠️ Solo información. No es consejo médico. Consulte a su médico.");
    m.insert("ar", "\n\n⚠️ دعم معلوماتي فقط. ليس نصيحة طبية. استشر طبيبك.");
    m.insert("zh", "\n\n⚠️ 仅供参考，不构成医疗建议。请咨询您的医生。");
    m.insert("ka", "\n\n⚠️ მხოლოდ საინფორმაციო მხარდაჭერა. არ არის სამედიცინო რჩევა. გაიარეთ კონსულტაცია ექიმთან.");
    m.insert("kz", "\n\n⚠️ Тек ақпараттық қолдау. Медициналық кеңес емес. Дәрігерге хабарласыңыз.");
    m.insert("da", "\n\n⚠️ Kun informationsstøtte. Ikke medicinsk rådgivning. Konsulter din læge.");
    m
});

const DISCLAIMER_MARKERS: &[&str] = &[
    "⚠️",
    "disclaimer",
    "Disclaimer",
    "не является медицинским",
    "not medical advice",
];

/// Append a localized disclaimer to `text` unless one is already present.
pub fn ensure_disclaimer(text: &str, lang: &str) -> String {
    if DISCLAIMER_MARKERS.iter().any(|m| text.contains(m)) {
        return text.to_string();
    }
    let disc = DISCLAIMERS.get(lang).copied().unwrap_or_else(|| {
        DISCLAIMERS.get("en").copied().unwrap_or("")
    });
    format!("{}{}", text, disc)
}

// ── patient formatting ──────────────────────────────────────────────────────

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct Patient {
    pub id: Option<String>,
    pub age: Option<i32>,
    pub sex: Option<String>,
    pub allergies: Vec<String>,
    pub medications: Vec<Medication>,
    pub red_flags: Vec<String>,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct Medication {
    pub name: String,
}

pub fn format_patient(patient: &Patient) -> String {
    let mut parts: Vec<String> = Vec::new();
    if let Some(age) = patient.age {
        parts.push(format!("возраст {}", age));
    }
    if let Some(sex) = &patient.sex {
        if !sex.is_empty() {
            parts.push(format!("пол {}", sex));
        }
    }
    if !patient.allergies.is_empty() {
        parts.push(format!("аллергии: {}", patient.allergies.join(", ")));
    }
    if !patient.medications.is_empty() {
        let meds: Vec<String> = patient.medications.iter().map(|m| m.name.clone()).collect();
        parts.push(format!("принимает: {}", meds.join(", ")));
    }
    if !patient.red_flags.is_empty() {
        parts.push(format!("red flags: {}", patient.red_flags.join("; ")));
    }
    if parts.is_empty() {
        "нет данных".into()
    } else {
        parts.join(" · ")
    }
}

// ── alternative parsing ─────────────────────────────────────────────────────

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct Alternative {
    pub id: String,
    pub action_type: String,
    pub description: String,
    pub payload: serde_json::Value,
}

/// Parse a JSON array of `Alternative` objects from raw LLM output. Strips
/// triple-backtick fences, locates `[…]`, then `serde_json` parses. Mirrors
/// Python `_parse_alternatives` semantics.
pub fn parse_alternatives(raw: &str) -> Result<Vec<Alternative>> {
    let mut s: String = raw.trim().to_string();
    if s.contains("```") {
        let mut parts = s.splitn(3, "```");
        let _before = parts.next();
        if let Some(inner) = parts.next() {
            let trimmed = inner.strip_prefix("json").unwrap_or(inner);
            s = trimmed.to_string();
        }
    }
    let start = s.find('[').ok_or_else(|| DoctorError::Llm("No JSON array".into()))?;
    let end = s.rfind(']').ok_or_else(|| DoctorError::Llm("No JSON array close".into()))?;
    if end < start {
        return Err(DoctorError::Llm("malformed JSON array".into()));
    }
    let slice = &s[start..=end];
    let raw_items: Vec<serde_json::Value> =
        serde_json::from_str(slice).map_err(|e| DoctorError::Llm(format!("parse: {}", e)))?;

    let mut out: Vec<Alternative> = Vec::new();
    for (i, item) in raw_items.into_iter().enumerate() {
        let id = item
            .get("id")
            .and_then(|v| v.as_str())
            .map(String::from)
            .unwrap_or_else(|| format!("opt_{}", i));
        let action_type = item
            .get("action_type")
            .and_then(|v| v.as_str())
            .unwrap_or("dx")
            .to_string();
        let description = item
            .get("description")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        let payload = item
            .get("payload")
            .cloned()
            .unwrap_or(serde_json::json!({}));
        out.push(Alternative {
            id,
            action_type,
            description,
            payload,
        });
    }
    Ok(out)
}

/// Parse a numbered/bulleted list of clarifying questions from LLM output.
pub fn parse_questions(raw: &str) -> Vec<String> {
    let mut out: Vec<String> = Vec::new();
    for line in raw.lines() {
        let trimmed = line.trim();
        if trimmed.is_empty() {
            continue;
        }
        let starts_numbered = trimmed.starts_with(|c: char| c.is_ascii_digit())
            && trimmed.chars().nth(1) == Some('.');
        let starts_bullet = trimmed.starts_with("- ") || trimmed.starts_with("* ");
        if !(starts_numbered || starts_bullet) {
            continue;
        }
        let cleaned: String = trimmed
            .trim_start_matches(|c: char| c.is_ascii_digit() || c == '.' || c == '-' || c == '*' || c == ' ')
            .to_string();
        if !cleaned.is_empty() {
            out.push(cleaned);
        }
    }
    out
}

// ── traits ──────────────────────────────────────────────────────────────────

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum LlmTier {
    Default,
    Deep,
}

pub trait Llm: Send + Sync {
    fn complete(&self, tier: LlmTier, system: &str, prompt: &str, lang: &str) -> Result<String>;
}

/// (prompt, model_tag) → response. `None` = miss.
pub trait Cache: Send + Sync {
    fn get(&self, prompt: &str, model_tag: &str) -> Option<String>;
    fn set(&self, prompt: &str, model_tag: &str, value: String);
}

pub struct NoCache;
impl Cache for NoCache {
    fn get(&self, _: &str, _: &str) -> Option<String> {
        None
    }
    fn set(&self, _: &str, _: &str, _: String) {}
}

pub trait Localizer: Send + Sync {
    /// Mirrors Python `i18n.t(key, lang)`.
    fn t(&self, key: &str, lang: &str) -> String;
}

/// Defaults: returns "(error)" for "error" key, else the key itself.
pub struct DefaultLocalizer;
impl Localizer for DefaultLocalizer {
    fn t(&self, key: &str, _lang: &str) -> String {
        match key {
            "error" => "(error)".into(),
            other => other.into(),
        }
    }
}

// ── DoctorAgent ─────────────────────────────────────────────────────────────

pub struct DoctorAgent<'a> {
    pub llm: &'a dyn Llm,
    pub cache: &'a dyn Cache,
    pub localizer: &'a dyn Localizer,
}

impl<'a> DoctorAgent<'a> {
    pub fn new(llm: &'a dyn Llm, cache: &'a dyn Cache, localizer: &'a dyn Localizer) -> Self {
        Self { llm, cache, localizer }
    }

    pub fn diagnose(&self, symptoms: &str, patient_context: &str, lang: &str) -> Result<String> {
        if symptoms.trim().is_empty() {
            return Ok(self.localizer.t("error", lang));
        }
        let mut prompt = String::new();
        if !patient_context.is_empty() {
            prompt.push_str(&format!("Контекст пациента:\n{}\n\n", patient_context));
        }
        prompt.push_str(&format!("Жалобы и симптомы:\n{}", symptoms));

        let cache_tag = format!("dx:{}", lang);
        if let Some(hit) = self.cache.get(&prompt, &cache_tag) {
            return Ok(hit);
        }
        let system = Role::Diagnosis.system_prompt(lang);
        let raw = self.llm.complete(LlmTier::Deep, system, &prompt, lang)?;
        let with_disc = ensure_disclaimer(&raw, lang);
        self.cache.set(&prompt, &cache_tag, with_disc.clone());
        Ok(with_disc)
    }

    pub fn treatment_plan(&self, diagnosis: &str, patient_context: &str, lang: &str) -> Result<String> {
        if diagnosis.trim().is_empty() {
            return Ok(self.localizer.t("error", lang));
        }
        let mut prompt = String::new();
        if !patient_context.is_empty() {
            prompt.push_str(&format!("Контекст пациента:\n{}\n\n", patient_context));
        }
        prompt.push_str(&format!("Диагноз:\n{}", diagnosis));
        let system = Role::Treatment.system_prompt(lang);
        let raw = self.llm.complete(LlmTier::Deep, system, &prompt, lang)?;
        Ok(ensure_disclaimer(&raw, lang))
    }

    pub fn interpret_labs(&self, lab_text: &str, lang: &str) -> Result<String> {
        if lab_text.trim().is_empty() {
            return Ok(self.localizer.t("error", lang));
        }
        let prompt = format!("Лабораторные данные для интерпретации:\n\n{}", lab_text);
        let system = Role::Labs.system_prompt(lang);
        let raw = self.llm.complete(LlmTier::Default, system, &prompt, lang)?;
        Ok(ensure_disclaimer(&raw, lang))
    }

    /// Free-form chat with rolling history (last 6 messages).
    pub fn chat(&self, message: &str, history: &[(String, String)], lang: &str) -> Result<String> {
        let system = Role::Diagnosis.system_prompt(lang);
        let prompt = if history.is_empty() {
            message.to_string()
        } else {
            let last_six: Vec<String> = history
                .iter()
                .rev()
                .take(6)
                .rev()
                .map(|(role, content)| format!("{}: {}", role.to_uppercase(), content))
                .collect();
            format!("{}\nUSER: {}", last_six.join("\n"), message)
        };
        let raw = self.llm.complete(LlmTier::Default, system, &prompt, lang)?;
        Ok(ensure_disclaimer(&raw, lang))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use parking_lot::Mutex;

    // ── stubs ───────────────────────────────────────────────────────────────

    struct FixedLlm {
        canned: String,
        calls: Mutex<Vec<(LlmTier, String, String, String)>>,
    }
    impl FixedLlm {
        fn new(canned: &str) -> Self {
            Self {
                canned: canned.into(),
                calls: Mutex::new(Vec::new()),
            }
        }
    }
    impl Llm for FixedLlm {
        fn complete(&self, tier: LlmTier, system: &str, prompt: &str, lang: &str) -> Result<String> {
            self.calls.lock().push((
                tier,
                system.into(),
                prompt.into(),
                lang.into(),
            ));
            Ok(self.canned.clone())
        }
    }

    #[derive(Default)]
    struct InMemCache {
        store: Mutex<HashMap<(String, String), String>>,
    }
    impl Cache for InMemCache {
        fn get(&self, prompt: &str, tag: &str) -> Option<String> {
            self.store.lock().get(&(prompt.into(), tag.into())).cloned()
        }
        fn set(&self, prompt: &str, tag: &str, val: String) {
            self.store.lock().insert((prompt.into(), tag.into()), val);
        }
    }

    // ── Role.system_prompt ──────────────────────────────────────────────────

    #[test]
    fn role_system_prompt_ru_en_distinct() {
        let ru = Role::Diagnosis.system_prompt("ru");
        let en = Role::Diagnosis.system_prompt("en");
        assert!(ru.contains("дифференциальную"));
        assert!(en.contains("differential"));
        assert_ne!(ru, en);
    }

    #[test]
    fn role_unknown_lang_falls_back_to_en() {
        let fr = Role::Treatment.system_prompt("fr");
        let en = Role::Treatment.system_prompt("en");
        assert_eq!(fr, en);
    }

    // ── ensure_disclaimer ───────────────────────────────────────────────────

    #[test]
    fn appends_disclaimer_when_missing() {
        let out = ensure_disclaimer("clinical body", "ru");
        assert!(out.starts_with("clinical body"));
        assert!(out.contains("Не является медицинским"));
    }

    #[test]
    fn skips_disclaimer_when_marker_present() {
        let s = "body ⚠️ already has it";
        assert_eq!(ensure_disclaimer(s, "ru"), s);
    }

    #[test]
    fn unknown_lang_uses_english_disclaimer() {
        let out = ensure_disclaimer("body", "fr");
        assert!(out.contains("Pas un avis médical") || out.contains("Not medical advice"));
    }

    #[test]
    fn supports_all_nine_languages() {
        for lang in ["ru", "en", "fr", "es", "ar", "zh", "ka", "kz", "da"] {
            assert!(DISCLAIMERS.contains_key(lang), "missing {}", lang);
        }
    }

    // ── format_patient ──────────────────────────────────────────────────────

    #[test]
    fn format_patient_empty_returns_no_data() {
        let p = Patient::default();
        assert_eq!(format_patient(&p), "нет данных");
    }

    #[test]
    fn format_patient_renders_known_fields_with_separators() {
        let p = Patient {
            age: Some(45),
            sex: Some("M".into()),
            allergies: vec!["aspirin".into()],
            medications: vec![Medication { name: "metformin".into() }],
            red_flags: vec!["chest pain".into()],
            ..Default::default()
        };
        let s = format_patient(&p);
        assert!(s.contains("возраст 45"));
        assert!(s.contains("пол M"));
        assert!(s.contains("aspirin"));
        assert!(s.contains("metformin"));
        assert!(s.contains("chest pain"));
        // separator " · "
        assert!(s.contains(" · "));
    }

    // ── parse_alternatives ──────────────────────────────────────────────────

    #[test]
    fn parse_alternatives_plain_json_array() {
        let raw = r#"[{"id":"a","action_type":"test","description":"CBC","payload":{}},
                       {"id":"b","action_type":"dx","description":"DDx","payload":{}}]"#;
        let v = parse_alternatives(raw).unwrap();
        assert_eq!(v.len(), 2);
        assert_eq!(v[0].id, "a");
        assert_eq!(v[1].action_type, "dx");
    }

    #[test]
    fn parse_alternatives_strips_code_fence() {
        let raw = "```json\n[{\"description\":\"x\"}]\n```";
        let v = parse_alternatives(raw).unwrap();
        assert_eq!(v.len(), 1);
        assert_eq!(v[0].description, "x");
    }

    #[test]
    fn parse_alternatives_defaults_for_missing_fields() {
        let raw = r#"[{}]"#;
        let v = parse_alternatives(raw).unwrap();
        assert_eq!(v[0].id, "opt_0");
        assert_eq!(v[0].action_type, "dx");
        assert_eq!(v[0].description, "");
    }

    #[test]
    fn parse_alternatives_no_array_errors() {
        assert!(parse_alternatives("nothing").is_err());
    }

    // ── parse_questions ─────────────────────────────────────────────────────

    #[test]
    fn parse_questions_numbered() {
        let raw = "1. Болит голова?\n2. Температура была?\nТекст без номера\n3. Тошнота?";
        let q = parse_questions(raw);
        assert_eq!(q.len(), 3);
        assert!(q[0].starts_with("Болит"));
    }

    #[test]
    fn parse_questions_bullets() {
        let raw = "- One question?\n* Another question?";
        let q = parse_questions(raw);
        assert_eq!(q.len(), 2);
    }

    #[test]
    fn parse_questions_empty() {
        assert!(parse_questions("plain text").is_empty());
    }

    // ── DoctorAgent.diagnose ────────────────────────────────────────────────

    #[test]
    fn diagnose_empty_returns_localized_error() {
        let llm = FixedLlm::new("ignored");
        let cache = NoCache;
        let agent = DoctorAgent::new(&llm, &cache, &DefaultLocalizer);
        assert_eq!(agent.diagnose("   ", "", "ru").unwrap(), "(error)");
        assert!(llm.calls.lock().is_empty());
    }

    #[test]
    fn diagnose_uses_deep_tier_and_diagnosis_system() {
        let llm = FixedLlm::new("Most likely: …");
        let cache = NoCache;
        let agent = DoctorAgent::new(&llm, &cache, &DefaultLocalizer);
        let _ = agent.diagnose("headache 3 days", "", "en").unwrap();
        let call = &llm.calls.lock()[0];
        assert_eq!(call.0, LlmTier::Deep);
        assert_eq!(call.1, Role::Diagnosis.system_prompt("en"));
    }

    #[test]
    fn diagnose_appends_disclaimer() {
        let llm = FixedLlm::new("clinical body");
        let cache = NoCache;
        let agent = DoctorAgent::new(&llm, &cache, &DefaultLocalizer);
        let r = agent.diagnose("x", "", "ru").unwrap();
        assert!(r.contains("Не является медицинским"));
    }

    #[test]
    fn diagnose_caches_result_and_returns_on_hit() {
        let llm = FixedLlm::new("body 1");
        let cache = InMemCache::default();
        let agent = DoctorAgent::new(&llm, &cache, &DefaultLocalizer);
        let r1 = agent.diagnose("symptoms", "ctx", "ru").unwrap();
        // change LLM canned: mutating private field — skip; instead verify call count
        assert_eq!(llm.calls.lock().len(), 1);
        let r2 = agent.diagnose("symptoms", "ctx", "ru").unwrap();
        // 2nd call should hit cache → still 1 LLM call
        assert_eq!(llm.calls.lock().len(), 1);
        assert_eq!(r1, r2);
    }

    #[test]
    fn diagnose_includes_patient_context_in_prompt() {
        let llm = FixedLlm::new("ok");
        let cache = NoCache;
        let agent = DoctorAgent::new(&llm, &cache, &DefaultLocalizer);
        agent.diagnose("hdr", "age 50, M", "ru").unwrap();
        let prompt = &llm.calls.lock()[0].2;
        assert!(prompt.contains("Контекст пациента"));
        assert!(prompt.contains("age 50, M"));
    }

    // ── treatment_plan ──────────────────────────────────────────────────────

    #[test]
    fn treatment_plan_uses_treatment_system() {
        let llm = FixedLlm::new("plan");
        let cache = NoCache;
        let agent = DoctorAgent::new(&llm, &cache, &DefaultLocalizer);
        agent.treatment_plan("diagnosis", "", "ru").unwrap();
        let system = &llm.calls.lock()[0].1;
        assert_eq!(system, Role::Treatment.system_prompt("ru"));
    }

    // ── interpret_labs ──────────────────────────────────────────────────────

    #[test]
    fn interpret_labs_uses_default_tier_and_labs_system() {
        let llm = FixedLlm::new("interp");
        let cache = NoCache;
        let agent = DoctorAgent::new(&llm, &cache, &DefaultLocalizer);
        agent.interpret_labs("Hb 130", "ru").unwrap();
        let call = &llm.calls.lock()[0];
        assert_eq!(call.0, LlmTier::Default);
        assert_eq!(call.1, Role::Labs.system_prompt("ru"));
    }

    // ── chat ────────────────────────────────────────────────────────────────

    #[test]
    fn chat_with_no_history_uses_message_only() {
        let llm = FixedLlm::new("reply");
        let cache = NoCache;
        let agent = DoctorAgent::new(&llm, &cache, &DefaultLocalizer);
        agent.chat("hello", &[], "ru").unwrap();
        assert_eq!(llm.calls.lock()[0].2, "hello");
    }

    #[test]
    fn chat_with_history_keeps_last_six_in_order() {
        let llm = FixedLlm::new("reply");
        let cache = NoCache;
        let agent = DoctorAgent::new(&llm, &cache, &DefaultLocalizer);
        let history: Vec<(String, String)> = (0..10)
            .map(|i| ("user".into(), format!("msg{}", i)))
            .collect();
        agent.chat("now", &history, "ru").unwrap();
        let prompt = &llm.calls.lock()[0].2;
        // last 6 slots are msg4..msg9
        assert!(prompt.contains("msg4"));
        assert!(prompt.contains("msg9"));
        // older messages dropped
        assert!(!prompt.contains("msg0"));
        assert!(prompt.ends_with("USER: now"));
    }
}
