//! aim-pi-agent — Personal Intelligence Agent (background helper).
//!
//! Port of `agents/pi_agent.py`. Watches AIM usage, classifies tasks,
//! produces proactive suggestions based on time-of-day / category /
//! latency patterns. Persistence + memory-organise step are pluggable.

use std::collections::BTreeMap;

use chrono::{DateTime, Datelike, Duration, Timelike, Utc};
use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum PiError {
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
    #[error("storage error: {0}")]
    Store(String),
}

pub type Result<T> = std::result::Result<T, PiError>;

// ── classification ─────────────────────────────────────────────────────────

const KEYWORDS: &[(&str, &[&str])] = &[
    ("coding", &[
        "код", "напиши", "функция", "класс",
        "debug", "исправь", "patch", "implement",
    ]),
    ("research", &[
        "найди", "поищи", "исследование", "статья",
        "pubmed", "doi", "review",
    ]),
    ("memory", &[
        "запомни", "помни", "не забывай",
        "memory", "remember", "recall",
    ]),
    ("analysis", &[
        "анализ", "проанализируй", "сравни", "оцени", "audit",
    ]),
    ("translation", &["переведи", "translate", "перевод"]),
    ("writing", &[
        "напиши письмо", "draft", "email", "ответь", "respond",
    ]),
    ("planning", &[
        "план", "roadmap", "стратегия", "deadline",
    ]),
];

pub fn classify(text: &str) -> &'static str {
    let lower = text.to_lowercase();
    for (cat, kws) in KEYWORDS {
        if kws.iter().any(|k| lower.contains(k)) {
            return cat;
        }
    }
    "general"
}

// ── data ────────────────────────────────────────────────────────────────────

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct TaskRecord {
    pub task: String,
    pub category: String,
    pub duration: f64,
    pub timestamp: DateTime<Utc>,
    pub hour: u32,
    pub weekday: u32,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct PiData {
    pub tasks: Vec<TaskRecord>,
    /// `category → cumulative count` ever observed.
    pub patterns: BTreeMap<String, usize>,
    /// `hour-of-day (0..24) → ring of last-30 task summaries`.
    pub time_based: BTreeMap<u32, Vec<String>>,
}

impl PiData {
    const TASK_HARD_CAP: usize = 1000;
    const TASK_SOFT_CAP: usize = 500;
    const HOUR_RING: usize = 30;
    const TASK_PREFIX_HARD: usize = 300;
    const TASK_PREFIX_HOUR: usize = 80;

    pub fn learn(&mut self, task: &str, duration: f64, now: DateTime<Utc>) {
        if task.is_empty() {
            return;
        }
        let category = classify(task).to_string();
        let task_truncated: String = task.chars().take(Self::TASK_PREFIX_HARD).collect();
        let hour = now.hour();
        let rec = TaskRecord {
            task: task_truncated,
            category: category.clone(),
            duration: round2(duration),
            timestamp: now,
            hour,
            weekday: now.weekday().num_days_from_monday(),
        };
        self.tasks.push(rec);
        if self.tasks.len() > Self::TASK_HARD_CAP {
            let drop_n = self.tasks.len() - Self::TASK_SOFT_CAP;
            self.tasks.drain(..drop_n);
        }
        let hour_ring = self.time_based.entry(hour).or_default();
        let short: String = task.chars().take(Self::TASK_PREFIX_HOUR).collect();
        hour_ring.push(short);
        if hour_ring.len() > Self::HOUR_RING {
            let drop_n = hour_ring.len() - Self::HOUR_RING;
            hour_ring.drain(..drop_n);
        }
        *self.patterns.entry(category).or_insert(0) += 1;
    }
}

fn round2(v: f64) -> f64 {
    (v * 100.0).round() / 100.0
}

// ── suggestions ────────────────────────────────────────────────────────────

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct Suggestion {
    pub kind: String,
    pub msg: String,
}

pub fn suggestions(data: &PiData, now: DateTime<Utc>) -> Vec<Suggestion> {
    let mut out: Vec<Suggestion> = Vec::new();

    // 1. Time-of-day pattern: if 3+ tasks in this hour ring, surface top 3.
    let hour = now.hour();
    if let Some(ring) = data.time_based.get(&hour) {
        if ring.len() >= 3 {
            let mut counts: BTreeMap<&str, usize> = BTreeMap::new();
            for t in ring {
                *counts.entry(t.as_str()).or_insert(0) += 1;
            }
            let mut top: Vec<(&str, usize)> = counts.into_iter().collect();
            top.sort_by(|a, b| b.1.cmp(&a.1).then_with(|| a.0.cmp(b.0)));
            top.truncate(3);
            let pieces: Vec<String> = top
                .iter()
                .map(|(t, c)| format!("{:?}×{}", t, c))
                .collect();
            out.push(Suggestion {
                kind: "time-of-day".into(),
                msg: format!(
                    "в {:02}:00 ты обычно делаешь: {}",
                    hour,
                    pieces.join(", ")
                ),
            });
        }
    }

    // 2. Frequent category in last 50 tasks.
    let recent: Vec<&TaskRecord> = data.tasks.iter().rev().take(50).collect();
    if !recent.is_empty() {
        let mut counts: BTreeMap<&str, usize> = BTreeMap::new();
        for r in &recent {
            *counts.entry(r.category.as_str()).or_insert(0) += 1;
        }
        if let Some((top, n)) = counts.into_iter().max_by_key(|&(_, n)| n) {
            if n >= 5 {
                out.push(Suggestion {
                    kind: "frequent-category".into(),
                    msg: format!(
                        "за последние {} задач: '{}' встречалось {} раз. возможно, нужен шаблон / preset?",
                        recent.len(),
                        top,
                        n
                    ),
                });
            }
        }
    }

    // 3. Long-running tasks: duration > 30s, 3+ in last 50.
    let slow_n = recent.iter().filter(|r| r.duration > 30.0).count();
    if slow_n >= 3 {
        out.push(Suggestion {
            kind: "slow-tasks".into(),
            msg: format!(
                "{} задач из последних {} заняли >30s. проверь circuit breaker / включи cache (AIM_LLM_CACHE=1)?",
                slow_n,
                recent.len()
            ),
        });
    }

    // 4. Categories that existed before last 7d but not since.
    let cutoff = now - Duration::days(7);
    let old_cats: std::collections::BTreeSet<&str> = data
        .tasks
        .iter()
        .filter(|r| r.timestamp < cutoff)
        .map(|r| r.category.as_str())
        .collect();
    let new_cats: std::collections::BTreeSet<&str> = data
        .tasks
        .iter()
        .filter(|r| r.timestamp >= cutoff)
        .map(|r| r.category.as_str())
        .collect();
    let missed: Vec<&str> = old_cats.difference(&new_cats).copied().collect();
    if !missed.is_empty() {
        let mut sorted = missed.clone();
        sorted.sort();
        out.push(Suggestion {
            kind: "missed-category".into(),
            msg: format!(
                "за последнюю неделю не было: {} — намеренно?",
                sorted.join(", ")
            ),
        });
    }
    out
}

// ── stats ──────────────────────────────────────────────────────────────────

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct Stats {
    pub tasks_total: usize,
    pub tasks_recent: usize,
    pub categories: BTreeMap<String, usize>,
    pub avg_duration: f64,
}

pub fn stats(data: &PiData) -> Stats {
    if data.tasks.is_empty() {
        return Stats::default();
    }
    let recent: Vec<&TaskRecord> = data.tasks.iter().rev().take(200).collect();
    let mut categories: BTreeMap<String, usize> = BTreeMap::new();
    for r in &recent {
        *categories.entry(r.category.clone()).or_insert(0) += 1;
    }
    let total_dur: f64 = recent.iter().map(|r| r.duration).sum();
    let avg = round2(total_dur / recent.len().max(1) as f64);
    Stats {
        tasks_total: data.tasks.len(),
        tasks_recent: recent.len(),
        categories,
        avg_duration: avg,
    }
}

// ── persistence trait ──────────────────────────────────────────────────────

pub trait PiStore: Send + Sync {
    fn load(&self) -> Result<PiData>;
    fn save(&self, data: &PiData) -> Result<()>;
}

#[derive(Default)]
pub struct InMemPiStore {
    inner: parking_lot::Mutex<PiData>,
}

impl InMemPiStore {
    pub fn new() -> Self {
        Self::default()
    }
}

impl PiStore for InMemPiStore {
    fn load(&self) -> Result<PiData> {
        Ok(self.inner.lock().clone())
    }
    fn save(&self, data: &PiData) -> Result<()> {
        *self.inner.lock() = data.clone();
        Ok(())
    }
}

// ── orchestrator ───────────────────────────────────────────────────────────

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

pub struct PiAgent<'a> {
    pub store: &'a dyn PiStore,
    pub clock: &'a dyn Clock,
}

impl<'a> PiAgent<'a> {
    pub fn new(store: &'a dyn PiStore, clock: &'a dyn Clock) -> Self {
        Self { store, clock }
    }

    pub fn learn(&self, task: &str, duration: f64) -> Result<()> {
        let mut data = self.store.load()?;
        data.learn(task, duration, self.clock.now());
        self.store.save(&data)
    }

    pub fn suggest(&self) -> Result<Vec<Suggestion>> {
        let data = self.store.load()?;
        Ok(suggestions(&data, self.clock.now()))
    }

    pub fn stats(&self) -> Result<Stats> {
        Ok(stats(&self.store.load()?))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;

    fn dt(secs: i64) -> DateTime<Utc> {
        DateTime::from_timestamp(secs, 0).unwrap()
    }

    fn tuesday_noon() -> DateTime<Utc> {
        Utc.with_ymd_and_hms(2026, 5, 5, 12, 0, 0).unwrap()
    }

    // ── classify ───────────────────────────────────────────────────────────

    #[test]
    fn classify_recognises_category_keywords() {
        assert_eq!(classify("напиши функцию x"), "coding");
        assert_eq!(classify("найди статьи по pubmed"), "research");
        assert_eq!(classify("translate this"), "translation");
        assert_eq!(classify("проанализируй данные"), "analysis");
        assert_eq!(classify("запомни мои настройки"), "memory");
        assert_eq!(classify("план на квартал"), "planning");
        assert_eq!(classify("что сегодня"), "general");
    }

    #[test]
    fn classify_first_match_wins() {
        // text containing both "перевод" (translation) and "помни" (memory):
        // KEYWORDS iteration order — "memory" comes before "translation"
        assert_eq!(classify("помни перевод"), "memory");
    }

    // ── PiData.learn ───────────────────────────────────────────────────────

    #[test]
    fn learn_records_task_with_classification_and_metadata() {
        let mut d = PiData::default();
        let now = tuesday_noon();
        d.learn("напиши функцию foo", 1.234, now);
        assert_eq!(d.tasks.len(), 1);
        assert_eq!(d.tasks[0].category, "coding");
        assert_eq!(d.tasks[0].hour, 12);
        // 2026-05-05 is Tuesday → weekday 1 (Monday=0)
        assert_eq!(d.tasks[0].weekday, 1);
        assert!((d.tasks[0].duration - 1.23).abs() < 1e-9);
        assert_eq!(d.patterns["coding"], 1);
        assert_eq!(d.time_based[&12].len(), 1);
    }

    #[test]
    fn learn_truncates_task_string() {
        let mut d = PiData::default();
        let big = "x".repeat(500);
        d.learn(&big, 0.0, dt(0));
        // hard truncation = 300; hour ring = 80
        assert_eq!(d.tasks[0].task.chars().count(), 300);
        assert_eq!(d.time_based[&0][0].chars().count(), 80);
    }

    #[test]
    fn learn_caps_task_history_at_1000() {
        let mut d = PiData::default();
        // Trim to 500 happens once when the buffer crosses 1000; subsequent
        // appends grow it again until the next crossing. Mirrors Python.
        for i in 0..1100 {
            d.learn(&format!("task {}", i), 0.0, dt(i as i64));
            assert!(d.tasks.len() <= 1000);
        }
        // After 1100 calls: 1000 → trimmed to 500 at call #1001,
        // then +99 calls → final 599
        assert_eq!(d.tasks.len(), 599);
        assert!(d.tasks.last().unwrap().task.contains("1099"));
    }

    #[test]
    fn learn_caps_hour_ring_at_30() {
        let mut d = PiData::default();
        for i in 0..50 {
            d.learn(&format!("task {}", i), 0.0, dt(i as i64));
        }
        let ring = d.time_based.get(&0).unwrap();
        assert_eq!(ring.len(), 30);
        assert!(ring.last().unwrap().contains("49"));
    }

    #[test]
    fn learn_skips_empty_task() {
        let mut d = PiData::default();
        d.learn("", 0.0, dt(0));
        assert!(d.tasks.is_empty());
    }

    // ── suggestions ────────────────────────────────────────────────────────

    #[test]
    fn suggest_time_of_day_when_three_in_ring() {
        let mut d = PiData::default();
        let noon = tuesday_noon();
        for _ in 0..3 {
            d.learn("обычная задача", 0.0, noon);
        }
        let s = suggestions(&d, noon);
        let kind: Vec<&str> = s.iter().map(|x| x.kind.as_str()).collect();
        assert!(kind.contains(&"time-of-day"));
    }

    #[test]
    fn suggest_frequent_category_when_five() {
        let mut d = PiData::default();
        for i in 0..6 {
            d.learn("напиши код N", 0.0, dt(i));
        }
        let s = suggestions(&d, dt(100));
        assert!(s.iter().any(|x| x.kind == "frequent-category" && x.msg.contains("coding")));
    }

    #[test]
    fn suggest_slow_tasks_when_three_over_thirty_seconds() {
        let mut d = PiData::default();
        for i in 0..3 {
            d.learn("slow task", 35.0, dt(i));
        }
        let s = suggestions(&d, dt(100));
        assert!(s.iter().any(|x| x.kind == "slow-tasks"));
    }

    #[test]
    fn suggest_missed_category_when_old_only() {
        let mut d = PiData::default();
        let now = dt(20 * 86_400);
        // Old task (15 days ago) in research
        d.learn("найди статью pubmed", 0.0, now - Duration::days(15));
        // Recent task in coding (last 7d)
        d.learn("напиши функцию", 0.0, now - Duration::days(2));
        let s = suggestions(&d, now);
        assert!(s
            .iter()
            .any(|x| x.kind == "missed-category" && x.msg.contains("research")));
    }

    #[test]
    fn suggest_returns_empty_for_quiet_history() {
        let d = PiData::default();
        let s = suggestions(&d, dt(0));
        assert!(s.is_empty());
    }

    // ── stats ──────────────────────────────────────────────────────────────

    #[test]
    fn stats_summarises_recent_tasks() {
        let mut d = PiData::default();
        for i in 0..10 {
            d.learn("напиши функцию", 5.0, dt(i));
        }
        let s = stats(&d);
        assert_eq!(s.tasks_total, 10);
        assert_eq!(s.tasks_recent, 10);
        assert_eq!(s.categories["coding"], 10);
        assert!((s.avg_duration - 5.0).abs() < 1e-9);
    }

    #[test]
    fn stats_caps_recent_at_200() {
        let mut d = PiData::default();
        for i in 0..300 {
            d.learn("напиши код", 1.0, dt(i));
        }
        let s = stats(&d);
        // total grows beyond cap due to learn-side trim, but stats `recent` cap is 200
        assert!(s.tasks_recent <= 200);
        assert!(s.tasks_total > 200);
    }

    #[test]
    fn stats_empty_returns_default() {
        let d = PiData::default();
        let s = stats(&d);
        assert_eq!(s.tasks_total, 0);
        assert_eq!(s.tasks_recent, 0);
        assert!(s.categories.is_empty());
    }

    // ── PiAgent ────────────────────────────────────────────────────────────

    #[test]
    fn agent_persists_across_calls() {
        let store = InMemPiStore::new();
        let clk = FixedClock(tuesday_noon());
        let agent = PiAgent::new(&store, &clk);
        agent.learn("напиши код", 5.0).unwrap();
        agent.learn("найди статью", 3.0).unwrap();
        let s = agent.stats().unwrap();
        assert_eq!(s.tasks_total, 2);
        assert!(s.categories.contains_key("coding"));
        assert!(s.categories.contains_key("research"));
    }

    #[test]
    fn agent_suggest_uses_stored_data() {
        let store = InMemPiStore::new();
        let clk = FixedClock(tuesday_noon());
        let agent = PiAgent::new(&store, &clk);
        for _ in 0..6 {
            agent.learn("напиши код", 35.0).unwrap();
        }
        let s = agent.suggest().unwrap();
        let kinds: Vec<&str> = s.iter().map(|x| x.kind.as_str()).collect();
        assert!(kinds.contains(&"slow-tasks"));
        assert!(kinds.contains(&"frequent-category"));
    }
}
