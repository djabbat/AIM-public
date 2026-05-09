//! aim-session-manager — session persistence + resume + auto STATE.md update.
//!
//! Port of `agents/session_manager.py`. The Python original delegates DB
//! ops to `db.py` (sqlite). Here the backend sits behind [`SessionStore`]
//! so the resume + STATE-update logic is testable without sqlite.

use std::path::{Path, PathBuf};

use chrono::{DateTime, Local};
use regex::Regex;
use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum SessionError {
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
    #[error("store error: {0}")]
    Store(String),
}

pub type Result<T> = std::result::Result<T, SessionError>;

// ── data ────────────────────────────────────────────────────────────────────

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct SessionRow {
    pub id: i64,
    pub started_at: String,
    pub ended_at: Option<String>,
    pub lang: String,
    pub summary: Option<String>,
    pub patient: Option<String>,
    pub n_msg: usize,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct Message {
    pub role: String,
    pub content: String,
    pub model: Option<String>,
    pub provider: Option<String>,
}

// ── pluggable store + clock ─────────────────────────────────────────────────

pub trait SessionStore: Send + Sync {
    fn list_recent(&self, n: usize) -> Result<Vec<SessionRow>>;
    fn get_history(&self, session_id: i64, limit: usize) -> Result<Vec<Message>>;
    fn new_session(&self, patient_id: Option<i64>, lang: &str) -> Result<i64>;
    fn save_message(&self, session_id: i64, msg: Message) -> Result<()>;
    fn close_session(&self, session_id: i64, summary: &str) -> Result<()>;
}

pub trait Clock: Send + Sync {
    fn now(&self) -> DateTime<Local>;
}

pub struct SystemClock;
impl Clock for SystemClock {
    fn now(&self) -> DateTime<Local> {
        Local::now()
    }
}

pub struct FixedClock(pub DateTime<Local>);
impl Clock for FixedClock {
    fn now(&self) -> DateTime<Local> {
        self.0
    }
}

// ── project detection ──────────────────────────────────────────────────────

pub const PROJECT_NAMES: &[&str] = &[
    "LongevityCommon", "FCLC", "MCOA", "Ze",
    "BioSense", "CDATA", "AIM", "Annals",
    "PhD", "Books", "GLA",
];

/// Return canonical project names mentioned in `text` (case-insensitive
/// substring match against [`PROJECT_NAMES`]).
pub fn detect_projects(text: &str) -> Vec<&'static str> {
    let lower = text.to_lowercase();
    PROJECT_NAMES
        .iter()
        .copied()
        .filter(|p| lower.contains(&p.to_lowercase()))
        .collect()
}

// ── STATE.md auto-update ───────────────────────────────────────────────────

pub const STATE_MARKER: &str = "## Recent updates";

/// Append a one-liner to `<desktop>/<project>/STATE.md` under
/// "## Recent updates". Returns the path written, or `None` if the file
/// doesn't exist (matches Python "best-effort" behaviour).
pub fn append_to_state(
    desktop_root: &Path,
    project: &str,
    line: &str,
    clock: &dyn Clock,
) -> Result<Option<PathBuf>> {
    let state = desktop_root.join(project).join("STATE.md");
    if !state.exists() {
        return Ok(None);
    }
    let content = std::fs::read_to_string(&state)?;
    let truncated: String = line.chars().take(200).collect();
    let entry = format!("- {}: {}", clock.now().format("%Y-%m-%d"), truncated);
    let new_content = if content.contains(STATE_MARKER) {
        let re = Regex::new(&format!(
            r"({}\s*\n)",
            regex::escape(STATE_MARKER)
        ))
        .expect("regex compiles");
        re.replace(&content, |caps: &regex::Captures| {
            format!("{}{}\n", &caps[1], entry)
        })
        .into_owned()
    } else {
        format!("{}\n\n{}\n{}\n", content.trim_end(), STATE_MARKER, entry)
    };
    std::fs::write(&state, new_content)?;
    Ok(Some(state))
}

// ── manager ────────────────────────────────────────────────────────────────

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct FinalizeReport {
    pub session_id: i64,
    pub summary: String,
    pub state_updates: Vec<PathBuf>,
}

pub struct SessionManager<'a> {
    pub store: &'a dyn SessionStore,
    pub clock: &'a dyn Clock,
    pub desktop: PathBuf,
}

impl<'a> SessionManager<'a> {
    pub fn new(store: &'a dyn SessionStore, clock: &'a dyn Clock, desktop: PathBuf) -> Self {
        Self {
            store,
            clock,
            desktop,
        }
    }

    /// Programmatic resume picker. Returns `(session_id, history)`.
    /// `pick=None` means "start a new session"; `pick=Some(i)` is 1-based.
    pub fn pick_or_new(
        &self,
        n_recent: usize,
        pick: Option<usize>,
        new_lang: &str,
    ) -> Result<(i64, Vec<Message>)> {
        let rows = self.store.list_recent(n_recent)?;
        if rows.is_empty() {
            let sid = self.store.new_session(None, new_lang)?;
            return Ok((sid, Vec::new()));
        }
        match pick {
            None | Some(0) => {
                let sid = self.store.new_session(None, new_lang)?;
                Ok((sid, Vec::new()))
            }
            Some(i) if i >= 1 && i <= rows.len() => {
                let sid = rows[i - 1].id;
                let history = self.store.get_history(sid, 50)?;
                Ok((sid, history))
            }
            Some(_) => {
                let sid = self.store.new_session(None, new_lang)?;
                Ok((sid, Vec::new()))
            }
        }
    }

    pub fn on_turn_end(&self, session_id: i64, msg: Message) -> Result<()> {
        self.store.save_message(session_id, msg)
    }

    /// Close the session and propagate a one-line summary to relevant
    /// project STATE.md files.
    pub fn finalize(&self, session_id: i64, summary: &str) -> Result<FinalizeReport> {
        self.store.close_session(session_id, summary)?;
        let mut updated: Vec<PathBuf> = Vec::new();
        if !summary.is_empty() {
            for project in detect_projects(summary) {
                if let Some(path) = append_to_state(&self.desktop, project, summary, self.clock)? {
                    updated.push(path);
                }
            }
        }
        Ok(FinalizeReport {
            session_id,
            summary: summary.into(),
            state_updates: updated,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;
    use parking_lot::Mutex;
    use tempfile::TempDir;

    // ── stubs ───────────────────────────────────────────────────────────────

    #[derive(Default)]
    struct InMemStore {
        recent: Mutex<Vec<SessionRow>>,
        histories: Mutex<std::collections::HashMap<i64, Vec<Message>>>,
        sessions: Mutex<i64>,
        saved_msgs: Mutex<Vec<(i64, Message)>>,
        closed: Mutex<Vec<(i64, String)>>,
    }
    impl SessionStore for InMemStore {
        fn list_recent(&self, n: usize) -> Result<Vec<SessionRow>> {
            let r = self.recent.lock();
            Ok(r.iter().take(n).cloned().collect())
        }
        fn get_history(&self, sid: i64, _limit: usize) -> Result<Vec<Message>> {
            Ok(self
                .histories
                .lock()
                .get(&sid)
                .cloned()
                .unwrap_or_default())
        }
        fn new_session(&self, _: Option<i64>, _: &str) -> Result<i64> {
            let mut s = self.sessions.lock();
            *s += 1;
            Ok(*s)
        }
        fn save_message(&self, sid: i64, msg: Message) -> Result<()> {
            self.saved_msgs.lock().push((sid, msg));
            Ok(())
        }
        fn close_session(&self, sid: i64, summary: &str) -> Result<()> {
            self.closed.lock().push((sid, summary.to_string()));
            Ok(())
        }
    }

    fn fixed_clock() -> FixedClock {
        let dt = Local
            .with_ymd_and_hms(2026, 5, 5, 1, 0, 0)
            .single()
            .unwrap();
        FixedClock(dt)
    }

    // ── detect_projects ─────────────────────────────────────────────────────

    #[test]
    fn detect_projects_finds_known_names() {
        let v = detect_projects("обновил CDATA и AIM сегодня");
        assert!(v.contains(&"CDATA"));
        assert!(v.contains(&"AIM"));
    }

    #[test]
    fn detect_projects_case_insensitive() {
        let v = detect_projects("работал над FClC и mcoa");
        assert!(v.contains(&"FCLC"));
        assert!(v.contains(&"MCOA"));
    }

    #[test]
    fn detect_projects_empty_no_match() {
        assert!(detect_projects("ничего общего").is_empty());
    }

    // ── append_to_state ─────────────────────────────────────────────────────

    #[test]
    fn append_state_inserts_under_marker() {
        let tmp = TempDir::new().unwrap();
        let proj = tmp.path().join("AIM");
        std::fs::create_dir_all(&proj).unwrap();
        std::fs::write(
            proj.join("STATE.md"),
            "# AIM\n\n## Recent updates\n- 2026-05-04: previous\n",
        )
        .unwrap();
        let p = append_to_state(tmp.path(), "AIM", "added Rust crate", &fixed_clock())
            .unwrap()
            .unwrap();
        let text = std::fs::read_to_string(&p).unwrap();
        assert!(text.contains("2026-05-05: added Rust crate"));
        assert!(text.contains("2026-05-04: previous"));
        // new entry should come before old (right after marker)
        let new_pos = text.find("added Rust crate").unwrap();
        let old_pos = text.find("previous").unwrap();
        assert!(new_pos < old_pos);
    }

    #[test]
    fn append_state_creates_marker_when_missing() {
        let tmp = TempDir::new().unwrap();
        let proj = tmp.path().join("AIM");
        std::fs::create_dir_all(&proj).unwrap();
        std::fs::write(proj.join("STATE.md"), "# AIM\n\n## Other section\nbody\n").unwrap();
        let p = append_to_state(tmp.path(), "AIM", "first update", &fixed_clock())
            .unwrap()
            .unwrap();
        let text = std::fs::read_to_string(&p).unwrap();
        assert!(text.contains("## Recent updates"));
        assert!(text.contains("first update"));
    }

    #[test]
    fn append_state_returns_none_when_file_missing() {
        let tmp = TempDir::new().unwrap();
        let r = append_to_state(tmp.path(), "AIM", "x", &fixed_clock()).unwrap();
        assert!(r.is_none());
    }

    #[test]
    fn append_state_truncates_long_summary() {
        let tmp = TempDir::new().unwrap();
        let proj = tmp.path().join("AIM");
        std::fs::create_dir_all(&proj).unwrap();
        std::fs::write(proj.join("STATE.md"), "## Recent updates\n").unwrap();
        let long = "x".repeat(500);
        let p = append_to_state(tmp.path(), "AIM", &long, &fixed_clock())
            .unwrap()
            .unwrap();
        let text = std::fs::read_to_string(&p).unwrap();
        // entry line should have ≤ ~210 chars (200 truncation + date prefix)
        let entry_line = text.lines().find(|l| l.starts_with("- 2026")).unwrap();
        assert!(entry_line.len() <= 220);
    }

    // ── pick_or_new ─────────────────────────────────────────────────────────

    #[test]
    fn pick_returns_new_when_no_recent() {
        let store = InMemStore::default();
        let clock = fixed_clock();
        let m = SessionManager::new(&store, &clock, PathBuf::from("/tmp"));
        let (sid, h) = m.pick_or_new(5, Some(1), "ru").unwrap();
        assert_eq!(sid, 1);
        assert!(h.is_empty());
    }

    #[test]
    fn pick_zero_starts_new_session() {
        let store = InMemStore::default();
        store.recent.lock().push(SessionRow {
            id: 42,
            started_at: "2026-05-05T00:00:00".into(),
            ..Default::default()
        });
        let clock = fixed_clock();
        let m = SessionManager::new(&store, &clock, PathBuf::from("/tmp"));
        let (sid, _) = m.pick_or_new(5, Some(0), "ru").unwrap();
        // new session created, not 42
        assert_ne!(sid, 42);
    }

    #[test]
    fn pick_index_returns_existing_history() {
        let store = InMemStore::default();
        store.recent.lock().push(SessionRow {
            id: 7,
            ..Default::default()
        });
        store.histories.lock().insert(
            7,
            vec![Message {
                role: "user".into(),
                content: "hi".into(),
                ..Default::default()
            }],
        );
        let clock = fixed_clock();
        let m = SessionManager::new(&store, &clock, PathBuf::from("/tmp"));
        let (sid, h) = m.pick_or_new(5, Some(1), "ru").unwrap();
        assert_eq!(sid, 7);
        assert_eq!(h.len(), 1);
    }

    #[test]
    fn pick_out_of_range_starts_new() {
        let store = InMemStore::default();
        store.recent.lock().push(SessionRow {
            id: 7,
            ..Default::default()
        });
        let clock = fixed_clock();
        let m = SessionManager::new(&store, &clock, PathBuf::from("/tmp"));
        let (sid, _) = m.pick_or_new(5, Some(99), "ru").unwrap();
        assert_ne!(sid, 7);
    }

    // ── finalize ────────────────────────────────────────────────────────────

    #[test]
    fn finalize_closes_and_updates_state() {
        let tmp = TempDir::new().unwrap();
        for proj in ["AIM", "CDATA"] {
            let p = tmp.path().join(proj);
            std::fs::create_dir_all(&p).unwrap();
            std::fs::write(p.join("STATE.md"), "## Recent updates\n").unwrap();
        }
        let store = InMemStore::default();
        let clock = fixed_clock();
        let m = SessionManager::new(&store, &clock, tmp.path().to_path_buf());
        let r = m
            .finalize(42, "обновил AIM и CDATA с новыми тестами")
            .unwrap();
        assert_eq!(r.session_id, 42);
        assert_eq!(r.state_updates.len(), 2);
        assert_eq!(store.closed.lock()[0].0, 42);
    }

    #[test]
    fn finalize_skips_state_when_summary_empty() {
        let tmp = TempDir::new().unwrap();
        let store = InMemStore::default();
        let clock = fixed_clock();
        let m = SessionManager::new(&store, &clock, tmp.path().to_path_buf());
        let r = m.finalize(1, "").unwrap();
        assert!(r.state_updates.is_empty());
    }

    // ── on_turn_end ────────────────────────────────────────────────────────

    #[test]
    fn on_turn_end_persists_via_store() {
        let store = InMemStore::default();
        let clock = fixed_clock();
        let m = SessionManager::new(&store, &clock, PathBuf::from("/tmp"));
        let msg = Message {
            role: "user".into(),
            content: "hello".into(),
            ..Default::default()
        };
        m.on_turn_end(5, msg.clone()).unwrap();
        assert_eq!(store.saved_msgs.lock().len(), 1);
        assert_eq!(store.saved_msgs.lock()[0].0, 5);
        assert_eq!(store.saved_msgs.lock()[0].1, msg);
    }
}
