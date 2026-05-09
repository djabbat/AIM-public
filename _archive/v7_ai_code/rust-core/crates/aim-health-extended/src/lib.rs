//! aim-health-extended — full system health snapshot (G9).
//!
//! Port of `agents/health_extended.py`. Aggregates project / eval /
//! memory / cost signals into ONE structured report suitable for
//! monitoring dashboards (`/healthz/full` style).
//!
//! ## Pluggable
//! Every subsystem probe is a [`Probe`] impl — production wires real
//! aim-project-owner / aim-cost-monitor / aim-evals queries; tests
//! inject [`StubProbe`] with pre-baked snapshots.
//!
//! ## Classifier
//! [`classify_overall`] turns the assembled report into `Overall::Ok`
//! / `Warn` / `Degraded` plus the warning list — same thresholds as
//! Python:
//! - `daily_pct ≥ 1.0` → degraded ("daily cost over budget")
//! - `daily_pct ≥ 0.85` → warn ("daily cost near budget")
//! - `broken_paths > 50` → warn
//! - `overdue_milestones > 0` → warn
//! - `self_health.status` ∉ {"ok", "unavailable", null} → degraded
//! - `deadlines.today ≥ 5` → warn

use chrono::{NaiveDate, Utc};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Overall {
    Ok,
    Warn,
    Degraded,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
pub struct SelfHealthSnapshot {
    /// "ok" / "warn" / "error" / "unavailable" / custom string from the
    /// host's `self_health.report()` impl.
    #[serde(default)]
    pub status: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub detail: Option<String>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct ProjectsSnapshot {
    pub count: u32,
    pub archived: u32,
    pub hot_milestones: u32,
    pub overdue_milestones: u32,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
pub struct EvalSnapshot {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub latest_version: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub latest_score: Option<f64>,
    /// Mean score over last 7 days minus the preceding 7. None when
    /// data is sparse.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub trend_7d: Option<f64>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct MemorySnapshot {
    pub scanned: u32,
    pub findings_total: u32,
    pub broken_paths: u32,
    pub obsolete_deadlines: u32,
    pub duplicates: u32,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
pub struct CostSnapshot {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub daily: Option<f64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub weekly: Option<f64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub monthly: Option<f64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub daily_pct: Option<f64>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct StakeholderSnapshot {
    pub overdue_count: u32,
    pub awaiting_count: u32,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct DeadlinesSnapshot {
    pub today: u32,
    pub this_week: u32,
    pub overdue: u32,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct CronSnapshot {
    /// Free-form `event_name → ISO timestamp` map populated from the
    /// host's per-script audit logs.
    #[serde(default)]
    pub events: std::collections::BTreeMap<String, String>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
pub struct Subsystems {
    pub self_health: SelfHealthSnapshot,
    pub projects: ProjectsSnapshot,
    pub eval: EvalSnapshot,
    pub memory_hygiene: MemorySnapshot,
    pub cost: CostSnapshot,
    pub stakeholders: StakeholderSnapshot,
    pub deadlines: DeadlinesSnapshot,
    pub cron: CronSnapshot,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct HealthReport {
    pub ts: String,
    pub overall: Overall,
    pub warnings: Vec<String>,
    pub subsystems: Subsystems,
}

// ── probes ──────────────────────────────────────────────────────────────

/// Pluggable subsystem probe. Production wires real aim-* dependencies;
/// tests inject StubProbe with pre-baked snapshots.
pub trait Probe: Send + Sync {
    fn self_health(&self) -> SelfHealthSnapshot;
    fn projects(&self, today: NaiveDate) -> ProjectsSnapshot;
    fn eval(&self, today: NaiveDate) -> EvalSnapshot;
    fn memory(&self) -> MemorySnapshot;
    fn cost(&self, today: NaiveDate) -> CostSnapshot;
    fn stakeholders(&self, today: NaiveDate) -> StakeholderSnapshot;
    fn deadlines(&self, today: NaiveDate) -> DeadlinesSnapshot;
    fn cron(&self) -> CronSnapshot;
}

/// Test-friendly probe: every subsystem returns a pre-baked snapshot.
#[derive(Debug, Default, Clone)]
pub struct StubProbe {
    pub self_health: SelfHealthSnapshot,
    pub projects: ProjectsSnapshot,
    pub eval: EvalSnapshot,
    pub memory: MemorySnapshot,
    pub cost: CostSnapshot,
    pub stakeholders: StakeholderSnapshot,
    pub deadlines: DeadlinesSnapshot,
    pub cron: CronSnapshot,
}

impl Probe for StubProbe {
    fn self_health(&self) -> SelfHealthSnapshot {
        self.self_health.clone()
    }
    fn projects(&self, _today: NaiveDate) -> ProjectsSnapshot {
        self.projects.clone()
    }
    fn eval(&self, _today: NaiveDate) -> EvalSnapshot {
        self.eval.clone()
    }
    fn memory(&self) -> MemorySnapshot {
        self.memory.clone()
    }
    fn cost(&self, _today: NaiveDate) -> CostSnapshot {
        self.cost.clone()
    }
    fn stakeholders(&self, _today: NaiveDate) -> StakeholderSnapshot {
        self.stakeholders.clone()
    }
    fn deadlines(&self, _today: NaiveDate) -> DeadlinesSnapshot {
        self.deadlines.clone()
    }
    fn cron(&self) -> CronSnapshot {
        self.cron.clone()
    }
}

// ── classifier ─────────────────────────────────────────────────────────

pub fn classify_overall(s: &Subsystems) -> (Overall, Vec<String>) {
    let mut warnings = Vec::new();

    if let Some(pct) = s.cost.daily_pct {
        if pct >= 1.0 {
            warnings.push(format!("daily cost over budget ({:.0}%)", pct * 100.0));
        } else if pct >= 0.85 {
            warnings.push(format!("daily cost near budget ({:.0}%)", pct * 100.0));
        }
    }

    if s.memory_hygiene.broken_paths > 50 {
        warnings.push(format!(
            "{} broken memory paths",
            s.memory_hygiene.broken_paths
        ));
    }

    if s.projects.overdue_milestones > 0 {
        warnings.push(format!(
            "{} overdue milestones",
            s.projects.overdue_milestones
        ));
    }

    if let Some(status) = &s.self_health.status {
        if status != "ok" && status != "unavailable" {
            warnings.push(format!("self_health: {status}"));
        }
    }

    if s.deadlines.today >= 5 {
        warnings.push(format!("{} deadlines today", s.deadlines.today));
    }

    let overall = if warnings
        .iter()
        .any(|w| w.contains("over budget") || w.contains("self_health"))
    {
        Overall::Degraded
    } else if !warnings.is_empty() {
        Overall::Warn
    } else {
        Overall::Ok
    };
    (overall, warnings)
}

/// Build a full health report from a probe. Stamps `ts` with `Utc::now`.
pub fn report(probe: &dyn Probe, today: NaiveDate) -> HealthReport {
    let subs = Subsystems {
        self_health: probe.self_health(),
        projects: probe.projects(today),
        eval: probe.eval(today),
        memory_hygiene: probe.memory(),
        cost: probe.cost(today),
        stakeholders: probe.stakeholders(today),
        deadlines: probe.deadlines(today),
        cron: probe.cron(),
    };
    let (overall, warnings) = classify_overall(&subs);
    HealthReport {
        ts: Utc::now().format("%Y-%m-%dT%H:%M:%S").to_string(),
        overall,
        warnings,
        subsystems: subs,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn d() -> NaiveDate {
        NaiveDate::from_ymd_opt(2026, 5, 4).unwrap()
    }

    #[test]
    fn ok_when_no_signals() {
        let s = Subsystems::default();
        let (o, w) = classify_overall(&s);
        assert_eq!(o, Overall::Ok);
        assert!(w.is_empty());
    }

    #[test]
    fn cost_at_85_pct_warns() {
        let mut s = Subsystems::default();
        s.cost.daily_pct = Some(0.85);
        let (o, w) = classify_overall(&s);
        assert_eq!(o, Overall::Warn);
        assert!(w[0].contains("near budget"));
        assert!(w[0].contains("85%"));
    }

    #[test]
    fn cost_over_100_pct_degrades() {
        let mut s = Subsystems::default();
        s.cost.daily_pct = Some(1.20);
        let (o, w) = classify_overall(&s);
        assert_eq!(o, Overall::Degraded);
        assert!(w[0].contains("over budget"));
        assert!(w[0].contains("120%"));
    }

    #[test]
    fn cost_under_85_silent() {
        let mut s = Subsystems::default();
        s.cost.daily_pct = Some(0.50);
        let (o, w) = classify_overall(&s);
        assert_eq!(o, Overall::Ok);
        assert!(w.is_empty());
    }

    #[test]
    fn many_broken_paths_warns() {
        let mut s = Subsystems::default();
        s.memory_hygiene.broken_paths = 51;
        let (o, w) = classify_overall(&s);
        assert_eq!(o, Overall::Warn);
        assert!(w[0].contains("51 broken"));
    }

    #[test]
    fn fifty_broken_paths_silent() {
        let mut s = Subsystems::default();
        s.memory_hygiene.broken_paths = 50;
        let (o, _) = classify_overall(&s);
        assert_eq!(o, Overall::Ok);
    }

    #[test]
    fn overdue_milestones_warn() {
        let mut s = Subsystems::default();
        s.projects.overdue_milestones = 3;
        let (o, w) = classify_overall(&s);
        assert_eq!(o, Overall::Warn);
        assert!(w[0].contains("3 overdue milestones"));
    }

    #[test]
    fn self_health_error_degrades() {
        let mut s = Subsystems::default();
        s.self_health.status = Some("error".into());
        let (o, w) = classify_overall(&s);
        assert_eq!(o, Overall::Degraded);
        assert!(w[0].contains("self_health: error"));
    }

    #[test]
    fn self_health_ok_silent() {
        let mut s = Subsystems::default();
        s.self_health.status = Some("ok".into());
        let (o, _) = classify_overall(&s);
        assert_eq!(o, Overall::Ok);
    }

    #[test]
    fn self_health_unavailable_silent() {
        let mut s = Subsystems::default();
        s.self_health.status = Some("unavailable".into());
        let (o, _) = classify_overall(&s);
        assert_eq!(o, Overall::Ok);
    }

    #[test]
    fn five_deadlines_today_warns() {
        let mut s = Subsystems::default();
        s.deadlines.today = 5;
        let (o, w) = classify_overall(&s);
        assert_eq!(o, Overall::Warn);
        assert!(w[0].contains("5 deadlines today"));
    }

    #[test]
    fn four_deadlines_today_silent() {
        let mut s = Subsystems::default();
        s.deadlines.today = 4;
        let (o, _) = classify_overall(&s);
        assert_eq!(o, Overall::Ok);
    }

    #[test]
    fn degraded_dominates_warn() {
        let mut s = Subsystems::default();
        s.cost.daily_pct = Some(1.10); // degraded
        s.deadlines.today = 5; // warn
        let (o, _) = classify_overall(&s);
        assert_eq!(o, Overall::Degraded);
    }

    #[test]
    fn report_assembles_all_subsystems() {
        let stub = StubProbe {
            self_health: SelfHealthSnapshot {
                status: Some("ok".into()),
                ..Default::default()
            },
            projects: ProjectsSnapshot {
                count: 4,
                archived: 1,
                hot_milestones: 2,
                overdue_milestones: 0,
            },
            eval: EvalSnapshot {
                latest_version: Some("v1".into()),
                latest_score: Some(0.82),
                trend_7d: Some(0.04),
            },
            memory: MemorySnapshot {
                scanned: 100,
                findings_total: 3,
                broken_paths: 1,
                obsolete_deadlines: 0,
                duplicates: 2,
            },
            cost: CostSnapshot {
                daily: Some(2.5),
                weekly: Some(15.0),
                monthly: Some(60.0),
                daily_pct: Some(0.5),
            },
            stakeholders: StakeholderSnapshot {
                overdue_count: 1,
                awaiting_count: 4,
            },
            deadlines: DeadlinesSnapshot {
                today: 1,
                this_week: 3,
                overdue: 0,
            },
            cron: CronSnapshot {
                events: [(
                    "last_notification".to_string(),
                    "2026-05-04T08:00:00".to_string(),
                )]
                .into_iter()
                .collect(),
            },
        };
        let r = report(&stub, d());
        assert_eq!(r.overall, Overall::Ok);
        assert!(r.warnings.is_empty());
        assert_eq!(r.subsystems.projects.count, 4);
        assert_eq!(r.subsystems.eval.latest_score, Some(0.82));
        assert!(!r.ts.is_empty());
    }

    #[test]
    fn report_serialises_to_json() {
        let stub = StubProbe::default();
        let r = report(&stub, d());
        let raw = serde_json::to_string(&r).unwrap();
        assert!(raw.contains("\"overall\":\"ok\""));
        assert!(raw.contains("\"subsystems\""));
        assert!(raw.contains("\"projects\""));
        let back: HealthReport = serde_json::from_str(&raw).unwrap();
        assert_eq!(back, r);
    }

    #[test]
    fn warnings_include_all_active_signals() {
        let mut s = Subsystems::default();
        s.cost.daily_pct = Some(0.90);
        s.memory_hygiene.broken_paths = 75;
        s.projects.overdue_milestones = 2;
        s.deadlines.today = 6;
        let (o, w) = classify_overall(&s);
        // Warn (no degrade triggers — 0.90 < 1.0, self_health silent)
        assert_eq!(o, Overall::Warn);
        assert_eq!(w.len(), 4);
    }

    #[test]
    fn cron_events_round_trip() {
        let mut events = std::collections::BTreeMap::new();
        events.insert("last_brief".to_string(), "2026-05-04T07:00:00".to_string());
        events.insert(
            "last_eval".to_string(),
            "2026-05-04T03:30:00".to_string(),
        );
        let stub = StubProbe {
            cron: CronSnapshot { events },
            ..Default::default()
        };
        let r = report(&stub, d());
        assert_eq!(r.subsystems.cron.events.len(), 2);
        let raw = serde_json::to_string(&r.subsystems.cron).unwrap();
        assert!(raw.contains("last_brief"));
    }
}
