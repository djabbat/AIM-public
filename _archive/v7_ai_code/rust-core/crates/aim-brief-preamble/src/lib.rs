//! aim-brief-preamble — smart 1-3 line morning header (B1).
//!
//! Port of `agents/brief_preamble.py`. The full Python module wires three
//! data sources (project_owner, stakeholder_tracker, deadline_scanner) on
//! its own. The Rust port keeps the **formatting and locale** logic here
//! and exposes a composable [`compose`] entry point that takes
//! pre-computed inputs — production code threads in the actual scanner /
//! tracker hits, tests pass them directly.
//!
//! ## Locale
//! Russian / English / Georgian (`AIM_BRIEF_LANG` env override).
//!
//! ## Output
//! 1–3 lines, capped at `max_chars` (default 280) total:
//!
//! 1. greeting (always)
//! 2. hottest milestone — overdue / today / `+Nd`
//! 3. most-overdue stakeholder follow-up
//! 4. deadline horizon (today / week / overdue counts)
//!
//! Lines 2-4 are dropped when their input is `None`.

use chrono::{DateTime, Datelike, NaiveDate, Timelike, Utc};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Lang {
    Ru,
    En,
    Ka,
}

impl Lang {
    pub fn parse(s: &str) -> Self {
        match s.to_lowercase().as_str() {
            "en" => Lang::En,
            "ka" => Lang::Ka,
            _ => Lang::Ru,
        }
    }

    pub fn from_env() -> Self {
        std::env::var("AIM_BRIEF_LANG")
            .ok()
            .map(|s| Self::parse(&s))
            .unwrap_or(Lang::Ru)
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MilestoneInput {
    /// Free-form label (e.g. `FCLC/concept_note`).
    pub label: String,
    /// Days from today: 0 → today, negative → overdue, positive → upcoming.
    pub days: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StakeholderInput {
    pub name: String,
    /// Optional role label (e.g. `Co-PI WP3`).
    pub role: Option<String>,
    /// Days since the expected reply date (always non-negative; 0 means
    /// the response was due today).
    pub silent_days: i64,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, Default)]
pub struct DeadlineCounts {
    pub today: u32,
    pub this_week: u32,
    pub overdue: u32,
}

impl DeadlineCounts {
    pub fn is_empty(&self) -> bool {
        self.today == 0 && self.this_week == 0 && self.overdue == 0
    }
}

const RU_GREETINGS: [&str; 4] = [
    "Спокойной ночи",
    "Доброе утро",
    "Добрый день",
    "Добрый вечер",
];
const EN_GREETINGS: [&str; 4] = [
    "Late evening",
    "Good morning",
    "Good afternoon",
    "Good evening",
];
const KA_GREETINGS: [&str; 4] = [
    "ღამე მშვიდობისა",
    "დილა მშვიდობისა",
    "შუადღე მშვიდობისა",
    "საღამო მშვიდობისა",
];

fn greeting(now: DateTime<Utc>, name: &str, lang: Lang) -> String {
    let h = now.hour();
    let table = match lang {
        Lang::Ru => &RU_GREETINGS,
        Lang::En => &EN_GREETINGS,
        Lang::Ka => &KA_GREETINGS,
    };
    let g = if h < 5 {
        table[0]
    } else if h < 12 {
        table[1]
    } else if h < 18 {
        table[2]
    } else {
        table[3]
    };
    format!("{g}, {name}.")
}

fn fmt_milestone(input: &MilestoneInput, lang: Lang) -> String {
    let days = input.days;
    let label = &input.label;
    match lang {
        Lang::Ru => {
            if days == 0 {
                format!("🔥 СЕГОДНЯ: {label}")
            } else if days < 0 {
                format!("⛔ просрочено {}d: {label}", -days)
            } else {
                format!("📅 через {days}д: {label}")
            }
        }
        Lang::En => {
            if days == 0 {
                format!("🔥 TODAY: {label}")
            } else if days < 0 {
                format!("⛔ overdue {}d: {label}", -days)
            } else {
                format!("📅 in {days}d: {label}")
            }
        }
        Lang::Ka => {
            if days == 0 {
                format!("🔥 დღეს: {label}")
            } else if days < 0 {
                format!("⛔ ვადაგასული {}d: {label}", -days)
            } else {
                format!("📅 {days}დღეში: {label}")
            }
        }
    }
}

fn fmt_stakeholder(s: &StakeholderInput, lang: Lang) -> String {
    let role = s.role.as_deref().unwrap_or(match lang {
        Lang::Ru => "контакт",
        Lang::En => "contact",
        Lang::Ka => "კონტაქტი",
    });
    let days = s.silent_days;
    let no_reply = match lang {
        Lang::Ru => format!("нет ответа уже {days}д"),
        Lang::En => format!("no reply for {days}d"),
        Lang::Ka => format!("{days}დღე უპასუხოდ"),
    };
    format!("📮 {} ({}) — {}", s.name, role, no_reply)
}

fn fmt_deadlines(c: DeadlineCounts, lang: Lang) -> String {
    let header = match lang {
        Lang::Ru => "🗓 дедлайны",
        Lang::En => "🗓 deadlines",
        Lang::Ka => "🗓 ვადები",
    };
    let mut parts: Vec<String> = Vec::new();
    if c.today > 0 {
        parts.push(format!(
            "{} {}",
            c.today,
            match lang {
                Lang::Ru => "сегодня",
                Lang::En => "today",
                Lang::Ka => "დღეს",
            }
        ));
    }
    if c.this_week > 0 {
        parts.push(format!(
            "{} {}",
            c.this_week,
            match lang {
                Lang::Ru => "в эту неделю",
                Lang::En => "this week",
                Lang::Ka => "ამ კვირაში",
            }
        ));
    }
    if c.overdue > 0 {
        parts.push(format!(
            "{} {}",
            c.overdue,
            match lang {
                Lang::Ru => "просрочено",
                Lang::En => "overdue",
                Lang::Ka => "ვადაგასული",
            }
        ));
    }
    format!("{}: {}", header, parts.join(", "))
}

#[derive(Debug, Clone, Default)]
pub struct PreambleInputs {
    pub hot_milestone: Option<MilestoneInput>,
    pub overdue_stakeholder: Option<StakeholderInput>,
    pub deadlines: Option<DeadlineCounts>,
}

#[derive(Debug, Clone, Copy)]
pub struct PreambleOpts {
    pub max_chars: usize,
    pub lang: Lang,
}

impl Default for PreambleOpts {
    fn default() -> Self {
        Self {
            max_chars: 280,
            lang: Lang::Ru,
        }
    }
}

/// Default name per locale (matches Python: "Джаба" / "Jaba" / "ჯაბა").
pub fn default_name(lang: Lang) -> &'static str {
    match lang {
        Lang::Ru => "Джаба",
        Lang::En => "Jaba",
        Lang::Ka => "ჯაბა",
    }
}

/// Compose the morning preamble. Caller threads in `now`, the user name,
/// and pre-computed [`PreambleInputs`].
pub fn compose(
    now: DateTime<Utc>,
    name: &str,
    inputs: &PreambleInputs,
    opts: &PreambleOpts,
) -> String {
    let mut lines: Vec<String> = Vec::with_capacity(4);
    lines.push(greeting(now, name, opts.lang));

    if let Some(m) = &inputs.hot_milestone {
        let line = fmt_milestone(m, opts.lang);
        if total_chars(&lines) + line.chars().count() <= opts.max_chars {
            lines.push(line);
        }
    }
    if let Some(s) = &inputs.overdue_stakeholder {
        let line = fmt_stakeholder(s, opts.lang);
        if total_chars(&lines) + line.chars().count() <= opts.max_chars {
            lines.push(line);
        }
    }
    if let Some(c) = &inputs.deadlines {
        if !c.is_empty() {
            let line = fmt_deadlines(*c, opts.lang);
            if total_chars(&lines) + line.chars().count() <= opts.max_chars {
                lines.push(line);
            }
        }
    }
    lines.join("\n")
}

fn total_chars(lines: &[String]) -> usize {
    lines.iter().map(|l| l.chars().count()).sum()
}

/// Convenience: pick the strongest milestone candidate by `(criticality_rank,
/// days)` — same algorithm Python uses inside `_hot_milestone_line`.
/// Lower rank = higher priority. Days outside `[-14, 14]` are dropped.
pub fn pick_hot_milestone(candidates: &[(MilestoneInput, u8)]) -> Option<MilestoneInput> {
    let mut filtered: Vec<&(MilestoneInput, u8)> = candidates
        .iter()
        .filter(|(m, _)| m.days >= -14 && m.days <= 14)
        .collect();
    filtered.sort_by(|a, b| {
        a.1.cmp(&b.1)
            .then_with(|| a.0.days.cmp(&b.0.days))
            .then_with(|| a.0.label.cmp(&b.0.label))
    });
    filtered.first().map(|(m, _)| m.clone())
}

/// Compute days-from-today for a deadline date (positive = upcoming,
/// 0 = today, negative = overdue).
pub fn days_from(today: NaiveDate, deadline: NaiveDate) -> i64 {
    (deadline - today).num_days()
}

/// Mirror `chrono::Datelike::ordinal0` use — exposed so callers don't need
/// to pull chrono just to compute "is it weekend?" / similar trivia.
pub fn weekday_ordinal(now: DateTime<Utc>) -> u32 {
    now.ordinal0()
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::{TimeZone, Utc};

    fn at(h: u32) -> DateTime<Utc> {
        Utc.with_ymd_and_hms(2026, 5, 4, h, 0, 0).unwrap()
    }

    #[test]
    fn greeting_picks_correct_window_ru() {
        assert_eq!(greeting(at(2), "Джаба", Lang::Ru), "Спокойной ночи, Джаба.");
        assert_eq!(greeting(at(8), "Джаба", Lang::Ru), "Доброе утро, Джаба.");
        assert_eq!(greeting(at(14), "Джаба", Lang::Ru), "Добрый день, Джаба.");
        assert_eq!(greeting(at(20), "Джаба", Lang::Ru), "Добрый вечер, Джаба.");
    }

    #[test]
    fn greeting_en_and_ka() {
        assert!(greeting(at(8), "Jaba", Lang::En).starts_with("Good morning"));
        assert!(greeting(at(20), "ჯაბა", Lang::Ka).starts_with("საღამო"));
    }

    #[test]
    fn fmt_milestone_today() {
        let s = fmt_milestone(
            &MilestoneInput {
                label: "FCLC/concept".into(),
                days: 0,
            },
            Lang::Ru,
        );
        assert!(s.starts_with("🔥 СЕГОДНЯ"));
        assert!(s.contains("FCLC/concept"));
    }

    #[test]
    fn fmt_milestone_overdue_uses_positive_days() {
        let s = fmt_milestone(
            &MilestoneInput {
                label: "X".into(),
                days: -3,
            },
            Lang::Ru,
        );
        assert!(s.starts_with("⛔"));
        assert!(s.contains("3d"));
    }

    #[test]
    fn fmt_milestone_upcoming() {
        let s = fmt_milestone(
            &MilestoneInput {
                label: "X".into(),
                days: 7,
            },
            Lang::En,
        );
        assert!(s.starts_with("📅"));
        assert!(s.contains("in 7d"));
    }

    #[test]
    fn fmt_stakeholder_with_role() {
        let s = fmt_stakeholder(
            &StakeholderInput {
                name: "Geiger".into(),
                role: Some("Co-PI WP3".into()),
                silent_days: 9,
            },
            Lang::Ru,
        );
        assert!(s.contains("Geiger"));
        assert!(s.contains("Co-PI WP3"));
        assert!(s.contains("9д"));
    }

    #[test]
    fn fmt_stakeholder_default_role() {
        let s = fmt_stakeholder(
            &StakeholderInput {
                name: "Janke".into(),
                role: None,
                silent_days: 5,
            },
            Lang::En,
        );
        assert!(s.contains("(contact)"));
        assert!(s.contains("5d"));
    }

    #[test]
    fn fmt_deadlines_combines_buckets() {
        let s = fmt_deadlines(
            DeadlineCounts {
                today: 2,
                this_week: 5,
                overdue: 1,
            },
            Lang::Ru,
        );
        assert!(s.contains("дедлайны"));
        assert!(s.contains("2 сегодня"));
        assert!(s.contains("5 в эту неделю"));
        assert!(s.contains("1 просрочено"));
    }

    #[test]
    fn compose_greeting_only_when_no_data() {
        let s = compose(
            at(8),
            "Джаба",
            &PreambleInputs::default(),
            &PreambleOpts::default(),
        );
        assert_eq!(s.lines().count(), 1);
        assert!(s.starts_with("Доброе утро"));
    }

    #[test]
    fn compose_full_set() {
        let inputs = PreambleInputs {
            hot_milestone: Some(MilestoneInput {
                label: "FCLC/concept".into(),
                days: 0,
            }),
            overdue_stakeholder: Some(StakeholderInput {
                name: "Geiger".into(),
                role: Some("Co-PI".into()),
                silent_days: 9,
            }),
            deadlines: Some(DeadlineCounts {
                today: 1,
                this_week: 4,
                overdue: 0,
            }),
        };
        let s = compose(at(9), "Джаба", &inputs, &PreambleOpts::default());
        assert_eq!(s.lines().count(), 4);
        assert!(s.contains("FCLC/concept"));
        assert!(s.contains("Geiger"));
        assert!(s.contains("дедлайны"));
    }

    #[test]
    fn compose_caps_at_max_chars() {
        let inputs = PreambleInputs {
            hot_milestone: Some(MilestoneInput {
                label: "x".repeat(200),
                days: 0,
            }),
            overdue_stakeholder: Some(StakeholderInput {
                name: "y".repeat(50),
                role: Some("z".repeat(50)),
                silent_days: 1,
            }),
            deadlines: Some(DeadlineCounts {
                today: 1,
                this_week: 0,
                overdue: 0,
            }),
        };
        let s = compose(
            at(9),
            "Джаба",
            &inputs,
            &PreambleOpts {
                max_chars: 250,
                lang: Lang::Ru,
            },
        );
        assert!(s.chars().count() <= 250);
    }

    #[test]
    fn compose_skips_empty_deadlines() {
        let inputs = PreambleInputs {
            hot_milestone: None,
            overdue_stakeholder: None,
            deadlines: Some(DeadlineCounts::default()),
        };
        let s = compose(at(9), "Джаба", &inputs, &PreambleOpts::default());
        assert_eq!(s.lines().count(), 1, "deadlines empty → no line");
    }

    #[test]
    fn pick_hot_milestone_priority_then_days() {
        let cands = vec![
            (
                MilestoneInput {
                    label: "low/in-2".into(),
                    days: 2,
                },
                2,
            ),
            (
                MilestoneInput {
                    label: "high/in-7".into(),
                    days: 7,
                },
                0,
            ),
            (
                MilestoneInput {
                    label: "med/today".into(),
                    days: 0,
                },
                1,
            ),
        ];
        let pick = pick_hot_milestone(&cands).unwrap();
        // High criticality wins despite later days.
        assert_eq!(pick.label, "high/in-7");
    }

    #[test]
    fn pick_hot_milestone_filters_outside_window() {
        let cands = vec![
            (
                MilestoneInput {
                    label: "way-future".into(),
                    days: 30,
                },
                0,
            ),
            (
                MilestoneInput {
                    label: "soon".into(),
                    days: 5,
                },
                1,
            ),
        ];
        let pick = pick_hot_milestone(&cands).unwrap();
        assert_eq!(pick.label, "soon");
    }

    #[test]
    fn pick_hot_milestone_empty_returns_none() {
        let cands: Vec<(MilestoneInput, u8)> = vec![];
        assert!(pick_hot_milestone(&cands).is_none());
    }

    #[test]
    fn days_from_basic() {
        let today = NaiveDate::from_ymd_opt(2026, 5, 4).unwrap();
        let later = NaiveDate::from_ymd_opt(2026, 5, 11).unwrap();
        assert_eq!(days_from(today, later), 7);
        let past = NaiveDate::from_ymd_opt(2026, 4, 27).unwrap();
        assert_eq!(days_from(today, past), -7);
    }

    #[test]
    fn lang_from_env_default_ru() {
        std::env::remove_var("AIM_BRIEF_LANG");
        assert_eq!(Lang::from_env(), Lang::Ru);
    }

    #[test]
    fn lang_parse_unknown_returns_ru() {
        assert_eq!(Lang::parse("klingon"), Lang::Ru);
        assert_eq!(Lang::parse("KA"), Lang::Ka);
        assert_eq!(Lang::parse("en"), Lang::En);
    }
}
