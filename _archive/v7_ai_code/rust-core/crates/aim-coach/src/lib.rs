//! aim-coach — motivational interviewing patterns + goal-setting
//! (Phase 4 of "Patient as a Project" cornerstone, scaffolded 2026-05-07).
//!
//! This is the *non-LLM* core of the coaching loop: it knows MI's
//! Open-question / Affirmation / Reflective-listening / Summary
//! framework (OARS), how to detect "change talk" vs "sustain talk" in
//! patient utterances, and how to manage an ongoing list of
//! `CoachingGoal`s. The actual prompt construction + LLM call lives
//! in callers (Python `agents/coach.py` shim, or future Phoenix
//! LiveView), so this crate stays unit-testable without a network.
//!
//! References:
//!   - Miller WR & Rollnick S, Motivational Interviewing (Guilford 2013)
//!   - Tao et al., Nat Med 2026 — co-design > fine-tuning for L3
//!     patient engagement.

use chrono::NaiveDate;
use serde::{Deserialize, Serialize};
use thiserror::Error;

pub use aim_patient_memory::{ActivationPoint, CoachingGoal};

#[derive(Debug, Error)]
pub enum CoachError {
    #[error("empty patient utterance")]
    EmptyUtterance,
    #[error("activation level {0} out of range 0..=4")]
    InvalidActivationLevel(u8),
}

/// Output of `classify_utterance` — coarse OARS-relevant labels for
/// what the patient just said. Used to pick the next coaching move.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum UtteranceKind {
    /// "Change talk" — desire / ability / reason / need to change.
    /// MI: amplify, reflect, summarise.
    ChangeTalk,
    /// "Sustain talk" — arguments AGAINST changing.
    /// MI: do not argue; explore ambivalence.
    SustainTalk,
    /// Status / informational with no commitment direction.
    Neutral,
    /// Resistance / discord (frustrated, blaming, refusing).
    /// MI: roll with resistance; reframe.
    Resistance,
}

const CHANGE_MARKERS: &[&str] = &[
    "хочу", "буду", "попробую", "i want", "i'll", "i will",
    "i can", "я смогу", "готов", "ready", "going to", "decided",
    "planning", "let me", "давайте",
];

const SUSTAIN_MARKERS: &[&str] = &[
    "не могу", "не получится", "сложно", "тяжело",
    "i can't", "won't work", "too hard", "no time",
    "невозможно", "уже пробовал", "tried before",
];

const RESISTANCE_MARKERS: &[&str] = &[
    "вы не понимаете", "это бесполезно", "оставьте меня",
    "you don't understand", "useless", "leave me alone",
    "почему я должен", "why should i",
];

/// Coarse classifier — looks for change/sustain/resistance markers
/// in a normalized lowercase utterance. Not a substitute for an LLM
/// classifier but useful as a deterministic gate before paying for
/// an LLM call (and as a fallback when LLM is unavailable).
pub fn classify_utterance(utterance: &str) -> Result<UtteranceKind, CoachError> {
    let text = utterance.trim();
    if text.is_empty() {
        return Err(CoachError::EmptyUtterance);
    }
    let lc = text.to_lowercase();
    if RESISTANCE_MARKERS.iter().any(|m| lc.contains(m)) {
        return Ok(UtteranceKind::Resistance);
    }
    let has_change = CHANGE_MARKERS.iter().any(|m| lc.contains(m));
    let has_sustain = SUSTAIN_MARKERS.iter().any(|m| lc.contains(m));
    Ok(match (has_change, has_sustain) {
        (true, false) => UtteranceKind::ChangeTalk,
        (false, true) => UtteranceKind::SustainTalk,
        _ => UtteranceKind::Neutral,
    })
}

/// OARS move — what the coach should do NEXT.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CoachMove {
    /// Open-ended question (e.g., "What would change look like for you?")
    OpenQuestion,
    /// Affirmation of the patient's strengths / progress.
    Affirmation,
    /// Reflective listening — restate what the patient said.
    Reflection,
    /// Summarise the conversation so far.
    Summary,
    /// Roll with resistance — reframe, do not push.
    RollWithResistance,
    /// Patient is at level 1 (disengaged) — start with rapport-building,
    /// not change-focused MI.
    BuildRapport,
}

/// Pick the next coaching move given the patient's utterance kind +
/// current activation level (PAM-13).
pub fn next_move(
    utterance: UtteranceKind,
    activation_level: u8,
) -> Result<CoachMove, CoachError> {
    if activation_level > 4 {
        return Err(CoachError::InvalidActivationLevel(activation_level));
    }
    // Level 0/1 → focus on rapport before MI techniques.
    if activation_level <= 1 && utterance != UtteranceKind::Resistance {
        return Ok(CoachMove::BuildRapport);
    }
    Ok(match utterance {
        UtteranceKind::ChangeTalk => CoachMove::Affirmation,
        UtteranceKind::SustainTalk => CoachMove::Reflection,
        UtteranceKind::Resistance => CoachMove::RollWithResistance,
        UtteranceKind::Neutral => CoachMove::OpenQuestion,
    })
}

/// Build the system prompt for an LLM coach. The caller (Python
/// `agents/coach.py` or Phoenix LiveView) sends this + recent
/// conversation history to `aim-llm /v1/chat`.
pub fn coach_system_prompt(language: &str) -> String {
    let preamble = match language {
        "ru" => "Ты — коуч-тренер по поведенческим изменениям, использующий технику \
                «мотивационного интервью» (Miller & Rollnick).",
        _ => "You are a behavioural-change coach using motivational interviewing \
              (Miller & Rollnick).",
    };
    format!(
        "{preamble}\n\n\
RULES:\n\
1. Use OARS: Open questions, Affirmations, Reflective listening, Summaries.\n\
2. NEVER argue, lecture, or push. Roll with resistance.\n\
3. Ask exactly ONE open question per turn; keep replies under 80 words.\n\
4. Reflect change talk back to amplify it. Do not amplify sustain talk.\n\
5. Ask permission before giving information: \"Would it be helpful if I...?\"\n\
6. Honour the patient's autonomy. Their goals are theirs."
    )
}

// ── goal management ───────────────────────────────────────────────────────

/// Add a new coaching goal. Returns the goal back so the caller can
/// persist it (e.g., via `PatientMemory.coaching_goals`).
pub fn new_goal(id: impl Into<String>, target: impl Into<String>, set_at: NaiveDate) -> CoachingGoal {
    CoachingGoal {
        id: id.into(),
        target: target.into(),
        set_at,
        achieved: None,
    }
}

/// Mark a goal as achieved. Returns `true` if the goal was found.
pub fn mark_achieved(
    goals: &mut Vec<CoachingGoal>,
    goal_id: &str,
    achieved_at: NaiveDate,
) -> bool {
    if let Some(g) = goals.iter_mut().find(|g| g.id == goal_id) {
        if g.achieved.is_none() {
            g.achieved = Some(achieved_at);
        }
        return true;
    }
    false
}

/// Filter active (not-yet-achieved) goals.
pub fn active_goals(goals: &[CoachingGoal]) -> Vec<&CoachingGoal> {
    goals.iter().filter(|g| g.achieved.is_none()).collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn classify_change_talk() {
        let k = classify_utterance("я хочу попробовать ходить по 30 минут").unwrap();
        assert_eq!(k, UtteranceKind::ChangeTalk);
    }

    #[test]
    fn classify_sustain_talk() {
        let k = classify_utterance("это слишком сложно, я не могу").unwrap();
        assert_eq!(k, UtteranceKind::SustainTalk);
    }

    #[test]
    fn classify_resistance() {
        let k = classify_utterance("вы не понимаете, оставьте меня").unwrap();
        assert_eq!(k, UtteranceKind::Resistance);
    }

    #[test]
    fn classify_neutral() {
        let k = classify_utterance("я ел овсянку на завтрак").unwrap();
        assert_eq!(k, UtteranceKind::Neutral);
    }

    #[test]
    fn classify_rejects_empty() {
        let err = classify_utterance("   ").unwrap_err();
        assert!(matches!(err, CoachError::EmptyUtterance));
    }

    #[test]
    fn next_move_change_talk_l3_is_affirmation() {
        let m = next_move(UtteranceKind::ChangeTalk, 3).unwrap();
        assert_eq!(m, CoachMove::Affirmation);
    }

    #[test]
    fn next_move_sustain_talk_l3_is_reflection() {
        let m = next_move(UtteranceKind::SustainTalk, 3).unwrap();
        assert_eq!(m, CoachMove::Reflection);
    }

    #[test]
    fn next_move_resistance_overrides_level() {
        // even at L1, resistance gets RollWith, not BuildRapport.
        let m = next_move(UtteranceKind::Resistance, 1).unwrap();
        assert_eq!(m, CoachMove::RollWithResistance);
    }

    #[test]
    fn next_move_l1_disengaged_builds_rapport() {
        let m = next_move(UtteranceKind::ChangeTalk, 1).unwrap();
        assert_eq!(m, CoachMove::BuildRapport);
        let m = next_move(UtteranceKind::Neutral, 0).unwrap();
        assert_eq!(m, CoachMove::BuildRapport);
    }

    #[test]
    fn next_move_l4_neutral_is_open_question() {
        let m = next_move(UtteranceKind::Neutral, 4).unwrap();
        assert_eq!(m, CoachMove::OpenQuestion);
    }

    #[test]
    fn next_move_rejects_out_of_range() {
        let err = next_move(UtteranceKind::Neutral, 99).unwrap_err();
        assert!(matches!(err, CoachError::InvalidActivationLevel(99)));
    }

    #[test]
    fn coach_system_prompt_has_oars_rules() {
        let p = coach_system_prompt("en");
        assert!(p.contains("OARS"));
        assert!(p.contains("autonomy"));
        let pr = coach_system_prompt("ru");
        assert!(pr.contains("мотивационного интервью"));
    }

    #[test]
    fn new_goal_creates_active() {
        let d = NaiveDate::from_ymd_opt(2026, 5, 7).unwrap();
        let g = new_goal("g1", "walk 30 min daily", d);
        assert_eq!(g.id, "g1");
        assert!(g.achieved.is_none());
    }

    #[test]
    fn mark_achieved_updates_goal() {
        let d = NaiveDate::from_ymd_opt(2026, 5, 7).unwrap();
        let d2 = NaiveDate::from_ymd_opt(2026, 5, 14).unwrap();
        let mut goals = vec![new_goal("g1", "walk", d)];
        assert!(mark_achieved(&mut goals, "g1", d2));
        assert_eq!(goals[0].achieved, Some(d2));
    }

    #[test]
    fn mark_achieved_idempotent() {
        let d = NaiveDate::from_ymd_opt(2026, 5, 7).unwrap();
        let d2 = NaiveDate::from_ymd_opt(2026, 5, 14).unwrap();
        let d3 = NaiveDate::from_ymd_opt(2026, 5, 21).unwrap();
        let mut goals = vec![new_goal("g1", "walk", d)];
        mark_achieved(&mut goals, "g1", d2);
        mark_achieved(&mut goals, "g1", d3);
        // First-write wins.
        assert_eq!(goals[0].achieved, Some(d2));
    }

    #[test]
    fn mark_achieved_unknown_returns_false() {
        let mut goals = vec![];
        let d = NaiveDate::from_ymd_opt(2026, 5, 7).unwrap();
        assert!(!mark_achieved(&mut goals, "nonexistent", d));
    }

    #[test]
    fn active_goals_filters_achieved() {
        let d = NaiveDate::from_ymd_opt(2026, 5, 7).unwrap();
        let d2 = NaiveDate::from_ymd_opt(2026, 5, 14).unwrap();
        let mut goals = vec![
            new_goal("g1", "walk", d),
            new_goal("g2", "sleep 8h", d),
        ];
        mark_achieved(&mut goals, "g1", d2);
        let active = active_goals(&goals);
        assert_eq!(active.len(), 1);
        assert_eq!(active[0].id, "g2");
    }
}
