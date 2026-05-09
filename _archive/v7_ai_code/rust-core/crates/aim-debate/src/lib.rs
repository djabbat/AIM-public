//! aim-debate — multi-persona debate for high-stakes decisions.
//!
//! Port of `agents/debate.py`. Three personas (Оптимист / Пессимист /
//! Реалист) argue across N rounds, each round consuming the others'
//! prior-round opinions; a final synthesiser produces a reasoned verdict
//! consolidating the three positions.
//!
//! ## Public API
//! - [`debate`] / [`debate_serial`] — async drivers with pluggable
//!   [`PersonaLlm`] + [`SynthesisLlm`] traits
//! - [`PERSONAS`] — the canonical RU prompt set
//! - [`Persona`] — one persona's role description

use async_trait::async_trait;
use parking_lot::Mutex;
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum DebateError {
    #[error("persona '{0}': {1}")]
    Persona(String, String),
    #[error("synthesis: {0}")]
    Synthesis(String),
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct Persona {
    pub name: String,
    pub role: String,
}

/// The Russian-language persona set from `agents/debate.py`. Order is
/// preserved (BTreeMap-style insertion) so the synthesiser sees the same
/// participants across rounds.
pub fn personas() -> Vec<Persona> {
    vec![
        Persona {
            name: "Оптимист".into(),
            role: "Ты ищешь возможности и плюсы. Аргументируй за «да», но честно (не рекламируй).".into(),
        },
        Persona {
            name: "Пессимист".into(),
            role: "Ты ищешь риски и слабости. Аргументируй за «нет» / «осторожно», но честно (не запугивай).".into(),
        },
        Persona {
            name: "Реалист".into(),
            role: "Ты взвешиваешь факты, числа, временные ограничения. Делай ставку на вероятности.".into(),
        },
    ]
}

/// Pluggable LLM for individual persona turns.
#[async_trait]
pub trait PersonaLlm: Send + Sync {
    /// Called per persona, per round. `system` is the canonical debate
    /// system prompt; tests can ignore it.
    async fn ask(&self, prompt: &str, system: &str) -> Result<String, DebateError>;
}

/// Pluggable LLM for the final synthesis (typically a higher tier).
#[async_trait]
pub trait SynthesisLlm: Send + Sync {
    async fn synthesise(&self, prompt: &str, system: &str) -> Result<String, DebateError>;
}

const SYSTEM_PERSONA: &str = "Ты участник дебатов. Отвечай по существу, на русском.";
const SYSTEM_SYNTH: &str = "Ты модератор дебатов. Отвечай на русском.";

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DebateResult {
    pub question: String,
    pub rounds: u32,
    /// Final round opinions keyed by persona name (insertion order
    /// preserved via Vec of pairs to match the Python dict shape).
    pub opinions: Vec<(String, String)>,
    /// Round-by-round snapshot, length = rounds.
    pub history: Vec<Vec<(String, String)>>,
    pub synthesis: String,
}

fn build_persona_prompt(
    role: &str,
    question: &str,
    self_name: &str,
    prior: &BTreeMap<String, String>,
) -> String {
    let mut lines: Vec<String> = prior
        .iter()
        .filter(|(k, _)| k.as_str() != self_name)
        .filter(|(_, v)| !v.is_empty())
        .map(|(k, v)| format!("  {k}: {v}"))
        .collect();
    let prior_block = if lines.is_empty() {
        "  (это первый раунд)".to_string()
    } else {
        lines.sort();
        lines.join("\n")
    };
    format!(
        "ВОПРОС:\n{question}\n\n━━━ ИНСТРУКЦИЯ ━━━\nТвоя роль: {role}\nВысказывания других участников:\n{prior_block}\n\nДай свой ответ за 2–4 предложения. Кратко. Без преамбул. Без воды."
    )
}

fn build_synthesis_prompt(question: &str, opinions: &BTreeMap<String, String>) -> String {
    let mut block = String::new();
    for (n, t) in opinions {
        block.push_str(&format!("{n}: {t}\n"));
    }
    format!(
        "ВОПРОС:\n{question}\n\n━━━ МНЕНИЯ ━━━\n{block}\n━━━ ИНСТРУКЦИЯ (СИНТЕЗ) ━━━\nУчти все три позиции. Найди реальную точку согласия (если есть) и реальные расхождения. Дай взвешенное решение в 4–7 предложений: рекомендация + 1 ключевой аргумент + 1 ключевой риск."
    )
}

/// Run `rounds` debate rounds in **parallel** within each round, then
/// produce a synthesis. Personas come from [`personas()`] and each one's
/// turn calls `persona_llm.ask` concurrently — matching the Python
/// `ThreadPoolExecutor(max_workers=3)`.
pub async fn debate(
    question: &str,
    rounds: u32,
    persona_llm: std::sync::Arc<dyn PersonaLlm>,
    synth_llm: &dyn SynthesisLlm,
) -> Result<DebateResult, DebateError> {
    let personas = personas();
    let mut opinions: BTreeMap<String, String> = personas
        .iter()
        .map(|p| (p.name.clone(), String::new()))
        .collect();
    let mut history: Vec<Vec<(String, String)>> = Vec::with_capacity(rounds as usize);

    for r in 0..rounds {
        tracing::info!("[debate] round {}/{}", r + 1, rounds);
        let mut tasks = Vec::with_capacity(personas.len());
        let prior = opinions.clone();
        for persona in &personas {
            let llm = persona_llm.clone();
            let prompt = build_persona_prompt(&persona.role, question, &persona.name, &prior);
            let name = persona.name.clone();
            tasks.push(tokio::spawn(async move {
                match llm.ask(&prompt, SYSTEM_PERSONA).await {
                    Ok(t) => Ok((name, t)),
                    Err(e) => Err(e),
                }
            }));
        }
        for task in tasks {
            match task.await {
                Ok(Ok((name, text))) => {
                    opinions.insert(name, text);
                }
                Ok(Err(e)) => return Err(e),
                Err(e) => {
                    return Err(DebateError::Persona("(join)".into(), e.to_string()));
                }
            }
        }
        history.push(opinions_to_pairs(&opinions, &personas));
    }

    let synth_prompt = build_synthesis_prompt(question, &opinions);
    let synthesis = synth_llm.synthesise(&synth_prompt, SYSTEM_SYNTH).await?;

    Ok(DebateResult {
        question: question.to_string(),
        rounds,
        opinions: opinions_to_pairs(&opinions, &personas),
        history,
        synthesis,
    })
}

/// Sequential variant — useful when the LLM provider rate-limits.
pub async fn debate_serial(
    question: &str,
    rounds: u32,
    persona_llm: &dyn PersonaLlm,
    synth_llm: &dyn SynthesisLlm,
) -> Result<DebateResult, DebateError> {
    let personas = personas();
    let mut opinions: BTreeMap<String, String> = personas
        .iter()
        .map(|p| (p.name.clone(), String::new()))
        .collect();
    let mut history: Vec<Vec<(String, String)>> = Vec::with_capacity(rounds as usize);

    for r in 0..rounds {
        tracing::info!("[debate-serial] round {}/{}", r + 1, rounds);
        let prior = opinions.clone();
        for persona in &personas {
            let prompt = build_persona_prompt(&persona.role, question, &persona.name, &prior);
            let text = persona_llm.ask(&prompt, SYSTEM_PERSONA).await?;
            opinions.insert(persona.name.clone(), text);
        }
        history.push(opinions_to_pairs(&opinions, &personas));
    }

    let synth_prompt = build_synthesis_prompt(question, &opinions);
    let synthesis = synth_llm.synthesise(&synth_prompt, SYSTEM_SYNTH).await?;

    Ok(DebateResult {
        question: question.to_string(),
        rounds,
        opinions: opinions_to_pairs(&opinions, &personas),
        history,
        synthesis,
    })
}

fn opinions_to_pairs(
    opinions: &BTreeMap<String, String>,
    personas: &[Persona],
) -> Vec<(String, String)> {
    personas
        .iter()
        .map(|p| {
            (
                p.name.clone(),
                opinions.get(&p.name).cloned().unwrap_or_default(),
            )
        })
        .collect()
}

// ── stubs for tests ────────────────────────────────────────────────────────

pub struct ScriptedPersonaLlm {
    /// Per-call response queue. Each `ask()` pops the front.
    pub queue: Mutex<Vec<String>>,
}

impl ScriptedPersonaLlm {
    pub fn new(responses: Vec<&str>) -> Self {
        Self {
            queue: Mutex::new(responses.into_iter().map(String::from).collect()),
        }
    }
}

#[async_trait]
impl PersonaLlm for ScriptedPersonaLlm {
    async fn ask(&self, _prompt: &str, _system: &str) -> Result<String, DebateError> {
        let mut q = self.queue.lock();
        if q.is_empty() {
            return Err(DebateError::Persona(
                "scripted".into(),
                "queue exhausted".into(),
            ));
        }
        Ok(q.remove(0))
    }
}

pub struct ScriptedSynthLlm {
    pub answer: String,
}

impl ScriptedSynthLlm {
    pub fn new(answer: impl Into<String>) -> Self {
        Self {
            answer: answer.into(),
        }
    }
}

#[async_trait]
impl SynthesisLlm for ScriptedSynthLlm {
    async fn synthesise(&self, _prompt: &str, _system: &str) -> Result<String, DebateError> {
        Ok(self.answer.clone())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Arc;

    #[test]
    fn personas_canonical_set() {
        let p = personas();
        assert_eq!(p.len(), 3);
        let names: Vec<&str> = p.iter().map(|x| x.name.as_str()).collect();
        assert_eq!(names, vec!["Оптимист", "Пессимист", "Реалист"]);
    }

    #[test]
    fn build_persona_prompt_first_round() {
        let prior: BTreeMap<String, String> = personas()
            .iter()
            .map(|p| (p.name.clone(), String::new()))
            .collect();
        let prompt = build_persona_prompt(
            "Ты ищешь возможности и плюсы.",
            "Стоит ли публиковать сейчас?",
            "Оптимист",
            &prior,
        );
        assert!(prompt.contains("(это первый раунд)"));
        assert!(prompt.contains("Стоит ли публиковать сейчас?"));
        assert!(prompt.contains("Твоя роль"));
    }

    #[test]
    fn build_persona_prompt_excludes_self() {
        let mut prior: BTreeMap<String, String> = BTreeMap::new();
        prior.insert("Оптимист".into(), "За — преимущества X".into());
        prior.insert("Пессимист".into(), "Против — риск Y".into());
        prior.insert("Реалист".into(), "Половинчато — Z".into());
        let prompt = build_persona_prompt("...", "Q?", "Оптимист", &prior);
        // Self should NOT appear, others should
        assert!(!prompt.contains("За — преимущества X"));
        assert!(prompt.contains("Против — риск Y"));
        assert!(prompt.contains("Половинчато — Z"));
    }

    #[test]
    fn build_synthesis_prompt_includes_all_opinions() {
        let mut opinions: BTreeMap<String, String> = BTreeMap::new();
        opinions.insert("Оптимист".into(), "За".into());
        opinions.insert("Пессимист".into(), "Против".into());
        opinions.insert("Реалист".into(), "Возможно".into());
        let p = build_synthesis_prompt("Q?", &opinions);
        assert!(p.contains("За"));
        assert!(p.contains("Против"));
        assert!(p.contains("Возможно"));
        assert!(p.contains("СИНТЕЗ"));
    }

    #[tokio::test]
    async fn debate_runs_three_personas_per_round() {
        // 3 personas × 2 rounds = 6 calls
        let llm = Arc::new(ScriptedPersonaLlm::new(vec![
            "opt-r1", "pes-r1", "rea-r1", "opt-r2", "pes-r2", "rea-r2",
        ]));
        let synth = ScriptedSynthLlm::new("FINAL VERDICT");
        let r = debate("Стоит ли?", 2, llm, &synth).await.unwrap();
        assert_eq!(r.rounds, 2);
        assert_eq!(r.history.len(), 2);
        assert_eq!(r.synthesis, "FINAL VERDICT");
        // Final-round opinions reflect r2 responses
        let final_map: BTreeMap<_, _> = r.opinions.iter().cloned().collect();
        assert!(final_map.values().any(|v| v.ends_with("r2")));
    }

    #[tokio::test]
    async fn debate_serial_round_trip() {
        let llm = ScriptedPersonaLlm::new(vec!["a", "b", "c"]);
        let synth = ScriptedSynthLlm::new("done");
        let r = debate_serial("Q", 1, &llm, &synth).await.unwrap();
        assert_eq!(r.rounds, 1);
        assert_eq!(r.opinions.len(), 3);
        assert!(r.opinions.iter().any(|(_, v)| v == "a"));
        assert!(r.opinions.iter().any(|(_, v)| v == "b"));
        assert!(r.opinions.iter().any(|(_, v)| v == "c"));
    }

    #[tokio::test]
    async fn debate_propagates_persona_error() {
        let llm = Arc::new(ScriptedPersonaLlm::new(vec!["a"])); // exhausts after 1
        let synth = ScriptedSynthLlm::new("nope");
        let r = debate("Q", 1, llm, &synth).await;
        assert!(matches!(r, Err(DebateError::Persona(_, _))));
    }

    #[tokio::test]
    async fn history_preserves_round_snapshots() {
        let llm = Arc::new(ScriptedPersonaLlm::new(vec![
            "r1-opt", "r1-pes", "r1-rea", "r2-opt", "r2-pes", "r2-rea",
        ]));
        let synth = ScriptedSynthLlm::new("verdict");
        let r = debate("Q", 2, llm, &synth).await.unwrap();
        let r1: BTreeMap<_, _> = r.history[0].iter().cloned().collect();
        let r2: BTreeMap<_, _> = r.history[1].iter().cloned().collect();
        assert!(r1.values().any(|v| v.starts_with("r1")));
        assert!(r2.values().any(|v| v.starts_with("r2")));
        assert!(!r1.values().any(|v| v.starts_with("r2")));
    }
}
