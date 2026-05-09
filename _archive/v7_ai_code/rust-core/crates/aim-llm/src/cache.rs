//! Prompt cache. Stores (sha256 of [model + messages]) → response in
//! a SQLite file shared with aim_memory.LlmCache. Disabled when
//! `AIM_LLM_NO_CACHE=1` or the DB is unreachable.

use parking_lot::Mutex;
use rusqlite::{params, Connection};
use sha2::{Digest, Sha256};
use std::sync::Arc;

#[derive(Clone)]
pub struct PromptCache {
    conn: Option<Arc<Mutex<Connection>>>,
}

impl PromptCache {
    pub fn from_env() -> Self {
        if std::env::var("AIM_LLM_NO_CACHE").as_deref() == Ok("1") {
            return Self { conn: None };
        }
        let path = std::env::var("AIM_DB_PATH").unwrap_or_else(|_| {
            let home = std::env::var("HOME").unwrap_or_else(|_| "/home/oem".into());
            format!("{home}/Desktop/LongevityCommon/AIM/aim.db")
        });
        match Connection::open(&path) {
            Ok(conn) => {
                // Table is created by aim_memory migration. We only insert/select.
                let exists = conn.query_row(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='llm_cache'",
                    [], |_| Ok(true)).unwrap_or(false);
                if !exists {
                    tracing::warn!(path = %path, "llm_cache table missing; cache disabled");
                    return Self { conn: None };
                }
                tracing::info!(path = %path, "llm prompt cache enabled");
                Self { conn: Some(Arc::new(Mutex::new(conn))) }
            }
            Err(e) => {
                tracing::warn!(path = %path, error = %e, "could not open aim.db; cache disabled");
                Self { conn: None }
            }
        }
    }

    pub fn enabled(&self) -> bool { self.conn.is_some() }

    /// Stable hash of (model + messages serialised as JSON).
    pub fn key(model: &str, messages_json: &str) -> String {
        let mut h = Sha256::new();
        h.update(b"v1\0");
        h.update(model.as_bytes());
        h.update(b"\0");
        h.update(messages_json.as_bytes());
        format!("{:x}", h.finalize())
    }

    pub fn get(&self, key: &str) -> Option<String> {
        let conn = self.conn.as_ref()?.lock();
        conn.query_row(
            "SELECT response FROM llm_cache WHERE hash = ?1",
            params![key],
            |r| r.get::<_, String>(0)
        ).ok()
    }

    pub fn put(&self, key: &str, prompt_hash: &str, response: &str, model: &str) {
        let Some(conn) = &self.conn else { return; };
        let _ = conn.lock().execute(
            "INSERT OR IGNORE INTO llm_cache (hash, prompt_hash, response, model, created_at)
             VALUES (?1, ?2, ?3, ?4, ?5)",
            params![key, prompt_hash, response, model, chrono::Utc::now().to_rfc3339()],
        );
    }
}
