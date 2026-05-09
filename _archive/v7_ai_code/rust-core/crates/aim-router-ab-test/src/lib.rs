//! aim-router-ab-test — A/B logging for smart-routing decisions.
//!
//! Port of `agents/router_ab_test.py`. Python uses sqlite, but the
//! interesting logic is the trial schema, feedback validation, and the
//! by-tier stats roll-up. We keep that here on top of an in-memory
//! [`TrialStore`] trait so the prod sqlite implementation can drop in
//! later without touching the math.

use std::collections::BTreeMap;

use chrono::{DateTime, Utc};
use parking_lot::Mutex;
use serde::{Deserialize, Serialize};

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Feedback {
    Good,
    Bad,
    Neutral,
}

impl Feedback {
    pub fn parse(s: &str) -> Option<Feedback> {
        match s {
            "good" => Some(Feedback::Good),
            "bad" => Some(Feedback::Bad),
            "neutral" => Some(Feedback::Neutral),
            _ => None,
        }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct Trial {
    pub id: u64,
    pub ts: String,
    pub task_preview: String,
    pub tier_assigned: String,
    pub model_assigned: String,
    pub tier_actual: String,
    pub model_actual: String,
    pub latency_ms: u64,
    pub cost_usd: f64,
    pub user_feedback: Option<Feedback>,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct LogParams<'a> {
    pub task: &'a str,
    pub tier_assigned: &'a str,
    pub model_assigned: &'a str,
    pub tier_actual: Option<&'a str>,
    pub model_actual: Option<&'a str>,
    pub latency_ms: u64,
    pub cost_usd: f64,
}

pub trait TrialStore: Send + Sync {
    fn insert(&self, t: Trial) -> u64;
    fn set_feedback(&self, id: u64, fb: Feedback) -> bool;
    fn list_recent(&self, limit: usize) -> Vec<Trial>;
    fn all(&self) -> Vec<Trial>;
}

#[derive(Default)]
pub struct InMemStore {
    inner: Mutex<InMemInner>,
}

#[derive(Default)]
struct InMemInner {
    next_id: u64,
    rows: Vec<Trial>,
}

impl InMemStore {
    pub fn new() -> Self {
        Self::default()
    }
}

impl TrialStore for InMemStore {
    fn insert(&self, mut t: Trial) -> u64 {
        let mut g = self.inner.lock();
        g.next_id += 1;
        t.id = g.next_id;
        let id = t.id;
        g.rows.push(t);
        id
    }
    fn set_feedback(&self, id: u64, fb: Feedback) -> bool {
        let mut g = self.inner.lock();
        if let Some(row) = g.rows.iter_mut().find(|r| r.id == id) {
            row.user_feedback = Some(fb);
            true
        } else {
            false
        }
    }
    fn list_recent(&self, limit: usize) -> Vec<Trial> {
        let g = self.inner.lock();
        let mut sorted = g.rows.clone();
        sorted.sort_by(|a, b| b.ts.cmp(&a.ts));
        sorted.truncate(limit);
        sorted
    }
    fn all(&self) -> Vec<Trial> {
        self.inner.lock().rows.clone()
    }
}

pub trait Clock: Send + Sync {
    fn now(&self) -> DateTime<Utc>;
}

pub struct ManualClock {
    t: Mutex<DateTime<Utc>>,
}
impl ManualClock {
    pub fn new(t: DateTime<Utc>) -> Self {
        Self { t: Mutex::new(t) }
    }
    pub fn set(&self, t: DateTime<Utc>) {
        *self.t.lock() = t;
    }
    pub fn advance_secs(&self, s: i64) {
        let mut g = self.t.lock();
        *g = *g + chrono::Duration::seconds(s);
    }
}
impl Clock for ManualClock {
    fn now(&self) -> DateTime<Utc> {
        *self.t.lock()
    }
}

pub fn log_trial(store: &dyn TrialStore, clock: &dyn Clock, p: &LogParams) -> u64 {
    let preview: String = p.task.chars().take(120).collect();
    let trial = Trial {
        id: 0,
        ts: clock.now().format("%Y-%m-%dT%H:%M:%S").to_string(),
        task_preview: preview,
        tier_assigned: p.tier_assigned.into(),
        model_assigned: p.model_assigned.into(),
        tier_actual: p.tier_actual.unwrap_or(p.tier_assigned).into(),
        model_actual: p.model_actual.unwrap_or(p.model_assigned).into(),
        latency_ms: p.latency_ms,
        cost_usd: round6(p.cost_usd),
        user_feedback: None,
    };
    store.insert(trial)
}

fn round6(v: f64) -> f64 {
    (v * 1_000_000.0).round() / 1_000_000.0
}

pub fn record_feedback(store: &dyn TrialStore, id: u64, value: &str) -> bool {
    match Feedback::parse(value) {
        Some(fb) => store.set_feedback(id, fb),
        None => false,
    }
}

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct TierStats {
    pub trials: u64,
    pub avg_latency_ms: f64,
    pub avg_cost_usd: f64,
    pub good: u64,
    pub bad: u64,
    pub good_rate: Option<f64>,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct StatsReport {
    pub total: u64,
    pub rated: u64,
    pub by_tier: BTreeMap<String, TierStats>,
}

pub fn stats(store: &dyn TrialStore) -> StatsReport {
    let rows = store.all();
    let total = rows.len() as u64;
    let rated = rows.iter().filter(|r| r.user_feedback.is_some()).count() as u64;
    let mut by_tier: BTreeMap<String, (u64, f64, f64, u64, u64)> = BTreeMap::new();
    for r in &rows {
        let e = by_tier
            .entry(r.tier_assigned.clone())
            .or_insert((0, 0.0, 0.0, 0, 0));
        e.0 += 1;
        e.1 += r.latency_ms as f64;
        e.2 += r.cost_usd;
        if r.user_feedback == Some(Feedback::Good) {
            e.3 += 1;
        }
        if r.user_feedback == Some(Feedback::Bad) {
            e.4 += 1;
        }
    }
    let mut out = BTreeMap::new();
    for (tier, (n, lat_sum, cost_sum, good, bad)) in by_tier {
        let avg_lat = if n > 0 { lat_sum / n as f64 } else { 0.0 };
        let avg_cost = if n > 0 { cost_sum / n as f64 } else { 0.0 };
        let rated_n = good + bad;
        let good_rate = if rated_n > 0 {
            Some(((good as f64) / (rated_n as f64) * 1000.0).round() / 1000.0)
        } else {
            None
        };
        out.insert(
            tier,
            TierStats {
                trials: n,
                avg_latency_ms: ((avg_lat) * 10.0).round() / 10.0,
                avg_cost_usd: round6(avg_cost),
                good,
                bad,
                good_rate,
            },
        );
    }
    StatsReport {
        total,
        rated,
        by_tier: out,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;

    fn fixed_clock() -> ManualClock {
        ManualClock::new(Utc.with_ymd_and_hms(2026, 5, 5, 12, 0, 0).unwrap())
    }

    fn add(
        store: &dyn TrialStore,
        clock: &ManualClock,
        tier: &str,
        model: &str,
        lat: u64,
        cost: f64,
    ) -> u64 {
        let id = log_trial(
            store,
            clock,
            &LogParams {
                task: "task text",
                tier_assigned: tier,
                model_assigned: model,
                tier_actual: None,
                model_actual: None,
                latency_ms: lat,
                cost_usd: cost,
            },
        );
        clock.advance_secs(1);
        id
    }

    // ── log_trial ─────────────────────────────────────────────────────────

    #[test]
    fn log_trial_assigns_increasing_ids() {
        let store = InMemStore::new();
        let clock = fixed_clock();
        let id1 = add(&store, &clock, "fast", "groq", 100, 0.001);
        let id2 = add(&store, &clock, "fast", "groq", 110, 0.002);
        assert_eq!(id1, 1);
        assert_eq!(id2, 2);
    }

    #[test]
    fn log_trial_truncates_task_to_120_chars() {
        let store = InMemStore::new();
        let clock = fixed_clock();
        let task = "a".repeat(500);
        let id = log_trial(
            &store,
            &clock,
            &LogParams {
                task: &task,
                tier_assigned: "default",
                model_assigned: "ds",
                ..Default::default()
            },
        );
        let row = store.all().into_iter().find(|r| r.id == id).unwrap();
        assert_eq!(row.task_preview.chars().count(), 120);
    }

    #[test]
    fn log_trial_actual_falls_back_to_assigned() {
        let store = InMemStore::new();
        let clock = fixed_clock();
        let id = add(&store, &clock, "deep", "ds-pro", 300, 0.01);
        let row = store.all().into_iter().find(|r| r.id == id).unwrap();
        assert_eq!(row.tier_actual, "deep");
        assert_eq!(row.model_actual, "ds-pro");
    }

    #[test]
    fn log_trial_rounds_cost_to_six_decimals() {
        let store = InMemStore::new();
        let clock = fixed_clock();
        let id = log_trial(
            &store,
            &clock,
            &LogParams {
                task: "t",
                tier_assigned: "fast",
                model_assigned: "groq",
                cost_usd: 0.0123456789,
                ..Default::default()
            },
        );
        let row = store.all().into_iter().find(|r| r.id == id).unwrap();
        assert!((row.cost_usd - 0.012346).abs() < 1e-9);
    }

    // ── feedback ──────────────────────────────────────────────────────────

    #[test]
    fn feedback_accepts_good_bad_neutral() {
        let store = InMemStore::new();
        let clock = fixed_clock();
        let id = add(&store, &clock, "fast", "g", 1, 0.0);
        assert!(record_feedback(&store, id, "good"));
        assert!(record_feedback(&store, id, "bad"));
        assert!(record_feedback(&store, id, "neutral"));
    }

    #[test]
    fn feedback_rejects_unknown_value() {
        let store = InMemStore::new();
        let clock = fixed_clock();
        let id = add(&store, &clock, "fast", "g", 1, 0.0);
        assert!(!record_feedback(&store, id, "great"));
    }

    #[test]
    fn feedback_unknown_id_returns_false() {
        let store = InMemStore::new();
        assert!(!record_feedback(&store, 999, "good"));
    }

    // ── list_recent ───────────────────────────────────────────────────────

    #[test]
    fn list_recent_orders_by_ts_desc() {
        let store = InMemStore::new();
        let clock = fixed_clock();
        add(&store, &clock, "fast", "g", 1, 0.0);
        add(&store, &clock, "deep", "p", 1, 0.0);
        add(&store, &clock, "default", "f", 1, 0.0);
        let r = store.list_recent(2);
        assert_eq!(r.len(), 2);
        assert_eq!(r[0].tier_assigned, "default");
        assert_eq!(r[1].tier_assigned, "deep");
    }

    // ── stats ─────────────────────────────────────────────────────────────

    #[test]
    fn stats_aggregates_by_tier() {
        let store = InMemStore::new();
        let clock = fixed_clock();
        let id1 = add(&store, &clock, "fast", "g", 100, 0.001);
        let id2 = add(&store, &clock, "fast", "g", 200, 0.002);
        let _id3 = add(&store, &clock, "deep", "p", 500, 0.01);
        record_feedback(&store, id1, "good");
        record_feedback(&store, id2, "bad");
        let s = stats(&store);
        assert_eq!(s.total, 3);
        assert_eq!(s.rated, 2);
        let fast = &s.by_tier["fast"];
        assert_eq!(fast.trials, 2);
        assert_eq!(fast.avg_latency_ms, 150.0);
        assert_eq!(fast.good, 1);
        assert_eq!(fast.bad, 1);
        assert_eq!(fast.good_rate, Some(0.5));
        let deep = &s.by_tier["deep"];
        assert_eq!(deep.trials, 1);
        assert_eq!(deep.good_rate, None); // unrated
    }

    #[test]
    fn stats_empty_store() {
        let store = InMemStore::new();
        let s = stats(&store);
        assert_eq!(s.total, 0);
        assert_eq!(s.rated, 0);
        assert!(s.by_tier.is_empty());
    }

    // ── feedback enum ─────────────────────────────────────────────────────

    #[test]
    fn feedback_parse_unknown() {
        assert_eq!(Feedback::parse("good"), Some(Feedback::Good));
        assert_eq!(Feedback::parse("nope"), None);
    }
}
