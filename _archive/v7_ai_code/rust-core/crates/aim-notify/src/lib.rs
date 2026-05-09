//! aim-notify — N1 notification multiplexer.
//!
//! Single front door for every alert / brief / digest AIM wants to
//! send. Tries each [`Channel`] in priority order; on failure falls
//! through to the next. JSONL audit at `~/.cache/aim/notify.jsonl`
//! records every attempt, regardless of outcome.
//!
//! Dedup: if `dedup_key` is provided, suppresses repeat sends within
//! `dedup_window_minutes` (default 60).
//!
//! Rust port of `agents/notify.py`. Channel implementations are caller
//! plug-ins — production binaries register Telegram, Gmail, stdout,
//! log; tests register stubs.

use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::Mutex;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum NotifyError {
    #[error("io: {0}")]
    Io(#[from] std::io::Error),
    #[error("json: {0}")]
    Json(#[from] serde_json::Error),
}

/// Pluggable channel. Returns `Ok(true)` on successful delivery,
/// `Ok(false)` if the channel decided not to attempt (e.g. missing
/// config), `Err` on a real failure.
pub trait Channel: Send + Sync {
    fn name(&self) -> &str;
    fn send(&self, text: &str, subject: Option<&str>) -> Result<bool, String>;
}

/// Stdout channel — never fails.
pub struct StdoutChannel;
impl Channel for StdoutChannel {
    fn name(&self) -> &str {
        "stdout"
    }
    fn send(&self, text: &str, subject: Option<&str>) -> Result<bool, String> {
        if let Some(s) = subject {
            println!("[{s}] {text}");
        } else {
            println!("{text}");
        }
        Ok(true)
    }
}

/// Tracing log channel — emits at info level.
pub struct LogChannel;
impl Channel for LogChannel {
    fn name(&self) -> &str {
        "log"
    }
    fn send(&self, text: &str, subject: Option<&str>) -> Result<bool, String> {
        match subject {
            Some(s) => tracing::info!(subject = s, "{text}"),
            None => tracing::info!("{text}"),
        }
        Ok(true)
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NotifyResult {
    pub delivered_via: Option<String>,
    pub attempted: Vec<String>,
    pub failures: HashMap<String, String>,
    pub suppressed: bool,
    pub dedup_key: Option<String>,
}

#[derive(Debug, Clone)]
pub struct NotifyOpts<'a> {
    pub channels: &'a [&'a str],
    pub subject: Option<&'a str>,
    pub level: &'a str,
    pub source: &'a str,
    pub dedup_key: Option<&'a str>,
    pub dedup_window_minutes: f64,
}

impl<'a> Default for NotifyOpts<'a> {
    fn default() -> Self {
        Self {
            channels: &["telegram", "email", "stdout"],
            subject: None,
            level: "info",
            source: "generic",
            dedup_key: None,
            dedup_window_minutes: 60.0,
        }
    }
}

pub struct Mux {
    channels: HashMap<String, Box<dyn Channel>>,
    audit_path: PathBuf,
    /// `dedup_key → last_send_iso` (in-process; for cross-process,
    /// implement a SQLite or file-backed dedup later).
    dedup: Mutex<HashMap<String, String>>,
}

impl Mux {
    pub fn new(audit_path: impl Into<PathBuf>) -> Self {
        Self {
            channels: HashMap::new(),
            audit_path: audit_path.into(),
            dedup: Mutex::new(HashMap::new()),
        }
    }

    pub fn default_audit_path() -> PathBuf {
        if let Ok(p) = std::env::var("AIM_NOTIFY_LOG") {
            return PathBuf::from(p);
        }
        if let Ok(xdg) = std::env::var("XDG_CACHE_HOME") {
            return PathBuf::from(xdg).join("aim").join("notify.jsonl");
        }
        let home = std::env::var("HOME").unwrap_or_else(|_| ".".to_string());
        PathBuf::from(home).join(".cache").join("aim").join("notify.jsonl")
    }

    pub fn register(&mut self, channel: Box<dyn Channel>) {
        self.channels.insert(channel.name().to_string(), channel);
    }

    /// Try each named channel in order; return the result envelope.
    pub fn notify(&self, text: &str, opts: &NotifyOpts<'_>) -> Result<NotifyResult, NotifyError> {
        let now = chrono::Utc::now();

        // Dedup
        let suppressed = if let Some(key) = opts.dedup_key {
            let dedup = self.dedup.lock().unwrap();
            if let Some(last) = dedup.get(key) {
                if let Ok(prev) = chrono::DateTime::parse_from_rfc3339(last) {
                    let elapsed = (now - prev.with_timezone(&chrono::Utc)).num_seconds() as f64
                        / 60.0;
                    elapsed < opts.dedup_window_minutes
                } else {
                    false
                }
            } else {
                false
            }
        } else {
            false
        };

        if suppressed {
            let res = NotifyResult {
                delivered_via: None,
                attempted: vec![],
                failures: HashMap::new(),
                suppressed: true,
                dedup_key: opts.dedup_key.map(String::from),
            };
            self.write_audit(&now, &res, text, opts)?;
            return Ok(res);
        }

        let mut attempted: Vec<String> = Vec::new();
        let mut failures: HashMap<String, String> = HashMap::new();
        let mut delivered: Option<String> = None;
        for cname in opts.channels {
            let Some(ch) = self.channels.get(*cname) else {
                continue;
            };
            attempted.push((*cname).to_string());
            match ch.send(text, opts.subject) {
                Ok(true) => {
                    delivered = Some((*cname).to_string());
                    break;
                }
                Ok(false) => {
                    failures.insert((*cname).to_string(), "channel skipped".into());
                }
                Err(e) => {
                    failures.insert((*cname).to_string(), e);
                }
            }
        }

        if delivered.is_some() {
            if let Some(key) = opts.dedup_key {
                self.dedup
                    .lock()
                    .unwrap()
                    .insert(key.to_string(), now.to_rfc3339());
            }
        }

        let res = NotifyResult {
            delivered_via: delivered,
            attempted,
            failures,
            suppressed: false,
            dedup_key: opts.dedup_key.map(String::from),
        };
        self.write_audit(&now, &res, text, opts)?;
        Ok(res)
    }

    fn write_audit(
        &self,
        ts: &chrono::DateTime<chrono::Utc>,
        res: &NotifyResult,
        text: &str,
        opts: &NotifyOpts<'_>,
    ) -> Result<(), NotifyError> {
        if let Some(parent) = self.audit_path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        use std::io::Write;
        let preview: String = text.chars().take(200).collect();
        let row = serde_json::json!({
            "ts": ts.to_rfc3339(),
            "level": opts.level,
            "source": opts.source,
            "subject": opts.subject,
            "preview": preview,
            "delivered_via": res.delivered_via,
            "attempted": res.attempted,
            "failures": res.failures,
            "suppressed": res.suppressed,
            "dedup_key": res.dedup_key,
        });
        let mut f = std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&self.audit_path)?;
        writeln!(f, "{}", serde_json::to_string(&row)?)?;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    struct Always {
        name: String,
        ok: bool,
    }
    impl Channel for Always {
        fn name(&self) -> &str {
            &self.name
        }
        fn send(&self, _t: &str, _s: Option<&str>) -> Result<bool, String> {
            if self.ok {
                Ok(true)
            } else {
                Err("nope".into())
            }
        }
    }

    fn ch(name: &str, ok: bool) -> Box<dyn Channel> {
        Box::new(Always {
            name: name.to_string(),
            ok,
        })
    }

    #[test]
    fn primary_succeeds_no_fallback() {
        let d = tempdir().unwrap();
        let mut m = Mux::new(d.path().join("audit.jsonl"));
        m.register(ch("primary", true));
        m.register(ch("backup", true));
        let opts = NotifyOpts {
            channels: &["primary", "backup"],
            ..Default::default()
        };
        let res = m.notify("hi", &opts).unwrap();
        assert_eq!(res.delivered_via.as_deref(), Some("primary"));
        assert_eq!(res.attempted, vec!["primary".to_string()]);
    }

    #[test]
    fn falls_through_to_backup() {
        let d = tempdir().unwrap();
        let mut m = Mux::new(d.path().join("audit.jsonl"));
        m.register(ch("primary", false));
        m.register(ch("backup", true));
        let opts = NotifyOpts {
            channels: &["primary", "backup"],
            ..Default::default()
        };
        let res = m.notify("hi", &opts).unwrap();
        assert_eq!(res.delivered_via.as_deref(), Some("backup"));
        assert_eq!(res.attempted, vec!["primary".to_string(), "backup".to_string()]);
        assert!(res.failures.contains_key("primary"));
    }

    #[test]
    fn unknown_channel_silently_skipped() {
        let d = tempdir().unwrap();
        let mut m = Mux::new(d.path().join("audit.jsonl"));
        m.register(ch("real", true));
        let opts = NotifyOpts {
            channels: &["fake", "real"],
            ..Default::default()
        };
        let res = m.notify("hi", &opts).unwrap();
        assert_eq!(res.delivered_via.as_deref(), Some("real"));
        assert!(!res.attempted.contains(&"fake".to_string()));
    }

    #[test]
    fn no_channel_succeeds_returns_none() {
        let d = tempdir().unwrap();
        let mut m = Mux::new(d.path().join("audit.jsonl"));
        m.register(ch("a", false));
        m.register(ch("b", false));
        let opts = NotifyOpts {
            channels: &["a", "b"],
            ..Default::default()
        };
        let res = m.notify("hi", &opts).unwrap();
        assert!(res.delivered_via.is_none());
        assert_eq!(res.failures.len(), 2);
    }

    #[test]
    fn dedup_within_window_suppresses() {
        let d = tempdir().unwrap();
        let mut m = Mux::new(d.path().join("audit.jsonl"));
        m.register(ch("c", true));
        let opts = NotifyOpts {
            channels: &["c"],
            dedup_key: Some("alert-1"),
            dedup_window_minutes: 60.0,
            ..Default::default()
        };
        let r1 = m.notify("hi", &opts).unwrap();
        assert!(!r1.suppressed);
        let r2 = m.notify("hi", &opts).unwrap();
        assert!(r2.suppressed);
        assert!(r2.delivered_via.is_none());
    }

    #[test]
    fn dedup_does_not_suppress_after_window() {
        let d = tempdir().unwrap();
        let mut m = Mux::new(d.path().join("audit.jsonl"));
        m.register(ch("c", true));
        // Pre-seed dedup with an old timestamp
        m.dedup.lock().unwrap().insert(
            "alert-2".into(),
            (chrono::Utc::now() - chrono::Duration::hours(2)).to_rfc3339(),
        );
        let opts = NotifyOpts {
            channels: &["c"],
            dedup_key: Some("alert-2"),
            dedup_window_minutes: 60.0,
            ..Default::default()
        };
        let r = m.notify("hi", &opts).unwrap();
        assert!(!r.suppressed);
        assert_eq!(r.delivered_via.as_deref(), Some("c"));
    }

    #[test]
    fn audit_jsonl_written() {
        let d = tempdir().unwrap();
        let audit = d.path().join("audit.jsonl");
        let mut m = Mux::new(audit.clone());
        m.register(ch("c", true));
        let opts = NotifyOpts {
            channels: &["c"],
            ..Default::default()
        };
        m.notify("hello world", &opts).unwrap();
        let text = std::fs::read_to_string(&audit).unwrap();
        assert!(text.contains("hello world"));
        assert!(text.contains("delivered_via"));
    }

    #[test]
    fn stdout_channel_always_succeeds() {
        let d = tempdir().unwrap();
        let mut m = Mux::new(d.path().join("audit.jsonl"));
        m.register(Box::new(StdoutChannel));
        let opts = NotifyOpts {
            channels: &["stdout"],
            ..Default::default()
        };
        let r = m.notify("test", &opts).unwrap();
        assert_eq!(r.delivered_via.as_deref(), Some("stdout"));
    }
}
