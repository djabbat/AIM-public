//! aim-kpi-auto-updater — observed-signal → KPI bridge (P7).
//!
//! Port of `agents/kpi_auto_updater.py`. Subscribes a KPI to a *named
//! source* and pushes the latest observed value into the KPI history on
//! every scheduling tick. Idempotent within a day.
//!
//! Sources, project enumeration, and the KPI store are all pluggable.

use std::collections::BTreeMap;

use chrono::NaiveDate;
use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum KpiError {
    #[error("unknown source: {0}")]
    UnknownSource(String),
    #[error("store error: {0}")]
    Store(String),
}

pub type Result<T> = std::result::Result<T, KpiError>;

// ── data ────────────────────────────────────────────────────────────────────

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct KpiPoint {
    pub date: NaiveDate,
    pub value: f64,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct Kpi {
    pub id: String,
    pub source: Option<String>,
    pub history: Vec<KpiPoint>,
}

impl Kpi {
    pub fn has_point_on(&self, date: NaiveDate) -> bool {
        self.history.iter().any(|p| p.date == date)
    }
}

// ── sources ─────────────────────────────────────────────────────────────────

/// A source produces a value for a given date. Returning `None` means
/// "no observation today" — caller skips, no error.
pub trait Source: Send + Sync {
    fn fetch(&self, date: NaiveDate) -> Option<f64>;
}

/// Constant-value source — useful for tests.
pub struct ConstantSource(pub f64);
impl Source for ConstantSource {
    fn fetch(&self, _date: NaiveDate) -> Option<f64> {
        Some(self.0)
    }
}

/// Always-fails source — useful for "source missing" tests.
pub struct EmptySource;
impl Source for EmptySource {
    fn fetch(&self, _date: NaiveDate) -> Option<f64> {
        None
    }
}

/// Source registry. Production wires `cost.weekly`, `stakeholders.total`,
/// `eval.latest`, etc; tests use the [`SourceMap`] convenience.
pub trait SourceRegistry: Send + Sync {
    fn get(&self, name: &str) -> Option<&dyn Source>;
}

#[derive(Default)]
pub struct SourceMap {
    inner: BTreeMap<String, Box<dyn Source>>,
}

impl SourceMap {
    pub fn new() -> Self {
        Self::default()
    }
    pub fn insert(&mut self, name: impl Into<String>, source: Box<dyn Source>) {
        self.inner.insert(name.into(), source);
    }
    pub fn names(&self) -> Vec<String> {
        self.inner.keys().cloned().collect()
    }
}

impl SourceRegistry for SourceMap {
    fn get(&self, name: &str) -> Option<&dyn Source> {
        self.inner.get(name).map(|b| b.as_ref())
    }
}

/// The 8 source names from the Python module — provided as constants
/// so production wiring stays in lockstep with the YAML schema.
pub const SOURCE_COST_DAILY: &str = "cost.daily";
pub const SOURCE_COST_WEEKLY: &str = "cost.weekly";
pub const SOURCE_COST_MONTHLY: &str = "cost.monthly";
pub const SOURCE_STAKEHOLDERS_TOTAL: &str = "stakeholders.total";
pub const SOURCE_STAKEHOLDERS_OVERDUE: &str = "stakeholders.overdue";
pub const SOURCE_EVAL_LATEST: &str = "eval.latest";
pub const SOURCE_MEMORY_FINDINGS: &str = "memory.findings";
pub const SOURCE_LITERATURE_OWN_COUNT: &str = "literature.own_count";

pub fn known_source_names() -> &'static [&'static str] {
    &[
        SOURCE_COST_DAILY,
        SOURCE_COST_WEEKLY,
        SOURCE_COST_MONTHLY,
        SOURCE_STAKEHOLDERS_TOTAL,
        SOURCE_STAKEHOLDERS_OVERDUE,
        SOURCE_EVAL_LATEST,
        SOURCE_MEMORY_FINDINGS,
        SOURCE_LITERATURE_OWN_COUNT,
    ]
}

// ── store ───────────────────────────────────────────────────────────────────

/// Pluggable per-project KPI store.
pub trait KpiStore: Send + Sync {
    fn list_projects(&self) -> Vec<String>;
    fn load_kpis(&self, project: &str) -> Vec<Kpi>;
    fn record(&self, project: &str, kpi_id: &str, value: f64, date: NaiveDate) -> Result<()>;
}

/// In-memory store. Production wires rusqlite + YAML readers.
#[derive(Default)]
pub struct InMemKpiStore {
    inner: parking_lot::Mutex<BTreeMap<String, Vec<Kpi>>>,
}

impl InMemKpiStore {
    pub fn new() -> Self {
        Self::default()
    }
    pub fn add_project(&self, name: &str, kpis: Vec<Kpi>) {
        self.inner.lock().insert(name.into(), kpis);
    }
    pub fn snapshot(&self, project: &str) -> Vec<Kpi> {
        self.inner.lock().get(project).cloned().unwrap_or_default()
    }
}

impl KpiStore for InMemKpiStore {
    fn list_projects(&self) -> Vec<String> {
        self.inner.lock().keys().cloned().collect()
    }
    fn load_kpis(&self, project: &str) -> Vec<Kpi> {
        self.inner.lock().get(project).cloned().unwrap_or_default()
    }
    fn record(&self, project: &str, kpi_id: &str, value: f64, date: NaiveDate) -> Result<()> {
        let mut map = self.inner.lock();
        let kpis = map.entry(project.to_string()).or_default();
        if let Some(k) = kpis.iter_mut().find(|k| k.id == kpi_id) {
            // Idempotent on (kpi_id, date) — replace if same date.
            if let Some(existing) = k.history.iter_mut().find(|p| p.date == date) {
                existing.value = value;
            } else {
                k.history.push(KpiPoint { date, value });
            }
        } else {
            kpis.push(Kpi {
                id: kpi_id.into(),
                source: None,
                history: vec![KpiPoint { date, value }],
            });
        }
        Ok(())
    }
}

// ── orchestrator ───────────────────────────────────────────────────────────

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct SyncResult {
    /// `project → [(kpi_id, value), …]` for successful updates.
    pub updates: BTreeMap<String, Vec<(String, f64)>>,
}

pub struct KpiSyncer<'a> {
    pub store: &'a dyn KpiStore,
    pub sources: &'a dyn SourceRegistry,
}

impl<'a> KpiSyncer<'a> {
    pub fn new(store: &'a dyn KpiStore, sources: &'a dyn SourceRegistry) -> Self {
        Self { store, sources }
    }

    /// Walk every project's KPIs; for each KPI with a registered source,
    /// record() its latest observed value. Idempotent within a day.
    pub fn sync(&self, today: NaiveDate) -> SyncResult {
        let mut out: BTreeMap<String, Vec<(String, f64)>> = BTreeMap::new();
        for project in self.store.list_projects() {
            let kpis = self.store.load_kpis(&project);
            for k in kpis {
                let Some(src_name) = k.source.as_deref() else {
                    continue;
                };
                let Some(src) = self.sources.get(src_name) else {
                    continue;
                };
                if k.has_point_on(today) {
                    continue;
                }
                let Some(value) = src.fetch(today) else {
                    continue;
                };
                if self.store.record(&project, &k.id, value, today).is_ok() {
                    out.entry(project.clone()).or_default().push((k.id.clone(), value));
                }
            }
        }
        SyncResult { updates: out }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::Datelike;

    fn date(y: i32, m: u32, d: u32) -> NaiveDate {
        NaiveDate::from_ymd_opt(y, m, d).unwrap()
    }

    fn make_kpi(id: &str, source: Option<&str>, points: Vec<(NaiveDate, f64)>) -> Kpi {
        Kpi {
            id: id.into(),
            source: source.map(String::from),
            history: points
                .into_iter()
                .map(|(date, value)| KpiPoint { date, value })
                .collect(),
        }
    }

    fn registry_with(pairs: &[(&str, f64)]) -> SourceMap {
        let mut m = SourceMap::new();
        for (name, v) in pairs {
            m.insert(*name, Box::new(ConstantSource(*v)));
        }
        m
    }

    // ── known_source_names ─────────────────────────────────────────────────

    #[test]
    fn known_sources_match_python_set() {
        let names = known_source_names();
        assert_eq!(names.len(), 8);
        assert!(names.contains(&"cost.weekly"));
        assert!(names.contains(&"eval.latest"));
        assert!(names.contains(&"literature.own_count"));
    }

    // ── Kpi.has_point_on ───────────────────────────────────────────────────

    #[test]
    fn has_point_on_finds_existing_date() {
        let k = make_kpi("x", Some("cost.weekly"), vec![(date(2026, 5, 5), 1.0)]);
        assert!(k.has_point_on(date(2026, 5, 5)));
        assert!(!k.has_point_on(date(2026, 5, 6)));
    }

    // ── SourceMap ──────────────────────────────────────────────────────────

    #[test]
    fn source_map_returns_registered_source() {
        let m = registry_with(&[("cost.weekly", 25.0)]);
        let s = m.get("cost.weekly").unwrap();
        assert_eq!(s.fetch(date(2026, 5, 5)), Some(25.0));
        assert!(m.get("missing").is_none());
    }

    #[test]
    fn empty_source_returns_none() {
        let s = EmptySource;
        assert!(s.fetch(date(2026, 5, 5)).is_none());
    }

    // ── InMemKpiStore.record ────────────────────────────────────────────────

    #[test]
    fn store_record_appends_then_replaces_same_date() {
        let store = InMemKpiStore::new();
        store.add_project("FCLC", vec![make_kpi("k", Some("cost.weekly"), vec![])]);
        store.record("FCLC", "k", 10.0, date(2026, 5, 5)).unwrap();
        store.record("FCLC", "k", 20.0, date(2026, 5, 5)).unwrap();
        let kpis = store.snapshot("FCLC");
        assert_eq!(kpis[0].history.len(), 1);
        assert_eq!(kpis[0].history[0].value, 20.0);
        // different date → append
        store.record("FCLC", "k", 30.0, date(2026, 5, 6)).unwrap();
        assert_eq!(store.snapshot("FCLC")[0].history.len(), 2);
    }

    #[test]
    fn store_record_creates_kpi_when_missing() {
        let store = InMemKpiStore::new();
        store.add_project("FCLC", vec![]);
        store.record("FCLC", "new", 5.0, date(2026, 5, 5)).unwrap();
        let kpis = store.snapshot("FCLC");
        assert_eq!(kpis.len(), 1);
        assert_eq!(kpis[0].id, "new");
    }

    // ── sync orchestration ─────────────────────────────────────────────────

    #[test]
    fn sync_records_observed_values_for_known_sources() {
        let store = InMemKpiStore::new();
        store.add_project(
            "FCLC",
            vec![
                make_kpi("weekly-llm-cost", Some("cost.weekly"), vec![]),
                make_kpi("stakeholder-count", Some("stakeholders.total"), vec![]),
            ],
        );
        let reg = registry_with(&[
            ("cost.weekly", 22.5),
            ("stakeholders.total", 7.0),
        ]);
        let s = KpiSyncer::new(&store, &reg);
        let res = s.sync(date(2026, 5, 5));
        let updates = &res.updates["FCLC"];
        assert_eq!(updates.len(), 2);
        let kpis = store.snapshot("FCLC");
        let cost = kpis.iter().find(|k| k.id == "weekly-llm-cost").unwrap();
        assert_eq!(cost.history.len(), 1);
        assert_eq!(cost.history[0].value, 22.5);
        assert_eq!(cost.history[0].date.day(), 5);
    }

    #[test]
    fn sync_skips_kpi_without_source() {
        let store = InMemKpiStore::new();
        store.add_project("p", vec![make_kpi("x", None, vec![])]);
        let reg = registry_with(&[]);
        let s = KpiSyncer::new(&store, &reg);
        let res = s.sync(date(2026, 5, 5));
        assert!(res.updates.is_empty());
        assert!(store.snapshot("p")[0].history.is_empty());
    }

    #[test]
    fn sync_skips_kpi_with_unknown_source() {
        let store = InMemKpiStore::new();
        store.add_project("p", vec![make_kpi("x", Some("xx.unknown"), vec![])]);
        let reg = registry_with(&[]);
        let s = KpiSyncer::new(&store, &reg);
        let res = s.sync(date(2026, 5, 5));
        assert!(res.updates.is_empty());
    }

    #[test]
    fn sync_idempotent_within_a_day() {
        let store = InMemKpiStore::new();
        let today = date(2026, 5, 5);
        store.add_project(
            "p",
            vec![make_kpi(
                "x",
                Some("cost.weekly"),
                vec![(today, 99.0)],
            )],
        );
        let reg = registry_with(&[("cost.weekly", 50.0)]);
        let s = KpiSyncer::new(&store, &reg);
        let res = s.sync(today);
        assert!(res.updates.is_empty());
        // existing point unchanged
        assert_eq!(store.snapshot("p")[0].history[0].value, 99.0);
    }

    #[test]
    fn sync_records_when_source_returns_none_does_not_record() {
        let store = InMemKpiStore::new();
        store.add_project(
            "p",
            vec![make_kpi("x", Some("eval.latest"), vec![])],
        );
        let mut reg = SourceMap::new();
        reg.insert("eval.latest", Box::new(EmptySource));
        let s = KpiSyncer::new(&store, &reg);
        let res = s.sync(date(2026, 5, 5));
        assert!(res.updates.is_empty());
        assert!(store.snapshot("p")[0].history.is_empty());
    }

    #[test]
    fn sync_walks_multiple_projects() {
        let store = InMemKpiStore::new();
        store.add_project("FCLC", vec![make_kpi("a", Some("cost.weekly"), vec![])]);
        store.add_project("CDATA", vec![make_kpi("b", Some("cost.weekly"), vec![])]);
        let reg = registry_with(&[("cost.weekly", 12.5)]);
        let s = KpiSyncer::new(&store, &reg);
        let res = s.sync(date(2026, 5, 5));
        assert_eq!(res.updates.len(), 2);
        assert!(res.updates.contains_key("FCLC"));
        assert!(res.updates.contains_key("CDATA"));
    }
}
