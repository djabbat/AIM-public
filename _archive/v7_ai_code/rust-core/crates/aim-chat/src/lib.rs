//! aim-chat — kernel-powered multilingual chat companion.
//!
//! Port of `agents/chat.py`. The Python original combines:
//!   1. regex-based intent classification (emergency / danger / symptom /
//!      info / emotional / other),
//!   2. alternative-decision generation per intent,
//!   3. kernel.decide() invocation for L0–L3 + scoring,
//!   4. LLM response with intent-specific system prompt.
//!
//! This crate ports (1), (2), (4-prompt-selection) — the pure parts.
//! (3) is left to consumers that already have `aim_kernel` wired in.

use once_cell::sync::Lazy;
use regex::RegexSet;
use serde::{Deserialize, Serialize};
use thiserror::Error;

use aim_kernel::Decision;

#[derive(Debug, Error)]
pub enum ChatError {
    #[error("llm error: {0}")]
    Llm(String),
}

pub type Result<T> = std::result::Result<T, ChatError>;

// ── intent ──────────────────────────────────────────────────────────────────

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize, Hash)]
pub enum Intent {
    Emergency,
    Danger,
    Symptom,
    Info,
    Emotional,
    Other,
}

impl Intent {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Emergency => "emergency",
            Self::Danger => "danger",
            Self::Symptom => "symptom",
            Self::Info => "info",
            Self::Emotional => "emotional",
            Self::Other => "other",
        }
    }
}

// ── pattern banks (verbatim from Python; case-insensitive) ──────────────────

const EMERGENCY_PATTERNS: &[&str] = &[
    // Cardio
    r"давящ.{0,20}боль.{0,20}(груд|сердц)",
    r"crushing chest",
    r"chest pain.{0,30}(jaw|arm|neck)",
    r"давит.{0,20}(сердц|груд)",
    r"боль.{0,20}отдаёт.{0,20}(руку|челюсть|лопатку)",
    // Stroke (FAST)
    r"парализ",
    r"онемени[ея].{0,20}(лица|руки|ноги)",
    r"нарушение.{0,20}реч",
    r"stroke",
    r"face droop",
    r"слабость.{0,20}(половин|одн)",
    // Respiratory
    r"не могу дышать",
    r"удушь[ея]",
    r"cant breathe",
    r"cannot breathe",
    r"suffocat",
    // LOC
    r"потерял.{0,20}сознан",
    r"обморок",
    r"passed out",
    r"lost consciousness",
    // Bleeding
    r"сильное кровотечение",
    r"severe bleeding",
    // Suicide
    r"самоубий",
    r"suicide",
    r"kill myself",
    r"покончить с",
    // Anaphylaxis
    r"анафилак",
    r"распух.{0,20}(лицо|горло|язык)",
    r"tongue swelling",
    // Trauma / overdose
    r"hit by",
    r"overdose",
    r"передозир",
];

const DANGER_PATTERNS: &[&str] = &[
    r"synthes.{0,20}(bio|poison|toxin|weapon)",
    r"make.{0,20}(bomb|explosive|weapon)",
    r"как.{0,20}(изготов|сделать).{0,20}(яд|взрывч|оружие)",
    r"forge.{0,20}(document|prescription|id)",
    r"подделать.{0,20}(рецепт|документ)",
];

static EMERGENCY_RS: Lazy<RegexSet> = Lazy::new(|| {
    RegexSet::new(
        EMERGENCY_PATTERNS
            .iter()
            .map(|p| format!("(?i){}", p)),
    )
    .expect("emergency regexes compile")
});

static DANGER_RS: Lazy<RegexSet> = Lazy::new(|| {
    RegexSet::new(DANGER_PATTERNS.iter().map(|p| format!("(?i){}", p)))
        .expect("danger regexes compile")
});

const EMOTIONAL_KEYWORDS: &[&str] = &[
    "боюсь", "тревог", "депресс", "afraid", "scared", "anxiety",
    "depress", "грустно", "alone", "одиноко",
];

const SYMPTOM_KEYWORDS: &[&str] = &[
    "болит", "беспокоит", "температура", "кашель", "сыпь",
    "hurt", "pain", "fever", "cough", "rash", "symptom",
    "тошнит", "рвота", "диарея", "nausea", "vomit", "diarrhea",
];

const INFO_MARKERS: &[&str] = &[
    "что такое", "как действует", "зачем", "what is", "how does",
    "why", "explain", "объясни", "расскажи о",
];

/// Classify a user message into one [`Intent`]. Emergency takes priority,
/// then danger (L0 pre-filter), then keyword-based heuristics.
pub fn classify_intent(message: &str) -> Intent {
    let m = message.to_lowercase();
    if EMERGENCY_RS.is_match(&m) {
        return Intent::Emergency;
    }
    if DANGER_RS.is_match(&m) {
        return Intent::Danger;
    }
    if EMOTIONAL_KEYWORDS.iter().any(|k| m.contains(k)) {
        return Intent::Emotional;
    }
    if SYMPTOM_KEYWORDS.iter().any(|k| m.contains(k)) {
        return Intent::Symptom;
    }
    if INFO_MARKERS.iter().any(|k| m.contains(k)) {
        return Intent::Info;
    }
    Intent::Other
}

// ── alternative generation ──────────────────────────────────────────────────

fn make_decision(id: &str, action_type: &str, description: &str, payload: serde_json::Value) -> Decision {
    let mut d = Decision::new(id, action_type);
    d.description = description.to_string();
    d.payload = payload;
    d
}

/// Build candidate response approaches for the kernel based on intent.
/// Returns a list mirrored 1:1 from Python; consumers feed it to
/// `aim_kernel::evaluate_laws` + scoring.
pub fn generate_alternatives(intent: Intent) -> Vec<Decision> {
    match intent {
        Intent::Emergency => vec![
            make_decision(
                "emergency",
                "referral",
                "Экстренное направление (скорая / ER)",
                serde_json::json!({
                    "urgency": "immediate",
                    "guideline_based": true,
                    "red_flags": ["emergency pattern detected"]
                }),
            ),
            make_decision(
                "reassure_and_call",
                "clarify",
                "Успокоить + подтвердить вызов скорой",
                serde_json::json!({"informed_consent_noted": true}),
            ),
        ],
        Intent::Danger => vec![
            make_decision(
                "refuse_harmful",
                "clarify",
                "Отказать и объяснить почему; перенаправить на полезные ресурсы",
                serde_json::json!({"informed_consent_noted": true}),
            ),
            // Intentionally include a decoy that L0 will block — mirrors Python.
            make_decision(
                "synthesize_biohazard_X",
                "treatment",
                "synthesize_biohazard requested substance",
                serde_json::json!({"drug": "dangerous_agent"}),
            ),
        ],
        Intent::Symptom => vec![
            make_decision(
                "triage_redirect",
                "referral",
                "Предложить запустить полный triage (kernel)",
                serde_json::json!({"guideline_based": true}),
            ),
            make_decision(
                "clarify_symptom",
                "clarify",
                "Уточняющие вопросы по симптому",
                serde_json::json!({"informed_consent_noted": true}),
            ),
            make_decision(
                "home_remedy",
                "treatment",
                "Базовые home care (fluids, rest) без dx",
                serde_json::json!({"drug": "supportive", "guideline_based": true}),
            ),
        ],
        Intent::Info => vec![
            make_decision(
                "educate",
                "clarify",
                "Образовательный ответ с источниками",
                serde_json::json!({
                    "informed_consent_noted": true,
                    "guideline_based": true
                }),
            ),
            make_decision(
                "inform_and_refer",
                "referral",
                "Краткий ответ + предложение консультации",
                serde_json::json!({"guideline_based": true}),
            ),
        ],
        Intent::Emotional => vec![
            make_decision(
                "empathize_refer",
                "referral",
                "Эмпатия + рекомендация психолога/psychiatrist (если показано)",
                serde_json::json!({
                    "informed_consent_noted": true,
                    "guideline_based": true
                }),
            ),
            make_decision(
                "active_listen",
                "clarify",
                "Active listening: acknowledge + clarifying question",
                serde_json::json!({"informed_consent_noted": true}),
            ),
        ],
        Intent::Other => vec![
            make_decision(
                "clarify_general",
                "clarify",
                "Уточнить что именно интересует пациента",
                serde_json::json!({"informed_consent_noted": true}),
            ),
            make_decision(
                "generic_info",
                "clarify",
                "Общий информационный ответ",
                serde_json::json!({"informed_consent_noted": true}),
            ),
        ],
    }
}

// ── response prompts ───────────────────────────────────────────────────────

/// Verbatim system prompt for `(decision_id_or_intent, lang)`. RU/EN
/// dedicated; everything else falls back to EN.
pub fn response_system_prompt(key: &str, lang: &str) -> &'static str {
    match (key, lang) {
        ("emergency", "ru") => "Пациент в экстренной ситуации. Кратко, ясно, calm: (1) призвать вызвать скорую 112 (Грузия) / 911 / местный emergency number, (2) инструкции до приезда (положение, что делать, чего НЕ делать), (3) одной фразой обосновать срочность. Максимум 150 слов.",
        ("emergency", _) => "Patient in emergency. Concise, clear, calm response: (1) call emergency services 112/911, (2) instructions until arrival, (3) one-sentence reason for urgency. Max 150 words.",
        ("triage_redirect", "ru") => "Пациент описал симптом. Ответ: empathetic acknowledgment + предложить пройти full triage через AIM для точной рекомендации. Не ставить диагноз. Спросить согласие на 2-3 уточняющих вопроса.",
        ("triage_redirect", _) => "Patient described symptom. Response: empathetic acknowledgment + suggest running full AIM triage for accurate recommendation. Don't diagnose. Ask consent for 2-3 clarifying questions.",
        ("clarify_symptom", "ru") => "Задай пациенту 2-3 уточняющих вопроса о симптоме (timeline, характер, триггеры, severity). Коротко, empathetic tone.",
        ("clarify_symptom", _) => "Ask patient 2-3 clarifying questions about symptom (timeline, nature, triggers, severity). Brief, empathetic tone.",
        ("educate", "ru") => "Дай educational ответ на вопрос пациента. Honest, grounded, с disclaimer 'это информация, не медицинский совет'. Максимум 200 слов. Если вопрос outside медицинской scope — сказать.",
        ("educate", _) => "Educational answer to patient question. Honest, grounded, with 'this is info not medical advice' disclaimer. Max 200 words. Say if question outside medical scope.",
        ("empathize_refer", "ru") => "Пациент в эмоциональном состоянии. Ответ: (1) acknowledge feelings без суждения, (2) если есть signs requiring help (suicidal, severe depression) — рекомендовать immediate professional support, (3) если general anxiety — нормализовать + рекомендовать психолога при need. Не давать therapy, только support + referral.",
        ("empathize_refer", _) => "Patient in emotional state. Response: (1) acknowledge feelings without judgment, (2) if signs requiring help — immediate professional support, (3) if general anxiety — normalize + recommend psychologist. Don't give therapy, only support + referral.",
        ("refuse_harmful", "ru") => "Пациент запросил потенциально вредную информацию (dual-use / bio / oружие / документы). Ответ: вежливо отказать, объяснить что это выходит за рамки безопасной помощи, перенаправить на legitimate help если применимо (напр. mental health crisis → hotline).",
        ("refuse_harmful", _) => "Patient requested potentially harmful info (dual-use / bio / weapon / docs). Response: politely decline, explain this is outside safe help scope, redirect to legitimate help if applicable (e.g. mental health crisis hotline).",
        // Fallback for unknown keys
        (_, "ru") => "Ты — AIM, AI-ассистент Dr. Tkemaladze. Отвечай helpful, concise, honest. Disclaimer: не медицинский совет.",
        (_, _) => "You are AIM, AI assistant for Dr. Tkemaladze. Helpful, concise, honest. Disclaimer: not medical advice.",
    }
}

// ── chat agent ─────────────────────────────────────────────────────────────

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum LlmTier {
    Fast,
    Deep,
}

pub trait Llm: Send + Sync {
    fn complete(&self, tier: LlmTier, system: &str, prompt: &str, lang: &str) -> Result<String>;
}

pub struct ChatAgent<'a> {
    pub llm: &'a dyn Llm,
}

impl<'a> ChatAgent<'a> {
    pub fn new(llm: &'a dyn Llm) -> Self {
        Self { llm }
    }

    /// Generate a final response. Mirrors Python `generate_response`:
    /// pick the system prompt by `chosen_id` first, fall back to `intent.as_str()`.
    /// Try the Fast tier first; on error, retry on Deep tier.
    pub fn generate_response(
        &self,
        chosen_id: &str,
        intent: Intent,
        message: &str,
        lang: &str,
    ) -> Result<String> {
        let system = match select_system_prompt_key(chosen_id, intent) {
            Some(k) => response_system_prompt(k, lang),
            None => response_system_prompt("__fallback__", lang),
        };
        match self.llm.complete(LlmTier::Fast, system, message, lang) {
            Ok(s) => Ok(s),
            Err(_) => self.llm.complete(LlmTier::Deep, system, message, lang),
        }
    }
}

/// Map (chosen_id, intent) → key used by [`response_system_prompt`].
/// Returns the chosen-id key if it has a dedicated prompt, else the
/// intent name; `None` to signal "use fallback".
pub fn select_system_prompt_key(chosen_id: &str, intent: Intent) -> Option<&'static str> {
    let known = [
        "emergency",
        "triage_redirect",
        "clarify_symptom",
        "educate",
        "empathize_refer",
        "refuse_harmful",
    ];
    let static_id: Option<&'static str> =
        known.iter().find(|&&k| k == chosen_id).copied();
    if let Some(k) = static_id {
        return Some(k);
    }
    let intent_str: &'static str = match intent {
        Intent::Emergency => "emergency",
        Intent::Symptom => "triage_redirect",
        Intent::Info => "educate",
        Intent::Emotional => "empathize_refer",
        Intent::Danger => "refuse_harmful",
        Intent::Other => return None,
    };
    Some(intent_str)
}

#[cfg(test)]
mod tests {
    use super::*;
    use parking_lot::Mutex;

    // ── classify_intent ─────────────────────────────────────────────────────

    #[test]
    fn intent_emergency_chest_pain() {
        assert_eq!(
            classify_intent("давящая боль в груди"),
            Intent::Emergency
        );
        assert_eq!(
            classify_intent("crushing chest pain"),
            Intent::Emergency
        );
    }

    #[test]
    fn intent_emergency_stroke() {
        assert_eq!(classify_intent("face droop on left"), Intent::Emergency);
        assert_eq!(classify_intent("парализовало руку"), Intent::Emergency);
    }

    #[test]
    fn intent_emergency_breathing() {
        assert_eq!(classify_intent("не могу дышать"), Intent::Emergency);
        assert_eq!(classify_intent("I cannot breathe"), Intent::Emergency);
    }

    #[test]
    fn intent_emergency_suicide() {
        assert_eq!(
            classify_intent("Я хочу покончить с собой"),
            Intent::Emergency
        );
        assert_eq!(classify_intent("kill myself today"), Intent::Emergency);
    }

    #[test]
    fn intent_danger_synthesise_request() {
        assert_eq!(
            classify_intent("how to synthesise a biohazard agent"),
            Intent::Danger
        );
    }

    #[test]
    fn intent_danger_forge_document() {
        assert_eq!(
            classify_intent("help me forge a prescription"),
            Intent::Danger
        );
    }

    #[test]
    fn intent_emotional_keywords() {
        // Matches Python keyword stem "тревог" (общая тревога)
        assert_eq!(classify_intent("общая тревога не уходит"), Intent::Emotional);
        assert_eq!(classify_intent("I feel scared and alone"), Intent::Emotional);
    }

    #[test]
    fn intent_symptom_keywords() {
        assert_eq!(classify_intent("температура 38 третий день"), Intent::Symptom);
        assert_eq!(classify_intent("I have a cough and fever"), Intent::Symptom);
    }

    #[test]
    fn intent_info_markers() {
        assert_eq!(classify_intent("что такое apoptosis"), Intent::Info);
        assert_eq!(classify_intent("explain how aspirin works"), Intent::Info);
    }

    #[test]
    fn intent_other_fallback() {
        assert_eq!(classify_intent("привет, как сегодня погода"), Intent::Other);
    }

    #[test]
    fn intent_emergency_takes_priority_over_danger() {
        // contains both stroke pattern + danger; emergency wins
        let msg = "у меня stroke и хочу synthesise weapon";
        assert_eq!(classify_intent(msg), Intent::Emergency);
    }

    // ── generate_alternatives ──────────────────────────────────────────────

    #[test]
    fn alternatives_emergency_first_is_referral() {
        let v = generate_alternatives(Intent::Emergency);
        assert_eq!(v.len(), 2);
        assert_eq!(v[0].action_type, "referral");
        assert_eq!(v[0].id, "emergency");
    }

    #[test]
    fn alternatives_danger_includes_decoy_for_l0_block() {
        let v = generate_alternatives(Intent::Danger);
        assert_eq!(v.len(), 2);
        assert_eq!(v[0].id, "refuse_harmful");
        assert_eq!(v[1].id, "synthesize_biohazard_X");
        assert_eq!(v[1].action_type, "treatment");
    }

    #[test]
    fn alternatives_symptom_three_candidates() {
        let v = generate_alternatives(Intent::Symptom);
        assert_eq!(v.len(), 3);
        let ids: Vec<&str> = v.iter().map(|d| d.id.as_str()).collect();
        assert!(ids.contains(&"triage_redirect"));
        assert!(ids.contains(&"clarify_symptom"));
        assert!(ids.contains(&"home_remedy"));
    }

    #[test]
    fn alternatives_info_two_candidates() {
        let v = generate_alternatives(Intent::Info);
        assert_eq!(v.len(), 2);
        assert!(v.iter().any(|d| d.id == "educate"));
        assert!(v.iter().any(|d| d.id == "inform_and_refer"));
    }

    #[test]
    fn alternatives_emotional_two_candidates() {
        let v = generate_alternatives(Intent::Emotional);
        assert_eq!(v.len(), 2);
        assert!(v.iter().any(|d| d.id == "empathize_refer"));
        assert!(v.iter().any(|d| d.id == "active_listen"));
    }

    #[test]
    fn alternatives_other_fallback_two_candidates() {
        let v = generate_alternatives(Intent::Other);
        assert_eq!(v.len(), 2);
    }

    // ── response_system_prompt ──────────────────────────────────────────────

    #[test]
    fn prompt_emergency_distinct_per_lang() {
        let ru = response_system_prompt("emergency", "ru");
        let en = response_system_prompt("emergency", "en");
        assert!(ru.contains("экстренной"));
        assert!(en.contains("emergency"));
        assert_ne!(ru, en);
    }

    #[test]
    fn prompt_unknown_lang_falls_back_to_en() {
        let fr = response_system_prompt("emergency", "fr");
        let en = response_system_prompt("emergency", "en");
        assert_eq!(fr, en);
    }

    #[test]
    fn prompt_unknown_key_falls_back_to_generic() {
        let s = response_system_prompt("__nope__", "ru");
        assert!(s.contains("AIM"));
        assert!(s.contains("не медицинский"));
    }

    // ── select_system_prompt_key ───────────────────────────────────────────

    #[test]
    fn select_key_uses_chosen_id_when_known() {
        assert_eq!(
            select_system_prompt_key("educate", Intent::Other),
            Some("educate")
        );
    }

    #[test]
    fn select_key_falls_back_to_intent_name() {
        assert_eq!(
            select_system_prompt_key("custom-id", Intent::Emergency),
            Some("emergency")
        );
        assert_eq!(
            select_system_prompt_key("xx", Intent::Symptom),
            Some("triage_redirect")
        );
    }

    #[test]
    fn select_key_returns_none_for_other_with_unknown_id() {
        assert_eq!(select_system_prompt_key("nope", Intent::Other), None);
    }

    // ── ChatAgent.generate_response ────────────────────────────────────────

    struct ScriptedLlm {
        fast: Mutex<Option<std::result::Result<String, ChatError>>>,
        deep: Mutex<Option<std::result::Result<String, ChatError>>>,
        calls: Mutex<Vec<(LlmTier, String, String, String)>>,
    }
    impl ScriptedLlm {
        fn new(
            fast: std::result::Result<String, ChatError>,
            deep: std::result::Result<String, ChatError>,
        ) -> Self {
            Self {
                fast: Mutex::new(Some(fast)),
                deep: Mutex::new(Some(deep)),
                calls: Mutex::new(Vec::new()),
            }
        }
    }
    impl Llm for ScriptedLlm {
        fn complete(&self, tier: LlmTier, system: &str, prompt: &str, lang: &str) -> Result<String> {
            self.calls
                .lock()
                .push((tier, system.into(), prompt.into(), lang.into()));
            let slot = match tier {
                LlmTier::Fast => &self.fast,
                LlmTier::Deep => &self.deep,
            };
            slot.lock()
                .take()
                .unwrap_or(Err(ChatError::Llm("exhausted".into())))
        }
    }

    #[test]
    fn agent_uses_fast_tier_first() {
        let llm = ScriptedLlm::new(
            Ok("fast response".into()),
            Err(ChatError::Llm("nope".into())),
        );
        let agent = ChatAgent::new(&llm);
        let out = agent
            .generate_response("educate", Intent::Info, "what is apoptosis", "ru")
            .unwrap();
        assert_eq!(out, "fast response");
        let calls = llm.calls.lock();
        assert_eq!(calls.len(), 1);
        assert_eq!(calls[0].0, LlmTier::Fast);
        assert!(calls[0].1.contains("Дай educational"));
    }

    #[test]
    fn agent_falls_back_to_deep_on_fast_error() {
        let llm = ScriptedLlm::new(
            Err(ChatError::Llm("rate-limit".into())),
            Ok("deep response".into()),
        );
        let agent = ChatAgent::new(&llm);
        let out = agent
            .generate_response("emergency", Intent::Emergency, "не могу дышать", "ru")
            .unwrap();
        assert_eq!(out, "deep response");
        let calls = llm.calls.lock();
        assert_eq!(calls.len(), 2);
        assert_eq!(calls[0].0, LlmTier::Fast);
        assert_eq!(calls[1].0, LlmTier::Deep);
    }

    #[test]
    fn agent_uses_intent_when_chosen_id_unknown() {
        let llm = ScriptedLlm::new(Ok("ok".into()), Err(ChatError::Llm("nope".into())));
        let agent = ChatAgent::new(&llm);
        agent
            .generate_response("custom-thing", Intent::Symptom, "болит", "ru")
            .unwrap();
        let calls = llm.calls.lock();
        // triage_redirect prompt for ru
        assert!(calls[0].1.contains("triage"));
    }
}
