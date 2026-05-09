//! aim-lifecycle — uniform abstraction over managed entities.
//!
//! Phase A (HW1, 2026-05-06). Defines an object-safe trait that any
//! managed entity (project / patient / experiment) implements. Storage
//! stays separate per entity type (project YAML, patient MEMORY.md,
//! experiment YAML); only the *API* converges so consumers like the
//! daily brief can iterate them uniformly.
//!
//! ```text
//! ┌─────────────────────────┐    ┌─────────────────────────┐
//! │  aim-project-owner      │    │  aim-patient-owner      │
//! │  yaml + Phase enum      │    │  MEMORY.md + Phase enum │
//! └────────┬────────────────┘    └────────┬────────────────┘
//!          │                              │
//!          └──────────┬───────────────────┘
//!                     ▼
//!          ┌──────────────────────┐
//!          │    Lifecycle trait    │   ← object-safe
//!          │    (this crate)       │
//!          └──────────────────────┘
//!                     ▲
//!          ┌──────────┴────────────┐
//!          │  aim-daily-brief etc  │   ← consumes Vec<Box<dyn Lifecycle>>
//!          └───────────────────────┘
//! ```
//!
//! ## Why object-safe
//!
//! Consumers need to hold a heterogeneous list of lifecycles
//! (`Vec<Box<dyn Lifecycle>>`). With associated types we lose that
//! ability. So phases are exchanged as `String` at the trait boundary
//! — implementations convert to/from typed enums internally.

use chrono::NaiveDate;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum EntityKind {
    Project,
    Patient,
    Experiment,
}

impl EntityKind {
    pub fn as_str(self) -> &'static str {
        match self {
            EntityKind::Project => "project",
            EntityKind::Patient => "patient",
            EntityKind::Experiment => "experiment",
        }
    }

    /// Display emoji for morning_brief headers.
    pub fn emoji(self) -> &'static str {
        match self {
            EntityKind::Project => "📌",
            EntityKind::Patient => "🏥",
            EntityKind::Experiment => "🔬",
        }
    }
}

/// A single time-anchored item that morning_brief / escalation cares
/// about: a milestone, an awaiting follow-up, a calibration deadline.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct HotItem {
    pub id: String,
    pub label: String,
    /// Days until the item is due. Negative = overdue.
    pub days_to: i64,
    /// "low" | "medium" | "high"
    pub criticality: String,
    pub blockers: Vec<String>,
}

impl HotItem {
    pub fn is_overdue(&self) -> bool {
        self.days_to < 0
    }

    pub fn is_today(&self) -> bool {
        self.days_to == 0
    }

    pub fn is_hot(&self) -> bool {
        self.days_to <= 7 || (self.criticality == "high" && self.days_to <= 14)
    }
}

#[derive(Debug, thiserror::Error)]
pub enum LifecycleError {
    #[error("entity not found: {0}")]
    NotFound(String),
    #[error("io: {0}")]
    Io(#[from] std::io::Error),
    #[error("invalid phase: {0}")]
    InvalidPhase(String),
    #[error("illegal transition: {src:?} → {dst:?}")]
    IllegalTransition { src: String, dst: String },
    #[error("{0}")]
    Other(String),
}

/// Object-safe lifecycle trait. Implementations live in
/// `aim-project-owner`, `aim-patient-owner`, `aim-experiment-owner`.
///
/// All phase values cross the boundary as `String` (e.g. "DRAFT",
/// "MONITORING") — lossless because each domain has a finite enum that
/// round-trips through its own `parse`/`as_str`.
pub trait Lifecycle: Send + Sync {
    fn kind(&self) -> EntityKind;

    /// Sorted list of entity ids (project name / patient folder /
    /// experiment id).
    fn list_entities(&self) -> Vec<String>;

    /// Current phase of `id`, as canonical uppercase string.
    fn current_phase(&self, id: &str) -> Result<String, LifecycleError>;

    /// Phases reachable from `src` (sorted). Empty for terminal phases.
    fn legal_phases(&self, src: &str) -> Vec<String>;

    /// Per-phase next-action advice. Stable static strings; consumers
    /// may render them in morning_brief.
    fn next_actions(&self, phase: &str) -> Vec<&'static str>;

    /// Items that should fire today: `is_hot()` true and not yet done.
    fn hot_items(
        &self,
        id: &str,
        today: NaiveDate,
    ) -> Result<Vec<HotItem>, LifecycleError>;

    /// Items already past their deadline / expected response time.
    fn overdue_items(
        &self,
        id: &str,
        today: NaiveDate,
    ) -> Result<Vec<HotItem>, LifecycleError>;

    /// One-screen status brief, ready for Telegram or terminal.
    fn morning_brief(
        &self,
        id: &str,
        today: NaiveDate,
    ) -> Result<String, LifecycleError>;
}

/// Render a multi-lifecycle brief by concatenating per-entity briefs.
/// Entity types are grouped (all projects, then all patients, …) and
/// separated by horizontal rules. Errors per entity are inlined as
/// `❌ <id>: <reason>` so one broken file doesn't blank the whole brief.
pub fn render_unified_brief(
    lifecycles: &[Box<dyn Lifecycle>],
    today: NaiveDate,
) -> String {
    let mut parts: Vec<String> = Vec::new();
    for lc in lifecycles {
        let header = format!("{} {}", lc.kind().emoji(), lc.kind().as_str());
        let mut block: Vec<String> = vec![header];
        for id in lc.list_entities() {
            match lc.morning_brief(&id, today) {
                Ok(brief) => block.push(brief),
                Err(e) => block.push(format!("❌ {id}: {e}")),
            }
        }
        if block.len() > 1 {
            parts.push(block.join("\n\n"));
        }
    }
    if parts.is_empty() {
        "(no managed entities configured)".into()
    } else {
        parts.join("\n\n———\n\n")
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn entity_kind_emojis_distinct() {
        let e1 = EntityKind::Project.emoji();
        let e2 = EntityKind::Patient.emoji();
        let e3 = EntityKind::Experiment.emoji();
        assert_ne!(e1, e2);
        assert_ne!(e2, e3);
        assert_ne!(e1, e3);
    }

    #[test]
    fn hot_item_overdue_and_today() {
        let h = HotItem {
            id: "x".into(),
            label: "test".into(),
            days_to: -3,
            criticality: "high".into(),
            blockers: vec![],
        };
        assert!(h.is_overdue());
        assert!(!h.is_today());
        assert!(h.is_hot()); // negative ≤ 7

        let today = HotItem { days_to: 0, ..h.clone() };
        assert!(today.is_today());
        assert!(today.is_hot());

        let in_10 = HotItem { days_to: 10, criticality: "high".into(), ..h.clone() };
        assert!(in_10.is_hot()); // high crit && ≤ 14

        let in_10_med = HotItem { days_to: 10, criticality: "medium".into(), ..h.clone() };
        assert!(!in_10_med.is_hot()); // medium && > 7

        let in_8 = HotItem { days_to: 8, criticality: "low".into(), ..h.clone() };
        assert!(!in_8.is_hot());
    }

    /// Smoke test: trait is object-safe (compiles with `Box<dyn Lifecycle>`).
    #[test]
    fn lifecycle_is_object_safe() {
        struct StubLifecycle;
        impl Lifecycle for StubLifecycle {
            fn kind(&self) -> EntityKind { EntityKind::Project }
            fn list_entities(&self) -> Vec<String> { vec![] }
            fn current_phase(&self, _: &str) -> Result<String, LifecycleError> {
                Ok("DRAFT".into())
            }
            fn legal_phases(&self, _: &str) -> Vec<String> { vec![] }
            fn next_actions(&self, _: &str) -> Vec<&'static str> { vec![] }
            fn hot_items(&self, _: &str, _: NaiveDate)
                -> Result<Vec<HotItem>, LifecycleError> { Ok(vec![]) }
            fn overdue_items(&self, _: &str, _: NaiveDate)
                -> Result<Vec<HotItem>, LifecycleError> { Ok(vec![]) }
            fn morning_brief(&self, _: &str, _: NaiveDate)
                -> Result<String, LifecycleError> { Ok(String::new()) }
        }
        let bx: Box<dyn Lifecycle> = Box::new(StubLifecycle);
        assert_eq!(bx.kind(), EntityKind::Project);
    }

    #[test]
    fn render_unified_empty_returns_placeholder() {
        let lifecycles: Vec<Box<dyn Lifecycle>> = vec![];
        let today = NaiveDate::from_ymd_opt(2026, 5, 6).unwrap();
        let brief = render_unified_brief(&lifecycles, today);
        assert!(brief.contains("no managed entities"));
    }
}
