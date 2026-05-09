//! aim-job-queue — in-process async job queue with persistent state.
//!
//! Port of `agents/job_queue.py`. No external broker (Redis/Celery);
//! state lives in a [`JobStore`] (production: rusqlite-backed; tests:
//! in-memory). Job execution is dispatched through an [`Executor`] —
//! production wraps `tokio::spawn_blocking` or a `std::thread` pool;
//! tests use the synchronous [`InlineExecutor`].

use std::sync::Arc;
use std::time::Duration;

use chrono::{DateTime, Utc};
use parking_lot::Mutex;
use serde::{Deserialize, Serialize};
use thiserror::Error;
use uuid::Uuid;

#[derive(Debug, Error)]
pub enum JobError {
    #[error("store error: {0}")]
    Store(String),
}

pub type Result<T> = std::result::Result<T, JobError>;

// ── status ──────────────────────────────────────────────────────────────────

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Status {
    Pending,
    Running,
    Completed,
    Failed,
    Cancelled,
}

impl Status {
    pub fn is_terminal(&self) -> bool {
        matches!(
            self,
            Self::Completed | Self::Failed | Self::Cancelled
        )
    }
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Pending => "pending",
            Self::Running => "running",
            Self::Completed => "completed",
            Self::Failed => "failed",
            Self::Cancelled => "cancelled",
        }
    }
}

// ── data ────────────────────────────────────────────────────────────────────

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct Job {
    pub id: String,
    pub name: String,
    pub status: Option<Status>,
    pub tags: Vec<String>,
    pub created_at: Option<DateTime<Utc>>,
    pub started_at: Option<DateTime<Utc>>,
    pub completed_at: Option<DateTime<Utc>>,
    pub result: Option<String>,
    pub error: Option<String>,
    pub duration_s: Option<f64>,
}

// ── store ───────────────────────────────────────────────────────────────────

#[derive(Clone, Debug, Default)]
pub struct JobUpdate {
    pub status: Option<Status>,
    pub started_at: Option<DateTime<Utc>>,
    pub completed_at: Option<DateTime<Utc>>,
    pub result: Option<String>,
    pub error: Option<String>,
    pub duration_s: Option<f64>,
}

pub trait JobStore: Send + Sync {
    fn insert(&self, job: &Job) -> Result<()>;
    fn update(&self, id: &str, fields: &JobUpdate) -> Result<()>;
    fn get(&self, id: &str) -> Result<Option<Job>>;
    /// Sort newest-first by `created_at`. Optional `status` filter.
    fn list(&self, limit: usize, status: Option<Status>) -> Result<Vec<Job>>;
}

#[derive(Default)]
pub struct InMemStore {
    inner: Mutex<std::collections::BTreeMap<String, Job>>,
}

impl InMemStore {
    pub fn new() -> Self {
        Self::default()
    }
}

impl JobStore for InMemStore {
    fn insert(&self, job: &Job) -> Result<()> {
        self.inner.lock().insert(job.id.clone(), job.clone());
        Ok(())
    }
    fn update(&self, id: &str, fields: &JobUpdate) -> Result<()> {
        let mut m = self.inner.lock();
        if let Some(j) = m.get_mut(id) {
            if let Some(s) = fields.status {
                j.status = Some(s);
            }
            if fields.started_at.is_some() {
                j.started_at = fields.started_at;
            }
            if fields.completed_at.is_some() {
                j.completed_at = fields.completed_at;
            }
            if fields.result.is_some() {
                j.result.clone_from(&fields.result);
            }
            if fields.error.is_some() {
                j.error.clone_from(&fields.error);
            }
            if fields.duration_s.is_some() {
                j.duration_s = fields.duration_s;
            }
        }
        Ok(())
    }
    fn get(&self, id: &str) -> Result<Option<Job>> {
        Ok(self.inner.lock().get(id).cloned())
    }
    fn list(&self, limit: usize, status: Option<Status>) -> Result<Vec<Job>> {
        let mut v: Vec<Job> = self
            .inner
            .lock()
            .values()
            .filter(|j| status.map(|s| j.status == Some(s)).unwrap_or(true))
            .cloned()
            .collect();
        v.sort_by(|a, b| {
            b.created_at
                .unwrap_or(DateTime::<Utc>::MIN_UTC)
                .cmp(&a.created_at.unwrap_or(DateTime::<Utc>::MIN_UTC))
        });
        v.truncate(limit);
        Ok(v)
    }
}

// ── executor ────────────────────────────────────────────────────────────────

pub trait Executor: Send + Sync {
    /// Spawn `task` for execution. Returns when scheduling is done; the
    /// caller polls the store for status updates. Implementations may run
    /// synchronously (test stubs) or on a background pool (production).
    fn spawn(&self, task: Box<dyn FnOnce() + Send + 'static>);
}

/// Runs the task on the calling thread. Used in tests so assertions can
/// inspect the store immediately after `submit()`.
pub struct InlineExecutor;
impl Executor for InlineExecutor {
    fn spawn(&self, task: Box<dyn FnOnce() + Send + 'static>) {
        task();
    }
}

// ── clock ──────────────────────────────────────────────────────────────────

pub trait Clock: Send + Sync {
    fn now(&self) -> DateTime<Utc>;
    fn sleep(&self, duration: Duration);
}

pub struct SystemClock;
impl Clock for SystemClock {
    fn now(&self) -> DateTime<Utc> {
        Utc::now()
    }
    fn sleep(&self, duration: Duration) {
        std::thread::sleep(duration);
    }
}

#[derive(Default)]
pub struct AdvancingClock {
    base: Mutex<DateTime<Utc>>,
}

impl AdvancingClock {
    pub fn new(base: DateTime<Utc>) -> Self {
        Self {
            base: Mutex::new(base),
        }
    }
}

impl Clock for AdvancingClock {
    fn now(&self) -> DateTime<Utc> {
        let mut t = self.base.lock();
        let v = *t;
        *t = v + chrono::Duration::milliseconds(1);
        v
    }
    fn sleep(&self, duration: Duration) {
        let mut t = self.base.lock();
        *t = *t + chrono::Duration::from_std(duration).unwrap_or(chrono::Duration::zero());
    }
}

// ── runner ──────────────────────────────────────────────────────────────────

/// Outcome of a job body. `Ok(json_string)` → COMPLETED;
/// `Err(message)` → FAILED.
pub type JobOutcome = std::result::Result<String, String>;

/// Cancellation handle. The runner consults `cancelled` before flipping
/// status to RUNNING; if set, the job ends as CANCELLED without invoking
/// the closure.
#[derive(Clone, Default)]
pub struct CancelToken(Arc<Mutex<bool>>);

impl CancelToken {
    pub fn new() -> Self {
        Self::default()
    }
    pub fn cancel(&self) {
        *self.0.lock() = true;
    }
    pub fn is_cancelled(&self) -> bool {
        *self.0.lock()
    }
}

/// Truncate `s` to at most `max` chars (Unicode-safe). Mirrors Python
/// `str(...)[:N]`.
pub fn cap_chars(s: &str, max: usize) -> String {
    s.chars().take(max).collect()
}

pub struct JobQueue<'a> {
    pub store: Arc<dyn JobStore>,
    pub executor: &'a dyn Executor,
    pub clock: Arc<dyn Clock>,
    tokens: Mutex<std::collections::BTreeMap<String, CancelToken>>,
}

impl<'a> JobQueue<'a> {
    pub fn new(
        store: Arc<dyn JobStore>,
        executor: &'a dyn Executor,
        clock: Arc<dyn Clock>,
    ) -> Self {
        Self {
            store,
            executor,
            clock,
            tokens: Mutex::new(Default::default()),
        }
    }

    /// Submit a job. The closure returns an outcome that gets persisted.
    pub fn submit<F>(&self, name: &str, tags: Vec<String>, body: F) -> Result<String>
    where
        F: FnOnce() -> JobOutcome + Send + 'static,
    {
        let id: String = Uuid::new_v4().simple().to_string().chars().take(12).collect();
        let job = Job {
            id: id.clone(),
            name: name.into(),
            status: Some(Status::Pending),
            tags,
            created_at: Some(self.clock.now()),
            ..Default::default()
        };
        self.store.insert(&job)?;
        let token = CancelToken::new();
        self.tokens.lock().insert(id.clone(), token.clone());

        let store = self.store.clone();
        let clock = self.clock.clone();
        let id_for_task = id.clone();
        let task: Box<dyn FnOnce() + Send + 'static> = Box::new(move || {
            if token.is_cancelled() {
                let _ = store.update(
                    &id_for_task,
                    &JobUpdate {
                        status: Some(Status::Cancelled),
                        completed_at: Some(clock.now()),
                        ..Default::default()
                    },
                );
                return;
            }
            let started = clock.now();
            let _ = store.update(
                &id_for_task,
                &JobUpdate {
                    status: Some(Status::Running),
                    started_at: Some(started),
                    ..Default::default()
                },
            );
            let outcome = body();
            let finished = clock.now();
            let dur = (finished - started).num_milliseconds() as f64 / 1000.0;
            let update = match outcome {
                Ok(json_string) => JobUpdate {
                    status: Some(Status::Completed),
                    completed_at: Some(finished),
                    result: Some(cap_chars(&json_string, 8000)),
                    duration_s: Some(dur),
                    ..Default::default()
                },
                Err(e) => JobUpdate {
                    status: Some(Status::Failed),
                    completed_at: Some(finished),
                    error: Some(cap_chars(&e, 4000)),
                    duration_s: Some(dur),
                    ..Default::default()
                },
            };
            let _ = store.update(&id_for_task, &update);
        });
        self.executor.spawn(task);
        Ok(id)
    }

    pub fn get(&self, id: &str) -> Result<Option<Job>> {
        self.store.get(id)
    }

    pub fn list(&self, limit: usize, status: Option<Status>) -> Result<Vec<Job>> {
        self.store.list(limit, status)
    }

    /// Best-effort cancel: marks the token. If the executor hasn't picked
    /// up the task yet, it will short-circuit to CANCELLED. If already
    /// running, the body keeps going (no thread-kill), and the call
    /// returns false.
    pub fn cancel(&self, id: &str) -> Result<bool> {
        let token = self.tokens.lock().get(id).cloned();
        let Some(token) = token else {
            return Ok(false);
        };
        if let Some(job) = self.store.get(id)? {
            if matches!(job.status, Some(Status::Pending)) {
                token.cancel();
                self.store.update(
                    id,
                    &JobUpdate {
                        status: Some(Status::Cancelled),
                        completed_at: Some(self.clock.now()),
                        ..Default::default()
                    },
                )?;
                return Ok(true);
            }
        }
        // already running / completed → just flip the token (informational)
        token.cancel();
        Ok(false)
    }

    /// Block until the job reaches a terminal state or `timeout` elapses.
    /// Returns the final job snapshot (or a synthetic `timeout` status).
    pub fn wait(&self, id: &str, timeout: Duration, poll: Duration) -> Result<Job> {
        let deadline = self.clock.now() + chrono::Duration::from_std(timeout).unwrap_or(chrono::Duration::seconds(0));
        loop {
            if let Some(j) = self.store.get(id)? {
                if j.status.map(|s| s.is_terminal()).unwrap_or(false) {
                    return Ok(j);
                }
            }
            if self.clock.now() >= deadline {
                let mut snap = self.store.get(id)?.unwrap_or_else(|| Job {
                    id: id.into(),
                    ..Default::default()
                });
                if !snap.status.map(|s| s.is_terminal()).unwrap_or(false) {
                    snap.status = None; // synthetic "timeout"
                    snap.error = Some("timeout".into());
                }
                return Ok(snap);
            }
            self.clock.sleep(poll);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;

    fn clock() -> Arc<AdvancingClock> {
        Arc::new(AdvancingClock::new(
            Utc.with_ymd_and_hms(2026, 5, 5, 0, 0, 0).unwrap(),
        ))
    }

    // ── status ──────────────────────────────────────────────────────────────

    #[test]
    fn status_terminal_classification() {
        assert!(Status::Completed.is_terminal());
        assert!(Status::Failed.is_terminal());
        assert!(Status::Cancelled.is_terminal());
        assert!(!Status::Pending.is_terminal());
        assert!(!Status::Running.is_terminal());
    }

    // ── cap_chars ──────────────────────────────────────────────────────────

    #[test]
    fn cap_chars_handles_unicode() {
        assert_eq!(cap_chars("Привет", 3), "При");
        let s = "x".repeat(50);
        assert_eq!(cap_chars(&s, 10).chars().count(), 10);
    }

    // ── submit + run (via InlineExecutor) ──────────────────────────────────

    #[test]
    fn submit_runs_inline_and_persists_completed() {
        let store: Arc<dyn JobStore> = Arc::new(InMemStore::new());
        let clk = clock();
        let q = JobQueue::new(store.clone(), &InlineExecutor, clk.clone());
        let id = q
            .submit("reindex", vec!["memory".into()], || Ok("\"done\"".into()))
            .unwrap();
        let job = q.get(&id).unwrap().unwrap();
        assert_eq!(job.status, Some(Status::Completed));
        assert_eq!(job.result.as_deref(), Some("\"done\""));
        assert!(job.duration_s.is_some());
        assert_eq!(job.tags, vec!["memory"]);
        assert_eq!(job.name, "reindex");
    }

    #[test]
    fn submit_failure_marks_failed_with_error() {
        let store: Arc<dyn JobStore> = Arc::new(InMemStore::new());
        let clk = clock();
        let q = JobQueue::new(store.clone(), &InlineExecutor, clk);
        let id = q.submit("calc", vec![], || Err("kaboom".into())).unwrap();
        let job = q.get(&id).unwrap().unwrap();
        assert_eq!(job.status, Some(Status::Failed));
        assert_eq!(job.error.as_deref(), Some("kaboom"));
    }

    #[test]
    fn submit_truncates_long_result_to_8000_chars() {
        let store: Arc<dyn JobStore> = Arc::new(InMemStore::new());
        let clk = clock();
        let q = JobQueue::new(store.clone(), &InlineExecutor, clk);
        let big: String = "x".repeat(20_000);
        let id = q.submit("fat", vec![], move || Ok(big)).unwrap();
        let job = q.get(&id).unwrap().unwrap();
        assert_eq!(job.result.unwrap().chars().count(), 8000);
    }

    #[test]
    fn submit_truncates_long_error_to_4000_chars() {
        let store: Arc<dyn JobStore> = Arc::new(InMemStore::new());
        let clk = clock();
        let q = JobQueue::new(store.clone(), &InlineExecutor, clk);
        let big: String = "e".repeat(20_000);
        let id = q.submit("err", vec![], move || Err(big)).unwrap();
        let job = q.get(&id).unwrap().unwrap();
        assert_eq!(job.error.unwrap().chars().count(), 4000);
    }

    // ── id format ──────────────────────────────────────────────────────────

    #[test]
    fn submitted_id_is_12_chars() {
        let store: Arc<dyn JobStore> = Arc::new(InMemStore::new());
        let clk = clock();
        let q = JobQueue::new(store.clone(), &InlineExecutor, clk);
        let id = q.submit("x", vec![], || Ok("y".into())).unwrap();
        assert_eq!(id.chars().count(), 12);
    }

    // ── cancel ─────────────────────────────────────────────────────────────

    /// Executor that holds tasks until released — lets us test the
    /// "cancel before run" path.
    #[derive(Default)]
    struct DeferredExecutor {
        held: Mutex<Vec<Box<dyn FnOnce() + Send + 'static>>>,
    }
    impl DeferredExecutor {
        fn release_all(&self) {
            let pending = std::mem::take(&mut *self.held.lock());
            for t in pending {
                t();
            }
        }
    }
    impl Executor for DeferredExecutor {
        fn spawn(&self, task: Box<dyn FnOnce() + Send + 'static>) {
            self.held.lock().push(task);
        }
    }

    #[test]
    fn cancel_before_run_marks_cancelled() {
        let store: Arc<dyn JobStore> = Arc::new(InMemStore::new());
        let clk = clock();
        let exec = DeferredExecutor::default();
        let q = JobQueue::new(store.clone(), &exec, clk);
        let id = q.submit("slow", vec![], || Ok("done".into())).unwrap();
        // Job is pending; cancel
        assert!(q.cancel(&id).unwrap());
        let job = q.get(&id).unwrap().unwrap();
        assert_eq!(job.status, Some(Status::Cancelled));
        // releasing the task should now skip execution
        exec.release_all();
        let job = q.get(&id).unwrap().unwrap();
        assert_eq!(job.status, Some(Status::Cancelled));
    }

    #[test]
    fn cancel_after_completion_returns_false() {
        let store: Arc<dyn JobStore> = Arc::new(InMemStore::new());
        let clk = clock();
        let q = JobQueue::new(store.clone(), &InlineExecutor, clk);
        let id = q.submit("x", vec![], || Ok("y".into())).unwrap();
        assert!(!q.cancel(&id).unwrap());
    }

    #[test]
    fn cancel_unknown_id_returns_false() {
        let store: Arc<dyn JobStore> = Arc::new(InMemStore::new());
        let clk = clock();
        let q = JobQueue::new(store.clone(), &InlineExecutor, clk);
        assert!(!q.cancel("ghost").unwrap());
    }

    // ── list ──────────────────────────────────────────────────────────────

    #[test]
    fn list_returns_newest_first() {
        let store: Arc<dyn JobStore> = Arc::new(InMemStore::new());
        let clk = clock();
        let q = JobQueue::new(store.clone(), &InlineExecutor, clk);
        let a = q.submit("a", vec![], || Ok("1".into())).unwrap();
        let b = q.submit("b", vec![], || Ok("2".into())).unwrap();
        let c = q.submit("c", vec![], || Ok("3".into())).unwrap();
        let v = q.list(10, None).unwrap();
        assert_eq!(v[0].id, c);
        assert_eq!(v[1].id, b);
        assert_eq!(v[2].id, a);
    }

    #[test]
    fn list_filters_by_status() {
        let store: Arc<dyn JobStore> = Arc::new(InMemStore::new());
        let clk = clock();
        let q = JobQueue::new(store.clone(), &InlineExecutor, clk);
        q.submit("ok1", vec![], || Ok("a".into())).unwrap();
        q.submit("err", vec![], || Err("bad".into())).unwrap();
        q.submit("ok2", vec![], || Ok("b".into())).unwrap();
        let failed = q.list(10, Some(Status::Failed)).unwrap();
        assert_eq!(failed.len(), 1);
        assert_eq!(failed[0].name, "err");
    }

    // ── wait ──────────────────────────────────────────────────────────────

    #[test]
    fn wait_returns_terminal_immediately() {
        let store: Arc<dyn JobStore> = Arc::new(InMemStore::new());
        let clk = clock();
        let q = JobQueue::new(store.clone(), &InlineExecutor, clk);
        let id = q.submit("x", vec![], || Ok("done".into())).unwrap();
        // already completed → wait returns at first poll
        let job = q.wait(&id, Duration::from_secs(60), Duration::from_millis(10)).unwrap();
        assert_eq!(job.status, Some(Status::Completed));
    }

    #[test]
    fn wait_times_out_when_never_terminal() {
        let store: Arc<dyn JobStore> = Arc::new(InMemStore::new());
        // Manually insert a stuck-in-pending row
        store
            .insert(&Job {
                id: "stuck".into(),
                name: "x".into(),
                status: Some(Status::Pending),
                created_at: Some(Utc.with_ymd_and_hms(2026, 5, 5, 0, 0, 0).unwrap()),
                ..Default::default()
            })
            .unwrap();
        let clk: Arc<dyn Clock> = Arc::new(AdvancingClock::new(
            Utc.with_ymd_and_hms(2026, 5, 5, 0, 0, 0).unwrap(),
        ));
        let q = JobQueue::new(store.clone(), &InlineExecutor, clk);
        // very small timeout; AdvancingClock advances on each .now() call
        let job = q.wait("stuck", Duration::from_millis(1), Duration::from_millis(0)).unwrap();
        assert_eq!(job.error.as_deref(), Some("timeout"));
    }
}
