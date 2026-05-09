//! aim-patient-memory — markdown-canonical patient state.
//!
//! Port of `agents/patient_memory.py`. Format: `Patients/<ID>/MEMORY.md`
//! is the human-editable canonical store. SQLite index lives behind a
//! pluggable [`PatientIndex`] trait so the markdown round-trip is testable
//! without sqlite.

use std::path::{Path, PathBuf};

use chrono::{DateTime, NaiveDate, Utc};
use regex::Regex;
use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum PatientError {
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
    #[error("not found: {0}")]
    NotFound(String),
}

pub type Result<T> = std::result::Result<T, PatientError>;

// ── data ────────────────────────────────────────────────────────────────────

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct Demographics {
    pub age: Option<i32>,
    pub sex: Option<String>,
    pub country: Option<String>,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct Medication {
    pub name: String,
    pub dose: Option<String>,
    pub freq: Option<String>,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct Condition {
    pub dx: String,
    pub since: Option<String>,
    pub notes: Option<String>,
}

/// Patient milestone — clinical task with a deadline.
///
/// Phase A (HW1, 2026-05-06). Mirrors `aim-project-owner::Milestone`
/// but for patient context (next thyroid check, next CTBA, etc.).
#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct Milestone {
    pub id: String,
    pub deadline: Option<NaiveDate>,
    /// "pending" | "done" | "blocked"
    pub status: String,
    pub blockers: Vec<String>,
    /// "low" | "medium" | "high"
    pub criticality: String,
}

impl Milestone {
    pub fn days_to_deadline(&self, today: NaiveDate) -> Option<i64> {
        self.deadline.map(|d| (d - today).num_days())
    }

    pub fn is_hot(&self, today: NaiveDate) -> bool {
        if self.status != "pending" {
            return false;
        }
        let Some(d) = self.days_to_deadline(today) else {
            return false;
        };
        d <= 7 || (self.criticality == "high" && d <= 14)
    }
}

/// Awaiting follow-up (lab result, referral reply, patient call-back).
///
/// Phase A (HW1, 2026-05-06). Captures non-milestone items the doctor
/// is waiting on — distinct from project-style stakeholders because
/// the "stakeholder" here is the patient themselves or a downstream
/// service.
#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct Awaiting {
    pub topic: String,
    pub since: Option<NaiveDate>,
    pub expected_by: Option<NaiveDate>,
}

impl Awaiting {
    pub fn days_silent(&self, today: NaiveDate) -> Option<i64> {
        self.since.map(|d| (today - d).num_days())
    }

    pub fn overdue(&self, today: NaiveDate) -> bool {
        match self.expected_by {
            Some(d) => today > d,
            None => false,
        }
    }
}

/// Patient Activation Measure (PAM-13) data point.
///
/// Phase 2 cornerstone (HW1, 2026-05-07). Per "Patient as a Project"
/// manuscript: developmental agency operationalised via PAM-13.
/// MCID = 5.4 points (95% CI 3.4–7.4) for CKD population
/// (Kidney Int Rep 2025;10(7):2275-2283). Levels per Insignia Health:
/// 1 (disengaged), 2 (becoming aware), 3 (taking action), 4 (maintaining).
#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct ActivationPoint {
    pub date: NaiveDate,
    pub score: f64,
    /// 1-4 per PAM-13 categorization
    pub level: u8,
}

/// Patient coaching goal (developmental agency target).
///
/// Phase 2 cornerstone (HW1, 2026-05-07). Coaching goals are
/// **co-designed with the patient**, not unilaterally set by AI.
/// Per Tao et al. (Nat Med 2026): co-design > fine-tuning.
#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct CoachingGoal {
    pub id: String,
    pub target: String,
    pub set_at: NaiveDate,
    pub achieved: Option<NaiveDate>,
}

impl CoachingGoal {
    pub fn is_achieved(&self) -> bool {
        self.achieved.is_some()
    }
}

/// PAM-13 minimal clinically important difference (Kidney Int Rep 2025).
pub const PAM_MCID: f64 = 5.4;

/// PAM-13 minimal detectable change at individual level.
pub const PAM_MDC: f64 = 7.2;

/// Categorize a PAM-13 raw score into level 1-4 per Insignia Health.
pub fn pam_level_from_score(score: f64) -> u8 {
    match score {
        s if s < 47.0 => 1,
        s if s < 55.1 => 2,
        s if s < 67.0 => 3,
        _ => 4,
    }
}

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct PatientMemory {
    pub id: String,
    pub demographics: Demographics,
    pub allergies: Vec<String>,
    pub medications: Vec<Medication>,
    pub conditions: Vec<Condition>,
    pub history: Vec<String>,
    pub known_unknowns: Vec<String>,
    pub red_flags: Vec<String>,
    pub missing_labs_count: i32,
    pub history_contradictions: i32,
    pub unexplained_symptoms_count: i32,
    pub last_visit_years_ago: f64,
    pub dx_without_evidence: bool,
    pub primary_complaint_undiagnosed: bool,
    pub has_confirmed_dx: bool,
    /// Phase A (HW1, 2026-05-06): clinical phase ID, validated by
    /// `aim-patient-state-machine`. Default "INTAKE" for new patients.
    #[serde(default = "default_phase")]
    pub phase: String,
    #[serde(default)]
    pub milestones: Vec<Milestone>,
    #[serde(default)]
    pub awaiting: Vec<Awaiting>,
    /// Phase 2 cornerstone (2026-05-07): PAM-13 longitudinal trajectory.
    #[serde(default)]
    pub activation_history: Vec<ActivationPoint>,
    /// Latest score from `activation_history` for fast access.
    #[serde(default)]
    pub current_activation_score: Option<f64>,
    /// Latest level (1-4) from `activation_history`.
    #[serde(default)]
    pub current_activation_level: Option<u8>,
    /// Co-designed coaching goals (developmental agency targets).
    #[serde(default)]
    pub coaching_goals: Vec<CoachingGoal>,
}

fn default_phase() -> String {
    "INTAKE".into()
}

impl PatientMemory {
    pub fn new(id: impl Into<String>) -> Self {
        Self {
            id: id.into(),
            primary_complaint_undiagnosed: true,
            phase: default_phase(),
            ..Default::default()
        }
    }

    /// Hot milestones for `today` — pending + within 7d (or 14d for
    /// high criticality).
    pub fn hot_milestones(&self, today: NaiveDate) -> Vec<&Milestone> {
        self.milestones.iter().filter(|m| m.is_hot(today)).collect()
    }

    /// Awaiting items past `expected_by`.
    pub fn overdue_awaiting(&self, today: NaiveDate) -> Vec<&Awaiting> {
        self.awaiting.iter().filter(|a| a.overdue(today)).collect()
    }

    /// Append a PAM-13 measurement; updates `current_activation_*` fields.
    pub fn record_activation(&mut self, date: NaiveDate, score: f64) {
        let level = pam_level_from_score(score);
        self.activation_history.push(ActivationPoint { date, score, level });
        self.current_activation_score = Some(score);
        self.current_activation_level = Some(level);
    }

    /// Delta between latest two activation points; None if <2 points.
    pub fn activation_delta(&self) -> Option<f64> {
        if self.activation_history.len() < 2 {
            return None;
        }
        let n = self.activation_history.len();
        Some(self.activation_history[n - 1].score - self.activation_history[n - 2].score)
    }

    /// True if the most recent delta exceeds MCID (5.4 pts).
    pub fn activation_clinically_improved(&self) -> bool {
        self.activation_delta().map(|d| d >= PAM_MCID).unwrap_or(false)
    }

    /// True if the most recent delta is a clinically significant decline.
    pub fn activation_clinically_declined(&self) -> bool {
        self.activation_delta().map(|d| d <= -PAM_MCID).unwrap_or(false)
    }

    /// Active coaching goals (not yet achieved).
    pub fn active_coaching_goals(&self) -> Vec<&CoachingGoal> {
        self.coaching_goals.iter().filter(|g| !g.is_achieved()).collect()
    }

    /// Flat dict shape for kernel scoring.
    pub fn to_kernel_json(&self) -> serde_json::Value {
        serde_json::json!({
            "id": self.id,
            "age": self.demographics.age,
            "sex": self.demographics.sex,
            "allergies": self.allergies,
            "medications": self.medications,
            "red_flags": self.red_flags,
            "missing_labs_count": self.missing_labs_count,
            "history_contradictions": self.history_contradictions,
            "unexplained_symptoms_count": self.unexplained_symptoms_count,
            "last_visit_years_ago": self.last_visit_years_ago,
            "dx_without_evidence": self.dx_without_evidence,
            "primary_complaint_undiagnosed": self.primary_complaint_undiagnosed,
            "has_confirmed_dx": self.has_confirmed_dx,
        })
    }
}

// ── markdown rendering ─────────────────────────────────────────────────────

pub const MEMORY_FILE: &str = "MEMORY.md";

fn bullets<I: IntoIterator<Item = S>, S: AsRef<str>>(items: I, empty: &str) -> String {
    let lines: Vec<String> = items
        .into_iter()
        .map(|s| format!("- {}", s.as_ref()))
        .collect();
    if lines.is_empty() {
        empty.to_string()
    } else {
        lines.join("\n")
    }
}

fn med_bullet(m: &Medication) -> String {
    format!(
        "- {} · {} · {}",
        if m.name.is_empty() { "?" } else { &m.name },
        m.dose.as_deref().unwrap_or("?"),
        m.freq.as_deref().unwrap_or("?")
    )
}

fn cond_bullet(c: &Condition) -> String {
    format!(
        "- {} ({}): {}",
        if c.dx.is_empty() { "?" } else { &c.dx },
        c.since.as_deref().unwrap_or("?"),
        c.notes.as_deref().unwrap_or("")
    )
}

/// Phase A (2026-05-06) — milestone bullet format:
///   `- <id> (<deadline?>, <criticality>): <status> [— <blockers>]`
/// e.g. `- thyroid-recheck (2026-08-15, medium): pending — TSH result`
fn milestone_bullet(m: &Milestone) -> String {
    let deadline = m
        .deadline
        .map(|d| d.format("%Y-%m-%d").to_string())
        .unwrap_or_else(|| "—".into());
    let crit = if m.criticality.is_empty() {
        "medium"
    } else {
        m.criticality.as_str()
    };
    let status = if m.status.is_empty() {
        "pending"
    } else {
        m.status.as_str()
    };
    let mut s = format!("- {} ({}, {}): {}", m.id, deadline, crit, status);
    if !m.blockers.is_empty() {
        s.push_str(" — ");
        s.push_str(&m.blockers.join(", "));
    }
    s
}

/// Phase A (2026-05-06) — awaiting bullet format:
///   `- <topic> (since <date?>, expected <date?>)`
/// e.g. `- repeat lab K+ (since 2026-05-06, expected 2026-05-13)`
/// Phase 2 cornerstone (2026-05-07) — activation history bullet:
///   `- <date>: <score> (level <N>)`
fn activation_bullet(a: &ActivationPoint) -> String {
    format!(
        "- {}: {:.1} (level {})",
        a.date.format("%Y-%m-%d"),
        a.score,
        a.level
    )
}

/// Phase 2 cornerstone (2026-05-07) — coaching goal bullet:
///   `- <id>: <target> (set <date>[, achieved <date>])`
fn coaching_goal_bullet(g: &CoachingGoal) -> String {
    let mut s = format!("- {}: {} (set {}", g.id, g.target, g.set_at.format("%Y-%m-%d"));
    if let Some(d) = g.achieved {
        s.push_str(&format!(", achieved {}", d.format("%Y-%m-%d")));
    }
    s.push(')');
    s
}

fn awaiting_bullet(a: &Awaiting) -> String {
    let mut parts: Vec<String> = Vec::new();
    if let Some(d) = a.since {
        parts.push(format!("since {}", d.format("%Y-%m-%d")));
    }
    if let Some(d) = a.expected_by {
        parts.push(format!("expected {}", d.format("%Y-%m-%d")));
    }
    if parts.is_empty() {
        format!("- {}", a.topic)
    } else {
        format!("- {} ({})", a.topic, parts.join(", "))
    }
}

pub fn render(mem: &PatientMemory, ts: DateTime<Utc>) -> String {
    let medications = if mem.medications.is_empty() {
        "_(none)_".to_string()
    } else {
        mem.medications
            .iter()
            .map(med_bullet)
            .collect::<Vec<_>>()
            .join("\n")
    };
    let conditions = if mem.conditions.is_empty() {
        "_(none)_".to_string()
    } else {
        mem.conditions
            .iter()
            .map(cond_bullet)
            .collect::<Vec<_>>()
            .join("\n")
    };
    let allergies = bullets(&mem.allergies, "_(none)_");
    let history = bullets(&mem.history, "_(none)_");
    let unknowns = bullets(&mem.known_unknowns, "_(none)_");
    let phase_str = if mem.phase.is_empty() {
        "INTAKE".to_string()
    } else {
        mem.phase.clone()
    };
    let milestones_block = if mem.milestones.is_empty() {
        "_(none)_".to_string()
    } else {
        mem.milestones
            .iter()
            .map(milestone_bullet)
            .collect::<Vec<_>>()
            .join("\n")
    };
    let awaiting_block = if mem.awaiting.is_empty() {
        "_(none)_".to_string()
    } else {
        mem.awaiting
            .iter()
            .map(awaiting_bullet)
            .collect::<Vec<_>>()
            .join("\n")
    };
    // Phase 2 cornerstone — PAM-13 activation + coaching goals.
    let activation_block = match (
        mem.current_activation_score,
        mem.current_activation_level,
    ) {
        (Some(score), Some(level)) => {
            let mut s = format!("- current_score: {:.1}\n- current_level: {}\n", score, level);
            if let Some(p) = mem.activation_history.last() {
                s.push_str(&format!("- last_measured: {}\n", p.date.format("%Y-%m-%d")));
            }
            s.push_str(&format!(
                "- mcid: {:.1}\n- mdc: {:.1}\n",
                PAM_MCID, PAM_MDC
            ));
            if !mem.activation_history.is_empty() {
                s.push_str("- history:\n");
                for p in &mem.activation_history {
                    s.push_str(&format!("  {}\n", activation_bullet(p)));
                }
            }
            s.trim_end().to_string()
        }
        _ => "_(not measured yet)_".to_string(),
    };
    let coaching_block = if mem.coaching_goals.is_empty() {
        "_(none)_".to_string()
    } else {
        mem.coaching_goals
            .iter()
            .map(coaching_goal_bullet)
            .collect::<Vec<_>>()
            .join("\n")
    };
    let age = mem
        .demographics
        .age
        .map(|n| n.to_string())
        .unwrap_or_else(|| "?".into());
    let sex = mem.demographics.sex.as_deref().unwrap_or("?");
    let country = mem.demographics.country.as_deref().unwrap_or("?");
    format!(
        "# Memory — {id}\n\n\
## Demographics\n\
- Age: {age}\n\
- Sex: {sex}\n\
- Country: {country}\n\n\
## Phase\n{phase}\n\n\
## Allergies\n{allergies}\n\n\
## Medications\n{medications}\n\n\
## Conditions\n{conditions}\n\n\
## History (reverse-chron)\n{history}\n\n\
## Known unknowns\n{unknowns}\n\n\
## Milestones\n{milestones_block}\n\n\
## Awaiting\n{awaiting_block}\n\n\
## Activation (PAM-13)\n{activation_block}\n\n\
## Coaching goals\n{coaching_block}\n\n\
## Derived (для kernel scoring)\n\
- primary_complaint_undiagnosed: {pcu}\n\
- has_confirmed_dx: {hcd}\n\
- missing_labs_count: {mlc}\n\
- history_contradictions: {hc}\n\
- unexplained_symptoms_count: {usc}\n\
- last_visit_years_ago: {lvya}\n\
- dx_without_evidence: {dwe}\n\n\
---\n_Last updated: {ts}. Edit freely; AIM will parse on next read._\n",
        id = mem.id,
        age = age,
        sex = sex,
        country = country,
        phase = phase_str,
        allergies = allergies,
        medications = medications,
        conditions = conditions,
        history = history,
        unknowns = unknowns,
        milestones_block = milestones_block,
        awaiting_block = awaiting_block,
        activation_block = activation_block,
        coaching_block = coaching_block,
        pcu = mem.primary_complaint_undiagnosed,
        hcd = mem.has_confirmed_dx,
        mlc = mem.missing_labs_count,
        hc = mem.history_contradictions,
        usc = mem.unexplained_symptoms_count,
        lvya = mem.last_visit_years_ago,
        dwe = mem.dx_without_evidence,
        ts = ts.format("%Y-%m-%d %H:%M:%S")
    )
}

// ── markdown parsing ────────────────────────────────────────────────────────

fn split_sections(text: &str) -> std::collections::BTreeMap<String, Vec<String>> {
    let mut map: std::collections::BTreeMap<String, Vec<String>> = std::collections::BTreeMap::new();
    let mut current: Option<String> = None;
    for line in text.lines() {
        if let Some(rest) = line.strip_prefix("## ") {
            let name = rest.trim().to_string();
            current = Some(name.clone());
            map.entry(name).or_default();
        } else if let Some(name) = &current {
            map.get_mut(name).unwrap().push(line.to_string());
        }
    }
    map
}

fn parse_bullet(line: &str) -> Option<&str> {
    let trimmed = line.trim();
    if !trimmed.starts_with("- ") {
        return None;
    }
    let body = &trimmed[2..];
    if body.starts_with('_') {
        return None;
    }
    Some(body.trim())
}

pub fn parse(id: &str, text: &str) -> PatientMemory {
    let sections = split_sections(text);
    let mut mem = PatientMemory::new(id);

    if let Some(lines) = sections.get("Demographics") {
        let kv = Regex::new(r"^- (\w+):\s*(.+)$").unwrap();
        for line in lines {
            if let Some(c) = kv.captures(line.trim()) {
                let key = c.get(1).map(|m| m.as_str().to_lowercase()).unwrap_or_default();
                let val = c.get(2).map(|m| m.as_str().trim().to_string()).unwrap_or_default();
                match key.as_str() {
                    "age" => mem.demographics.age = val.parse().ok(),
                    "sex" => {
                        mem.demographics.sex = if val == "?" { None } else { Some(val) };
                    }
                    "country" => {
                        mem.demographics.country = if val == "?" { None } else { Some(val) };
                    }
                    _ => {}
                }
            }
        }
    }

    if let Some(lines) = sections.get("Allergies") {
        for line in lines {
            if let Some(body) = parse_bullet(line) {
                mem.allergies.push(body.to_string());
            }
        }
    }

    if let Some(lines) = sections.get("Medications") {
        for line in lines {
            if let Some(body) = parse_bullet(line) {
                let parts: Vec<String> = body.split('·').map(|s| s.trim().to_string()).collect();
                let mut med = Medication {
                    name: parts.first().cloned().unwrap_or_else(|| "?".into()),
                    dose: parts.get(1).cloned(),
                    freq: parts.get(2).cloned(),
                };
                // treat literal "?" placeholders as None
                if med.dose.as_deref() == Some("?") {
                    med.dose = None;
                }
                if med.freq.as_deref() == Some("?") {
                    med.freq = None;
                }
                mem.medications.push(med);
            }
        }
    }

    if let Some(lines) = sections.get("Conditions") {
        let cond_re = Regex::new(r"^- (.+?) \((.+?)\):?\s*(.*)$").unwrap();
        for line in lines {
            let trimmed = line.trim();
            if !trimmed.starts_with("- ") || trimmed.starts_with("- _") {
                continue;
            }
            if let Some(c) = cond_re.captures(trimmed) {
                let dx = c.get(1).map(|m| m.as_str().to_string()).unwrap_or_default();
                let since = c.get(2).map(|m| m.as_str().to_string());
                let notes = c.get(3).map(|m| m.as_str().to_string()).filter(|s| !s.is_empty());
                mem.conditions.push(Condition {
                    dx,
                    since,
                    notes,
                });
            }
        }
    }

    if let Some(lines) = sections.get("History (reverse-chron)") {
        for line in lines {
            if let Some(body) = parse_bullet(line) {
                mem.history.push(body.to_string());
            }
        }
    }

    if let Some(lines) = sections.get("Known unknowns") {
        for line in lines {
            if let Some(body) = parse_bullet(line) {
                mem.known_unknowns.push(body.to_string());
            }
        }
    }

    // Phase A (2026-05-06) — phase / milestones / awaiting parsers.
    if let Some(lines) = sections.get("Phase") {
        for line in lines {
            let trimmed = line.trim();
            if trimmed.is_empty() || trimmed.starts_with('_') {
                continue;
            }
            // Phase is a single bare token on its own line.
            mem.phase = trimmed.to_string();
            break;
        }
    }
    if mem.phase.is_empty() {
        mem.phase = default_phase();
    }

    // Milestone bullet:
    //   - <id> (<deadline>, <criticality>): <status> [— <blockers>]
    if let Some(lines) = sections.get("Milestones") {
        let m_re = Regex::new(
            r"^- ([\w\-]+)\s+\(([^,]+),\s*([^\)]+)\):\s*(\w+)(?:\s+[—\-]\s+(.+))?$",
        )
        .unwrap();
        for line in lines {
            let trimmed = line.trim();
            if !trimmed.starts_with("- ") || trimmed.starts_with("- _") {
                continue;
            }
            if let Some(c) = m_re.captures(trimmed) {
                let id = c.get(1).map(|m| m.as_str().to_string()).unwrap_or_default();
                let deadline_s = c.get(2).map(|m| m.as_str().trim()).unwrap_or("");
                let crit = c.get(3).map(|m| m.as_str().trim().to_string()).unwrap_or_else(|| "medium".into());
                let status = c.get(4).map(|m| m.as_str().to_string()).unwrap_or_else(|| "pending".into());
                let blockers: Vec<String> = c
                    .get(5)
                    .map(|m| {
                        m.as_str()
                            .split(',')
                            .map(|s| s.trim().to_string())
                            .filter(|s| !s.is_empty())
                            .collect()
                    })
                    .unwrap_or_default();
                let deadline = if deadline_s == "—" || deadline_s.is_empty() {
                    None
                } else {
                    NaiveDate::parse_from_str(deadline_s, "%Y-%m-%d").ok()
                };
                mem.milestones.push(Milestone {
                    id,
                    deadline,
                    status,
                    blockers,
                    criticality: crit,
                });
            }
        }
    }

    // Awaiting bullet:
    //   - <topic> [(since <date>[, expected <date>])]
    if let Some(lines) = sections.get("Awaiting") {
        let a_re_full = Regex::new(
            r"^- (.+?)\s+\(([^)]+)\)\s*$",
        )
        .unwrap();
        for line in lines {
            let trimmed = line.trim();
            if !trimmed.starts_with("- ") || trimmed.starts_with("- _") {
                continue;
            }
            if let Some(c) = a_re_full.captures(trimmed) {
                let topic = c.get(1).map(|m| m.as_str().trim().to_string()).unwrap_or_default();
                let parens = c.get(2).map(|m| m.as_str()).unwrap_or("");
                let mut since: Option<NaiveDate> = None;
                let mut expected: Option<NaiveDate> = None;
                for part in parens.split(',').map(|s| s.trim()) {
                    if let Some(rest) = part.strip_prefix("since ") {
                        since = NaiveDate::parse_from_str(rest.trim(), "%Y-%m-%d").ok();
                    } else if let Some(rest) = part.strip_prefix("expected ") {
                        expected = NaiveDate::parse_from_str(rest.trim(), "%Y-%m-%d").ok();
                    }
                }
                mem.awaiting.push(Awaiting {
                    topic,
                    since,
                    expected_by: expected,
                });
            } else if let Some(body) = parse_bullet(trimmed) {
                // Fallback — bare topic without dates
                mem.awaiting.push(Awaiting {
                    topic: body.to_string(),
                    since: None,
                    expected_by: None,
                });
            }
        }
    }

    // Phase 2 cornerstone (2026-05-07) — Activation (PAM-13) parser.
    if let Some(lines) = sections.get("Activation (PAM-13)") {
        // Accepted shapes (single canonical block per render()):
        //   - current_score: 56.4
        //   - current_level: 3
        //   - last_measured: 2026-04-15
        //   - mcid: 5.4
        //   - mdc: 7.2
        //   - history:
        //     - 2026-01-10: 48.2 (level 2)
        //     - 2026-04-15: 56.4 (level 3)
        let kv = Regex::new(r"^- (\w+):\s*(.+)$").unwrap();
        let hist_re = Regex::new(
            r"^-\s+(\d{4}-\d{2}-\d{2}):\s+([\d.]+)\s+\(level\s+(\d+)\)$",
        )
        .unwrap();
        for line in lines {
            let stripped = line.trim();
            if stripped.is_empty() || stripped.starts_with('_') {
                continue;
            }
            // History point (more indented)
            if let Some(c) = hist_re.captures(stripped) {
                let date = c.get(1)
                    .and_then(|m| NaiveDate::parse_from_str(m.as_str(), "%Y-%m-%d").ok());
                let score = c.get(2).and_then(|m| m.as_str().parse::<f64>().ok());
                let level = c.get(3).and_then(|m| m.as_str().parse::<u8>().ok());
                if let (Some(d), Some(s), Some(l)) = (date, score, level) {
                    mem.activation_history.push(ActivationPoint {
                        date: d, score: s, level: l,
                    });
                }
                continue;
            }
            // current_score / current_level
            if let Some(c) = kv.captures(stripped) {
                let key = c.get(1).map(|m| m.as_str()).unwrap_or("");
                let val = c.get(2).map(|m| m.as_str().trim()).unwrap_or("");
                match key {
                    "current_score" => mem.current_activation_score = val.parse().ok(),
                    "current_level" => mem.current_activation_level = val.parse().ok(),
                    _ => {}
                }
            }
        }
        // If history present but current_* fields missing, infer from latest.
        if let Some(p) = mem.activation_history.last() {
            if mem.current_activation_score.is_none() {
                mem.current_activation_score = Some(p.score);
            }
            if mem.current_activation_level.is_none() {
                mem.current_activation_level = Some(p.level);
            }
        }
    }

    // Phase 2 cornerstone (2026-05-07) — Coaching goals parser.
    if let Some(lines) = sections.get("Coaching goals") {
        // Format: `- <id>: <target> (set <date>[, achieved <date>])`
        let goal_re = Regex::new(
            r"^-\s+([\w\-]+):\s+(.+?)\s+\(set\s+(\d{4}-\d{2}-\d{2})(?:,\s*achieved\s+(\d{4}-\d{2}-\d{2}))?\)$",
        )
        .unwrap();
        for line in lines {
            let trimmed = line.trim();
            if !trimmed.starts_with("- ") || trimmed.starts_with("- _") {
                continue;
            }
            if let Some(c) = goal_re.captures(trimmed) {
                let id = c.get(1).map(|m| m.as_str().to_string()).unwrap_or_default();
                let target = c.get(2).map(|m| m.as_str().to_string()).unwrap_or_default();
                let set_at = c.get(3)
                    .and_then(|m| NaiveDate::parse_from_str(m.as_str(), "%Y-%m-%d").ok());
                let achieved = c.get(4)
                    .and_then(|m| NaiveDate::parse_from_str(m.as_str(), "%Y-%m-%d").ok());
                if let Some(date) = set_at {
                    mem.coaching_goals.push(CoachingGoal {
                        id, target, set_at: date, achieved,
                    });
                }
            }
        }
    }

    if let Some(lines) = sections.get("Derived (для kernel scoring)") {
        let kv = Regex::new(r"^- (\w+):\s*(.+)$").unwrap();
        for line in lines {
            if let Some(c) = kv.captures(line.trim()) {
                let key = c.get(1).map(|m| m.as_str()).unwrap_or("");
                let val = c.get(2).map(|m| m.as_str().trim()).unwrap_or("");
                match key {
                    "primary_complaint_undiagnosed" => {
                        mem.primary_complaint_undiagnosed = val.eq_ignore_ascii_case("true");
                    }
                    "has_confirmed_dx" => {
                        mem.has_confirmed_dx = val.eq_ignore_ascii_case("true");
                    }
                    "dx_without_evidence" => {
                        mem.dx_without_evidence = val.eq_ignore_ascii_case("true");
                    }
                    "missing_labs_count" => {
                        if let Ok(n) = val.parse() {
                            mem.missing_labs_count = n;
                        }
                    }
                    "history_contradictions" => {
                        if let Ok(n) = val.parse() {
                            mem.history_contradictions = n;
                        }
                    }
                    "unexplained_symptoms_count" => {
                        if let Ok(n) = val.parse() {
                            mem.unexplained_symptoms_count = n;
                        }
                    }
                    "last_visit_years_ago" => {
                        if let Ok(n) = val.parse() {
                            mem.last_visit_years_ago = n;
                        }
                    }
                    _ => {}
                }
            }
        }
    }

    // Derive: conditions present implies confirmed dx + complaint diagnosed.
    if !mem.conditions.is_empty() && !mem.has_confirmed_dx {
        mem.has_confirmed_dx = true;
        mem.primary_complaint_undiagnosed = false;
    }

    mem
}

// ── filesystem I/O + index ─────────────────────────────────────────────────

pub fn memory_path(patients_root: &Path, patient_id: &str) -> PathBuf {
    patients_root.join(patient_id).join(MEMORY_FILE)
}

pub trait PatientIndex: Send + Sync {
    fn upsert(&self, mem: &PatientMemory) -> Result<()>;
    fn list(&self) -> Result<Vec<PatientMemory>>;
}

pub struct NoopIndex;
impl PatientIndex for NoopIndex {
    fn upsert(&self, _: &PatientMemory) -> Result<()> {
        Ok(())
    }
    fn list(&self) -> Result<Vec<PatientMemory>> {
        Ok(Vec::new())
    }
}

pub trait Clock: Send + Sync {
    fn now(&self) -> DateTime<Utc>;
}

pub struct SystemClock;
impl Clock for SystemClock {
    fn now(&self) -> DateTime<Utc> {
        Utc::now()
    }
}

pub struct FixedClock(pub DateTime<Utc>);
impl Clock for FixedClock {
    fn now(&self) -> DateTime<Utc> {
        self.0
    }
}

pub fn write_memory(
    patients_root: &Path,
    mem: &PatientMemory,
    clock: &dyn Clock,
    index: &dyn PatientIndex,
) -> Result<PathBuf> {
    let path = memory_path(patients_root, &mem.id);
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    std::fs::write(&path, render(mem, clock.now()))?;
    index.upsert(mem)?;
    Ok(path)
}

pub fn read_memory(
    patients_root: &Path,
    patient_id: &str,
    index: &dyn PatientIndex,
) -> Result<Option<PatientMemory>> {
    let path = memory_path(patients_root, patient_id);
    if !path.exists() {
        return Ok(None);
    }
    let text = std::fs::read_to_string(&path)?;
    let mem = parse(patient_id, &text);
    index.upsert(&mem)?;
    Ok(Some(mem))
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;
    use tempfile::TempDir;

    fn ts() -> DateTime<Utc> {
        Utc.with_ymd_and_hms(2026, 5, 5, 0, 0, 0).unwrap()
    }

    // ── render ─────────────────────────────────────────────────────────────

    #[test]
    fn render_includes_all_sections() {
        let mem = PatientMemory {
            id: "Smith_John_1980_05_15".into(),
            demographics: Demographics {
                age: Some(45),
                sex: Some("M".into()),
                country: Some("GE".into()),
            },
            allergies: vec!["penicillin".into()],
            medications: vec![Medication {
                name: "metformin".into(),
                dose: Some("500 mg".into()),
                freq: Some("BID".into()),
            }],
            conditions: vec![Condition {
                dx: "T2DM".into(),
                since: Some("2020".into()),
                notes: Some("controlled".into()),
            }],
            history: vec!["MI 2018".into()],
            known_unknowns: vec!["family hx".into()],
            ..Default::default()
        };
        let s = render(&mem, ts());
        assert!(s.starts_with("# Memory — Smith_John_1980_05_15"));
        assert!(s.contains("- Age: 45"));
        assert!(s.contains("- penicillin"));
        assert!(s.contains("metformin · 500 mg · BID"));
        assert!(s.contains("T2DM (2020): controlled"));
        assert!(s.contains("- MI 2018"));
        assert!(s.contains("- family hx"));
        assert!(s.contains("Last updated: 2026-05-05 00:00:00"));
    }

    #[test]
    fn render_uses_none_placeholders_for_empty_lists() {
        let mem = PatientMemory::new("X");
        let s = render(&mem, ts());
        assert!(s.contains("## Allergies\n_(none)_"));
        assert!(s.contains("## Medications\n_(none)_"));
        assert!(s.contains("## Conditions\n_(none)_"));
    }

    #[test]
    fn render_demographic_question_marks_when_empty() {
        let mem = PatientMemory::new("X");
        let s = render(&mem, ts());
        assert!(s.contains("- Age: ?"));
        assert!(s.contains("- Sex: ?"));
    }

    // ── parse ──────────────────────────────────────────────────────────────

    #[test]
    fn parse_round_trips_demographics_and_allergies() {
        let original = PatientMemory {
            id: "X_Y_1990_01_01".into(),
            demographics: Demographics {
                age: Some(35),
                sex: Some("F".into()),
                country: Some("GE".into()),
            },
            allergies: vec!["aspirin".into(), "ibuprofen".into()],
            ..Default::default()
        };
        let text = render(&original, ts());
        let parsed = parse(&original.id, &text);
        assert_eq!(parsed.demographics, original.demographics);
        assert_eq!(parsed.allergies, original.allergies);
    }

    #[test]
    fn parse_handles_medications_with_dose_and_freq() {
        let mem = PatientMemory {
            id: "X".into(),
            medications: vec![Medication {
                name: "warfarin".into(),
                dose: Some("5 mg".into()),
                freq: Some("daily".into()),
            }],
            ..Default::default()
        };
        let text = render(&mem, ts());
        let p = parse(&mem.id, &text);
        assert_eq!(p.medications.len(), 1);
        assert_eq!(p.medications[0].name, "warfarin");
        assert_eq!(p.medications[0].dose.as_deref(), Some("5 mg"));
        assert_eq!(p.medications[0].freq.as_deref(), Some("daily"));
    }

    #[test]
    fn parse_skips_none_placeholders() {
        let mem = PatientMemory::new("X");
        let text = render(&mem, ts());
        let p = parse(&mem.id, &text);
        assert!(p.allergies.is_empty());
        assert!(p.medications.is_empty());
        assert!(p.conditions.is_empty());
    }

    #[test]
    fn parse_conditions_round_trip() {
        let mem = PatientMemory {
            id: "X".into(),
            conditions: vec![Condition {
                dx: "HTN".into(),
                since: Some("2015".into()),
                notes: Some("on lisinopril".into()),
            }],
            ..Default::default()
        };
        let text = render(&mem, ts());
        let p = parse(&mem.id, &text);
        assert_eq!(p.conditions.len(), 1);
        assert_eq!(p.conditions[0].dx, "HTN");
        assert_eq!(p.conditions[0].since.as_deref(), Some("2015"));
        assert_eq!(p.conditions[0].notes.as_deref(), Some("on lisinopril"));
    }

    #[test]
    fn parse_derives_confirmed_dx_when_conditions_present() {
        let mem = PatientMemory {
            id: "X".into(),
            conditions: vec![Condition {
                dx: "HTN".into(),
                since: Some("2015".into()),
                notes: None,
            }],
            primary_complaint_undiagnosed: true,
            has_confirmed_dx: false,
            ..Default::default()
        };
        let text = render(&mem, ts());
        let p = parse(&mem.id, &text);
        assert!(p.has_confirmed_dx);
        assert!(!p.primary_complaint_undiagnosed);
    }

    #[test]
    fn parse_derived_section_round_trips() {
        let mem = PatientMemory {
            id: "X".into(),
            missing_labs_count: 3,
            history_contradictions: 1,
            unexplained_symptoms_count: 2,
            last_visit_years_ago: 1.5,
            dx_without_evidence: true,
            primary_complaint_undiagnosed: true,
            has_confirmed_dx: false,
            ..Default::default()
        };
        let text = render(&mem, ts());
        let p = parse(&mem.id, &text);
        assert_eq!(p.missing_labs_count, 3);
        assert_eq!(p.history_contradictions, 1);
        assert_eq!(p.unexplained_symptoms_count, 2);
        assert!((p.last_visit_years_ago - 1.5).abs() < 1e-9);
        assert!(p.dx_without_evidence);
    }

    // ── filesystem I/O ─────────────────────────────────────────────────────

    #[test]
    fn write_then_read_round_trips() {
        let tmp = TempDir::new().unwrap();
        let mem = PatientMemory {
            id: "Smith_John_1980_05_15".into(),
            demographics: Demographics {
                age: Some(45),
                sex: Some("M".into()),
                country: None,
            },
            allergies: vec!["aspirin".into()],
            ..Default::default()
        };
        let clk = FixedClock(ts());
        let idx = NoopIndex;
        let path = write_memory(tmp.path(), &mem, &clk, &idx).unwrap();
        assert!(path.exists());
        assert!(path.ends_with("Smith_John_1980_05_15/MEMORY.md"));
        let reloaded = read_memory(tmp.path(), &mem.id, &idx).unwrap().unwrap();
        assert_eq!(reloaded.demographics, mem.demographics);
        assert_eq!(reloaded.allergies, mem.allergies);
    }

    #[test]
    fn read_memory_missing_returns_none() {
        let tmp = TempDir::new().unwrap();
        let r = read_memory(tmp.path(), "ghost", &NoopIndex).unwrap();
        assert!(r.is_none());
    }

    // ── PatientIndex side-effect ───────────────────────────────────────────

    #[derive(Default)]
    struct CountingIndex(parking_lot::Mutex<usize>);
    impl CountingIndex {
        fn count(&self) -> usize {
            *self.0.lock()
        }
    }
    impl PatientIndex for CountingIndex {
        fn upsert(&self, _: &PatientMemory) -> Result<()> {
            *self.0.lock() += 1;
            Ok(())
        }
        fn list(&self) -> Result<Vec<PatientMemory>> {
            Ok(Vec::new())
        }
    }

    #[test]
    fn write_memory_calls_index_upsert() {
        let tmp = TempDir::new().unwrap();
        let mem = PatientMemory::new("X");
        let clk = FixedClock(ts());
        let idx = CountingIndex::default();
        write_memory(tmp.path(), &mem, &clk, &idx).unwrap();
        assert_eq!(idx.count(), 1);
    }

    #[test]
    fn read_memory_calls_index_upsert() {
        let tmp = TempDir::new().unwrap();
        let mem = PatientMemory::new("X");
        let clk = FixedClock(ts());
        let noop = NoopIndex;
        write_memory(tmp.path(), &mem, &clk, &noop).unwrap();
        let idx = CountingIndex::default();
        read_memory(tmp.path(), "X", &idx).unwrap();
        assert_eq!(idx.count(), 1);
    }

    // ── to_kernel_json ─────────────────────────────────────────────────────

    // ── Phase A (HW1, 2026-05-06): phase + milestones + awaiting ───────────

    #[test]
    fn new_patient_defaults_to_intake_phase() {
        let m = PatientMemory::new("X");
        assert_eq!(m.phase, "INTAKE");
        assert!(m.milestones.is_empty());
        assert!(m.awaiting.is_empty());
    }

    #[test]
    fn render_includes_phase_section() {
        let mut m = PatientMemory::new("X");
        m.phase = "DIAGNOSTIC_WORKUP".into();
        let s = render(&m, ts());
        assert!(s.contains("## Phase\nDIAGNOSTIC_WORKUP"));
    }

    #[test]
    fn render_milestones_and_awaiting_round_trip() {
        let mut m = PatientMemory::new("X");
        m.phase = "ACTIVE_TREATMENT".into();
        m.milestones.push(Milestone {
            id: "thyroid-recheck".into(),
            deadline: NaiveDate::from_ymd_opt(2026, 8, 15),
            status: "pending".into(),
            blockers: vec!["TSH result".into()],
            criticality: "medium".into(),
        });
        m.awaiting.push(Awaiting {
            topic: "repeat lab K+".into(),
            since: NaiveDate::from_ymd_opt(2026, 5, 6),
            expected_by: NaiveDate::from_ymd_opt(2026, 5, 13),
        });

        let s = render(&m, ts());
        assert!(s.contains("## Milestones"));
        assert!(s.contains("- thyroid-recheck (2026-08-15, medium): pending — TSH result"));
        assert!(s.contains("## Awaiting"));
        assert!(s.contains("- repeat lab K+ (since 2026-05-06, expected 2026-05-13)"));

        let p = parse(&m.id, &s);
        assert_eq!(p.phase, "ACTIVE_TREATMENT");
        assert_eq!(p.milestones.len(), 1);
        assert_eq!(p.milestones[0].id, "thyroid-recheck");
        assert_eq!(p.milestones[0].deadline, NaiveDate::from_ymd_opt(2026, 8, 15));
        assert_eq!(p.milestones[0].criticality, "medium");
        assert_eq!(p.milestones[0].status, "pending");
        assert_eq!(p.milestones[0].blockers, vec!["TSH result".to_string()]);
        assert_eq!(p.awaiting.len(), 1);
        assert_eq!(p.awaiting[0].topic, "repeat lab K+");
        assert_eq!(p.awaiting[0].since, NaiveDate::from_ymd_opt(2026, 5, 6));
        assert_eq!(p.awaiting[0].expected_by, NaiveDate::from_ymd_opt(2026, 5, 13));
    }

    #[test]
    fn parse_milestones_without_blockers() {
        let mut m = PatientMemory::new("X");
        m.milestones.push(Milestone {
            id: "followup".into(),
            deadline: NaiveDate::from_ymd_opt(2026, 9, 1),
            status: "pending".into(),
            blockers: vec![],
            criticality: "high".into(),
        });
        let s = render(&m, ts());
        let p = parse(&m.id, &s);
        assert_eq!(p.milestones.len(), 1);
        assert!(p.milestones[0].blockers.is_empty());
        assert_eq!(p.milestones[0].criticality, "high");
    }

    #[test]
    fn parse_awaiting_bare_topic() {
        let s = "## Awaiting\n- referral consult\n";
        let mut text = render(&PatientMemory::new("X"), ts());
        // Inject a bare-topic awaiting bullet by replacing the (none) placeholder
        text = text.replace("## Awaiting\n_(none)_", s);
        let p = parse("X", &text);
        assert_eq!(p.awaiting.len(), 1);
        assert_eq!(p.awaiting[0].topic, "referral consult");
        assert!(p.awaiting[0].since.is_none());
        assert!(p.awaiting[0].expected_by.is_none());
    }

    #[test]
    fn missing_phase_section_defaults_to_intake() {
        let text = "# Memory — X\n\n## Demographics\n- Age: 30\n";
        let p = parse("X", text);
        assert_eq!(p.phase, "INTAKE");
    }

    #[test]
    fn milestone_is_hot_basic() {
        let today = NaiveDate::from_ymd_opt(2026, 5, 6).unwrap();
        let m = Milestone {
            id: "x".into(),
            deadline: NaiveDate::from_ymd_opt(2026, 5, 10),
            status: "pending".into(),
            blockers: vec![],
            criticality: "medium".into(),
        };
        assert!(m.is_hot(today)); // 4d ≤ 7

        let in_10 = Milestone {
            deadline: NaiveDate::from_ymd_opt(2026, 5, 16),
            criticality: "medium".into(),
            ..m.clone()
        };
        assert!(!in_10.is_hot(today)); // 10d, medium

        let in_10_high = Milestone {
            criticality: "high".into(),
            ..in_10.clone()
        };
        assert!(in_10_high.is_hot(today)); // 10d, high → ≤14
    }

    #[test]
    fn awaiting_overdue_basic() {
        let today = NaiveDate::from_ymd_opt(2026, 5, 6).unwrap();
        let a = Awaiting {
            topic: "x".into(),
            since: NaiveDate::from_ymd_opt(2026, 4, 20),
            expected_by: NaiveDate::from_ymd_opt(2026, 5, 1),
        };
        assert!(a.overdue(today));
        assert_eq!(a.days_silent(today), Some(16));

        let not_yet = Awaiting {
            expected_by: NaiveDate::from_ymd_opt(2026, 5, 10),
            ..a.clone()
        };
        assert!(!not_yet.overdue(today));

        let no_expected = Awaiting {
            expected_by: None,
            ..a.clone()
        };
        assert!(!no_expected.overdue(today));
    }

    #[test]
    fn hot_milestones_filter_pending_only() {
        let today = NaiveDate::from_ymd_opt(2026, 5, 6).unwrap();
        let mut mem = PatientMemory::new("X");
        mem.milestones.push(Milestone {
            id: "soon-pending".into(),
            deadline: NaiveDate::from_ymd_opt(2026, 5, 10),
            status: "pending".into(),
            blockers: vec![],
            criticality: "medium".into(),
        });
        mem.milestones.push(Milestone {
            id: "soon-done".into(),
            deadline: NaiveDate::from_ymd_opt(2026, 5, 10),
            status: "done".into(),
            blockers: vec![],
            criticality: "high".into(),
        });
        let hot = mem.hot_milestones(today);
        assert_eq!(hot.len(), 1);
        assert_eq!(hot[0].id, "soon-pending");
    }

    // ── existing tests ─────────────────────────────────────────────────────

    #[test]
    fn to_kernel_json_emits_flat_fields() {
        let mem = PatientMemory {
            id: "X".into(),
            demographics: Demographics {
                age: Some(30),
                sex: Some("F".into()),
                country: None,
            },
            allergies: vec!["x".into()],
            primary_complaint_undiagnosed: true,
            has_confirmed_dx: false,
            ..Default::default()
        };
        let v = mem.to_kernel_json();
        assert_eq!(v["age"], serde_json::json!(30));
        assert_eq!(v["sex"], serde_json::json!("F"));
        assert_eq!(v["allergies"], serde_json::json!(["x"]));
        assert_eq!(v["primary_complaint_undiagnosed"], serde_json::json!(true));
    }

    // ── Phase 2 cornerstone (HW1, 2026-05-07) — PAM-13 + coaching ──────────

    #[test]
    fn pam_level_categorization() {
        assert_eq!(pam_level_from_score(40.0), 1);
        assert_eq!(pam_level_from_score(46.9), 1);
        assert_eq!(pam_level_from_score(47.0), 2);
        assert_eq!(pam_level_from_score(55.1), 3);
        assert_eq!(pam_level_from_score(67.0), 4);
        assert_eq!(pam_level_from_score(85.0), 4);
    }

    #[test]
    fn record_activation_updates_current_fields() {
        let mut m = PatientMemory::new("X");
        m.record_activation(NaiveDate::from_ymd_opt(2026, 1, 10).unwrap(), 48.2);
        assert_eq!(m.current_activation_score, Some(48.2));
        assert_eq!(m.current_activation_level, Some(2));
        m.record_activation(NaiveDate::from_ymd_opt(2026, 4, 15).unwrap(), 56.4);
        assert_eq!(m.current_activation_score, Some(56.4));
        assert_eq!(m.current_activation_level, Some(3));
        assert_eq!(m.activation_history.len(), 2);
    }

    #[test]
    fn activation_delta_and_mcid() {
        let mut m = PatientMemory::new("X");
        assert_eq!(m.activation_delta(), None);
        m.record_activation(NaiveDate::from_ymd_opt(2026, 1, 10).unwrap(), 48.2);
        assert_eq!(m.activation_delta(), None);
        m.record_activation(NaiveDate::from_ymd_opt(2026, 4, 15).unwrap(), 56.4);
        let delta = m.activation_delta().unwrap();
        assert!((delta - 8.2).abs() < 1e-9);
        assert!(m.activation_clinically_improved()); // 8.2 ≥ MCID 5.4
        assert!(!m.activation_clinically_declined());
    }

    #[test]
    fn activation_decline_detected() {
        let mut m = PatientMemory::new("X");
        m.record_activation(NaiveDate::from_ymd_opt(2026, 1, 10).unwrap(), 60.0);
        m.record_activation(NaiveDate::from_ymd_opt(2026, 4, 15).unwrap(), 50.0);
        assert!(m.activation_clinically_declined()); // -10 ≤ -MCID
        assert!(!m.activation_clinically_improved());
    }

    #[test]
    fn coaching_goals_render_round_trip() {
        let mut m = PatientMemory::new("X");
        m.coaching_goals.push(CoachingGoal {
            id: "hba1c-self-monitor".into(),
            target: "weekly home glucose check".into(),
            set_at: NaiveDate::from_ymd_opt(2026, 2, 1).unwrap(),
            achieved: None,
        });
        m.coaching_goals.push(CoachingGoal {
            id: "med-adherence".into(),
            target: "95% pill count".into(),
            set_at: NaiveDate::from_ymd_opt(2026, 3, 15).unwrap(),
            achieved: NaiveDate::from_ymd_opt(2026, 4, 15),
        });
        let s = render(&m, ts());
        assert!(s.contains("## Coaching goals"));
        assert!(s.contains("- hba1c-self-monitor: weekly home glucose check (set 2026-02-01)"));
        assert!(s.contains("- med-adherence: 95% pill count (set 2026-03-15, achieved 2026-04-15)"));
        let p = parse(&m.id, &s);
        assert_eq!(p.coaching_goals.len(), 2);
        assert_eq!(p.coaching_goals[0].id, "hba1c-self-monitor");
        assert!(p.coaching_goals[0].achieved.is_none());
        assert!(p.coaching_goals[1].achieved.is_some());
    }

    #[test]
    fn activation_render_round_trip() {
        let mut m = PatientMemory::new("X");
        m.record_activation(NaiveDate::from_ymd_opt(2026, 1, 10).unwrap(), 48.2);
        m.record_activation(NaiveDate::from_ymd_opt(2026, 4, 15).unwrap(), 56.4);
        let s = render(&m, ts());
        assert!(s.contains("## Activation (PAM-13)"));
        assert!(s.contains("- current_score: 56.4"));
        assert!(s.contains("- current_level: 3"));
        assert!(s.contains("2026-01-10: 48.2 (level 2)"));
        assert!(s.contains("2026-04-15: 56.4 (level 3)"));
        let p = parse(&m.id, &s);
        assert_eq!(p.current_activation_score, Some(56.4));
        assert_eq!(p.current_activation_level, Some(3));
        assert_eq!(p.activation_history.len(), 2);
    }

    #[test]
    fn missing_activation_section_renders_placeholder() {
        let m = PatientMemory::new("X");
        let s = render(&m, ts());
        assert!(s.contains("## Activation (PAM-13)\n_(not measured yet)_"));
        let p = parse(&m.id, &s);
        assert_eq!(p.current_activation_score, None);
        assert_eq!(p.current_activation_level, None);
        assert!(p.activation_history.is_empty());
    }

    #[test]
    fn active_coaching_goals_filter() {
        let mut m = PatientMemory::new("X");
        m.coaching_goals.push(CoachingGoal {
            id: "a".into(),
            target: "active".into(),
            set_at: NaiveDate::from_ymd_opt(2026, 2, 1).unwrap(),
            achieved: None,
        });
        m.coaching_goals.push(CoachingGoal {
            id: "b".into(),
            target: "done".into(),
            set_at: NaiveDate::from_ymd_opt(2026, 1, 1).unwrap(),
            achieved: NaiveDate::from_ymd_opt(2026, 4, 15),
        });
        assert_eq!(m.active_coaching_goals().len(), 1);
        assert_eq!(m.active_coaching_goals()[0].id, "a");
    }
}
