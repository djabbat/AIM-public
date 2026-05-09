//! aim-hub-auth — Hub-side authentication core for AIM multi-user.
//!
//! ## Architecture
//!
//! AIM Hub (one instance) — manages users, issues tokens, audit log.
//! AIM Node (per-user, local) — validates tokens via aim-hub-client, runs LLM
//! with the user's own DeepSeek/Groq keys.
//!
//! **INVARIANT: the Hub MUST NEVER store, accept, or proxy LLM provider keys.**
//! [`Hub::init`] runs [`assert_no_llm_key_columns`] which fails loudly if a
//! future migration accidentally adds one.
//!
//! ## Public API (mirrors Python `agents/auth.py`)
//!
//! - [`Hub::create_user`] / [`Hub::set_password`] / [`Hub::disable_user`] / [`Hub::enable_user`]
//! - [`Hub::verify_password`]
//! - [`Hub::get_user`] / [`Hub::get_user_by_username`] / [`Hub::get_user_by_token`] / [`Hub::get_user_by_telegram`]
//! - [`Hub::list_users`]
//! - [`Hub::issue_jwt`] / [`Hub::verify_jwt`] / [`Hub::revoke_jwt`]
//! - [`Hub::issue_api_token`] / [`Hub::revoke_api_token`]
//! - [`Hub::create_link_code`] / [`Hub::consume_link_code`]
//! - [`Hub::audit`] / [`Hub::list_audit`]
//! - [`Hub::record_node_heartbeat`] / [`Hub::list_nodes`]

use argon2::password_hash::{rand_core::OsRng, PasswordHash, PasswordHasher, PasswordVerifier, SaltString};
use argon2::Argon2;
use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use base64::Engine;
use chrono::{DateTime, Utc};
use hmac::{Hmac, Mac};
use parking_lot::Mutex;
use rand::RngCore;
use rusqlite::{params, Connection, OptionalExtension, Row};
use serde::{Deserialize, Serialize};
use sha2::Sha256;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use thiserror::Error;

type HmacSha256 = Hmac<Sha256>;

#[derive(Debug, Error)]
pub enum AuthError {
    #[error("invalid role (must be 'admin' or 'user')")]
    InvalidRole,
    #[error("password must be at least 8 characters")]
    PasswordTooShort,
    #[error("username '{0}' already exists")]
    DuplicateUsername(String),
    #[error("user not found: {0}")]
    UserNotFound(i64),
    #[error("password mismatch")]
    PasswordMismatch,
    #[error("hub schema contains banned column {0}.{1}; the Hub MUST NOT store LLM provider keys")]
    BannedKeyColumn(String, String),
    #[error("argon2: {0}")]
    Argon2(String),
    #[error("sqlite: {0}")]
    Sql(#[from] rusqlite::Error),
    #[error("io: {0}")]
    Io(#[from] std::io::Error),
    #[error("json: {0}")]
    Json(#[from] serde_json::Error),
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct User {
    pub id: i64,
    pub username: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub email: Option<String>,
    pub role: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub api_token: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub telegram_id: Option<i64>,
    #[serde(default)]
    pub disabled: bool,
    pub created_at: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub last_login_at: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AuditEntry {
    pub id: i64,
    pub ts: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub user_id: Option<i64>,
    pub action: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub target: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub ip: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub ua: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NodeEntry {
    pub user_id: i64,
    pub node_id: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub username: Option<String>,
    pub host: String,
    pub version: String,
    pub last_seen: String,
}

const SCHEMA: &str = r#"
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT UNIQUE NOT NULL,
    email         TEXT,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'user',
    api_token     TEXT UNIQUE,
    telegram_id   INTEGER UNIQUE,
    disabled      INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL,
    last_login_at TEXT
);

CREATE TABLE IF NOT EXISTS jwt_revocations (
    jti          TEXT PRIMARY KEY,
    user_id      INTEGER NOT NULL,
    revoked_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS link_codes (
    code         TEXT PRIMARY KEY,
    user_id      INTEGER NOT NULL REFERENCES users(id),
    expires_at   TEXT NOT NULL,
    used         INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS audit_log (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT NOT NULL,
    user_id   INTEGER,
    action    TEXT NOT NULL,
    target    TEXT,
    ip        TEXT,
    ua        TEXT
);

CREATE TABLE IF NOT EXISTS nodes (
    user_id      INTEGER NOT NULL REFERENCES users(id),
    node_id      TEXT NOT NULL,
    host         TEXT,
    version      TEXT,
    last_seen    TEXT NOT NULL,
    PRIMARY KEY (user_id, node_id)
);

CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log(user_id, ts);
CREATE INDEX IF NOT EXISTS idx_audit_ts   ON audit_log(ts);
CREATE INDEX IF NOT EXISTS idx_nodes_seen ON nodes(last_seen);
"#;

const BANNED_KEY_COLUMNS: &[&str] = &[
    "api_key",
    "deepseek_api_key",
    "deepseek_key",
    "ds_key",
    "groq_api_key",
    "groq_key",
    "anthropic_api_key",
    "anthropic_key",
    "claude_api_key",
    "openai_api_key",
    "openai_key",
    "gemini_api_key",
    "gemini_key",
    "google_api_key",
    "llm_api_key",
    "llm_key",
    "provider_key",
    "provider_api_key",
];

pub fn assert_no_llm_key_columns(con: &Connection) -> Result<(), AuthError> {
    let mut stmt = con.prepare("SELECT name FROM sqlite_master WHERE type='table'")?;
    let tables: Vec<String> = stmt
        .query_map([], |r| r.get::<_, String>(0))?
        .filter_map(|x| x.ok())
        .collect();
    for table in tables {
        let mut tstmt = con.prepare(&format!("PRAGMA table_info({})", table))?;
        let rows = tstmt
            .query_map([], |r| r.get::<_, String>(1))?
            .filter_map(|x| x.ok());
        for col in rows {
            let lc = col.to_lowercase();
            if BANNED_KEY_COLUMNS.contains(&lc.as_str()) {
                return Err(AuthError::BannedKeyColumn(table, lc));
            }
        }
    }
    Ok(())
}

pub struct Hub {
    db_path: PathBuf,
    secret: Vec<u8>,
    conn: Arc<Mutex<Connection>>,
}

impl Hub {
    /// Open or create the hub at `db_path`. The JWT secret is loaded from
    /// `<db_path>.secret` (created and chmod 0600 on first start).
    pub fn open(db_path: impl AsRef<Path>) -> Result<Self, AuthError> {
        let db_path = db_path.as_ref().to_path_buf();
        if let Some(parent) = db_path.parent() {
            if !parent.as_os_str().is_empty() {
                std::fs::create_dir_all(parent)?;
            }
        }
        let secret = load_or_create_secret(&secret_path(&db_path))?;
        let conn = Connection::open(&db_path)?;
        conn.execute_batch("PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON;")?;
        conn.execute_batch(SCHEMA)?;
        assert_no_llm_key_columns(&conn)?;
        Ok(Self {
            db_path,
            secret,
            conn: Arc::new(Mutex::new(conn)),
        })
    }

    pub fn db_path(&self) -> &Path {
        &self.db_path
    }

    fn now(&self) -> String {
        Utc::now().to_rfc3339()
    }

    fn map_user(row: &Row<'_>) -> rusqlite::Result<User> {
        Ok(User {
            id: row.get("id")?,
            username: row.get("username")?,
            email: row.get("email")?,
            role: row.get("role")?,
            api_token: row.get("api_token")?,
            telegram_id: row.get("telegram_id")?,
            disabled: row.get::<_, i64>("disabled")? != 0,
            created_at: row.get("created_at")?,
            last_login_at: row.get("last_login_at")?,
        })
    }

    // ── User CRUD ──────────────────────────────────────────────────────────

    pub fn create_user(
        &self,
        username: &str,
        password: &str,
        role: &str,
        email: Option<&str>,
    ) -> Result<User, AuthError> {
        if role != "admin" && role != "user" {
            return Err(AuthError::InvalidRole);
        }
        if password.len() < 8 {
            return Err(AuthError::PasswordTooShort);
        }
        let pw_hash = hash_password(password)?;
        let now = self.now();
        let con = self.conn.lock();
        let r = con.execute(
            "INSERT INTO users (username, email, password_hash, role, created_at) VALUES (?,?,?,?,?)",
            params![username, email, pw_hash, role, now],
        );
        match r {
            Err(rusqlite::Error::SqliteFailure(e, _))
                if e.code == rusqlite::ErrorCode::ConstraintViolation =>
            {
                Err(AuthError::DuplicateUsername(username.to_string()))
            }
            Err(e) => Err(e.into()),
            Ok(_) => {
                let id = con.last_insert_rowid();
                let mut stmt = con.prepare("SELECT * FROM users WHERE id=?")?;
                let user = stmt.query_row(params![id], Self::map_user)?;
                Ok(user)
            }
        }
    }

    pub fn set_password(&self, user_id: i64, new_password: &str) -> Result<(), AuthError> {
        if new_password.len() < 8 {
            return Err(AuthError::PasswordTooShort);
        }
        let pw_hash = hash_password(new_password)?;
        let con = self.conn.lock();
        let n = con.execute(
            "UPDATE users SET password_hash=? WHERE id=?",
            params![pw_hash, user_id],
        )?;
        if n == 0 {
            return Err(AuthError::UserNotFound(user_id));
        }
        Ok(())
    }

    pub fn disable_user(&self, user_id: i64) -> Result<(), AuthError> {
        let con = self.conn.lock();
        con.execute(
            "UPDATE users SET disabled=1, api_token=NULL WHERE id=?",
            params![user_id],
        )?;
        Ok(())
    }

    pub fn enable_user(&self, user_id: i64) -> Result<(), AuthError> {
        let con = self.conn.lock();
        con.execute("UPDATE users SET disabled=0 WHERE id=?", params![user_id])?;
        Ok(())
    }

    pub fn get_user(&self, user_id: i64) -> Result<Option<User>, AuthError> {
        let con = self.conn.lock();
        let mut stmt = con.prepare("SELECT * FROM users WHERE id=?")?;
        let u = stmt.query_row(params![user_id], Self::map_user).optional()?;
        Ok(u)
    }

    pub fn get_user_by_username(&self, username: &str) -> Result<Option<User>, AuthError> {
        let con = self.conn.lock();
        let mut stmt = con.prepare("SELECT * FROM users WHERE username=?")?;
        let u = stmt
            .query_row(params![username], Self::map_user)
            .optional()?;
        Ok(u)
    }

    pub fn get_user_by_token(&self, api_token: &str) -> Result<Option<User>, AuthError> {
        if api_token.is_empty() {
            return Ok(None);
        }
        let con = self.conn.lock();
        let mut stmt = con.prepare("SELECT * FROM users WHERE api_token=? AND disabled=0")?;
        let u = stmt
            .query_row(params![api_token], Self::map_user)
            .optional()?;
        Ok(u)
    }

    pub fn get_user_by_telegram(&self, telegram_id: i64) -> Result<Option<User>, AuthError> {
        let con = self.conn.lock();
        let mut stmt = con.prepare("SELECT * FROM users WHERE telegram_id=? AND disabled=0")?;
        let u = stmt
            .query_row(params![telegram_id], Self::map_user)
            .optional()?;
        Ok(u)
    }

    pub fn list_users(&self) -> Result<Vec<User>, AuthError> {
        let con = self.conn.lock();
        let mut stmt = con.prepare("SELECT * FROM users ORDER BY id")?;
        let users: Vec<User> = stmt
            .query_map([], Self::map_user)?
            .collect::<rusqlite::Result<Vec<_>>>()?;
        Ok(users)
    }

    pub fn verify_password(&self, username: &str, password: &str) -> Result<Option<User>, AuthError> {
        // Lookup
        let row_opt = {
            let con = self.conn.lock();
            let mut stmt =
                con.prepare("SELECT id, password_hash FROM users WHERE username=? AND disabled=0")?;
            stmt.query_row(params![username], |r| {
                Ok((r.get::<_, i64>(0)?, r.get::<_, String>(1)?))
            })
            .optional()?
        };

        let Some((uid, pw_hash)) = row_opt else {
            // constant-time-ish: hash a dummy to even out timing
            let _ = hash_password(password);
            return Ok(None);
        };

        let parsed =
            PasswordHash::new(&pw_hash).map_err(|e| AuthError::Argon2(e.to_string()))?;
        if Argon2::default()
            .verify_password(password.as_bytes(), &parsed)
            .is_err()
        {
            return Ok(None);
        }

        let now = self.now();
        {
            let con = self.conn.lock();
            con.execute(
                "UPDATE users SET last_login_at=? WHERE id=?",
                params![now, uid],
            )?;
        }
        self.get_user(uid)
    }

    // ── JWT ────────────────────────────────────────────────────────────────

    pub fn issue_jwt(&self, user_id: i64, ttl_days: i64) -> String {
        let now = Utc::now().timestamp();
        let exp = now + ttl_days * 86400;
        let jti = random_hex(8);
        let header = r#"{"alg":"HS256","typ":"JWT"}"#;
        let payload = serde_json::json!({
            "sub": user_id,
            "iat": now,
            "exp": exp,
            "jti": jti,
        })
        .to_string();
        let h = b64url_encode(header.as_bytes());
        let p = b64url_encode(payload.as_bytes());
        let mut mac = HmacSha256::new_from_slice(&self.secret).expect("hmac key");
        mac.update(format!("{h}.{p}").as_bytes());
        let sig = b64url_encode(&mac.finalize().into_bytes());
        format!("{h}.{p}.{sig}")
    }

    pub fn verify_jwt(&self, token: &str) -> Result<Option<User>, AuthError> {
        let parts: Vec<&str> = token.split('.').collect();
        if parts.len() != 3 {
            return Ok(None);
        }
        let (h, p, sig) = (parts[0], parts[1], parts[2]);
        let mut mac = HmacSha256::new_from_slice(&self.secret).expect("hmac key");
        mac.update(format!("{h}.{p}").as_bytes());
        let expected = b64url_encode(&mac.finalize().into_bytes());
        if !constant_time_eq(expected.as_bytes(), sig.as_bytes()) {
            return Ok(None);
        }
        let payload_bytes = match URL_SAFE_NO_PAD.decode(p) {
            Ok(b) => b,
            Err(_) => return Ok(None),
        };
        let payload: serde_json::Value = match serde_json::from_slice(&payload_bytes) {
            Ok(v) => v,
            Err(_) => return Ok(None),
        };
        let exp = payload.get("exp").and_then(|v| v.as_i64()).unwrap_or(0);
        if exp < Utc::now().timestamp() {
            return Ok(None);
        }
        let jti = payload.get("jti").and_then(|v| v.as_str()).unwrap_or("");
        {
            let con = self.conn.lock();
            let mut stmt = con.prepare("SELECT 1 FROM jwt_revocations WHERE jti=?")?;
            let revoked = stmt.exists(params![jti])?;
            if revoked {
                return Ok(None);
            }
        }
        let sub = payload.get("sub").and_then(|v| v.as_i64()).unwrap_or(0);
        match self.get_user(sub)? {
            Some(u) if !u.disabled => Ok(Some(u)),
            _ => Ok(None),
        }
    }

    pub fn revoke_jwt(&self, token: &str) -> Result<bool, AuthError> {
        let parts: Vec<&str> = token.split('.').collect();
        if parts.len() != 3 {
            return Ok(false);
        }
        let payload_bytes = match URL_SAFE_NO_PAD.decode(parts[1]) {
            Ok(b) => b,
            Err(_) => return Ok(false),
        };
        let payload: serde_json::Value = match serde_json::from_slice(&payload_bytes) {
            Ok(v) => v,
            Err(_) => return Ok(false),
        };
        let jti = payload.get("jti").and_then(|v| v.as_str()).unwrap_or("");
        let sub = payload.get("sub").and_then(|v| v.as_i64()).unwrap_or(0);
        let now = self.now();
        let con = self.conn.lock();
        con.execute(
            "INSERT OR IGNORE INTO jwt_revocations (jti, user_id, revoked_at) VALUES (?,?,?)",
            params![jti, sub, now],
        )?;
        Ok(true)
    }

    // ── API tokens ─────────────────────────────────────────────────────────

    pub fn issue_api_token(&self, user_id: i64) -> Result<String, AuthError> {
        let mut bytes = [0u8; 32];
        OsRng.fill_bytes(&mut bytes);
        let tok = format!("aim_{}", URL_SAFE_NO_PAD.encode(bytes));
        let con = self.conn.lock();
        con.execute(
            "UPDATE users SET api_token=? WHERE id=?",
            params![tok, user_id],
        )?;
        Ok(tok)
    }

    pub fn revoke_api_token(&self, user_id: i64) -> Result<(), AuthError> {
        let con = self.conn.lock();
        con.execute("UPDATE users SET api_token=NULL WHERE id=?", params![user_id])?;
        Ok(())
    }

    // ── Link codes ─────────────────────────────────────────────────────────

    pub fn create_link_code(&self, user_id: i64, ttl_min: i64) -> Result<String, AuthError> {
        use rand::Rng;
        let n: u32 = rand::thread_rng().gen_range(0..1_000_000);
        let code = format!("{:06}", n);
        let expires =
            (Utc::now() + chrono::Duration::minutes(ttl_min)).to_rfc3339();
        let con = self.conn.lock();
        con.execute(
            "INSERT OR REPLACE INTO link_codes (code, user_id, expires_at, used) VALUES (?,?,?,0)",
            params![code, user_id, expires],
        )?;
        Ok(code)
    }

    pub fn consume_link_code(
        &self,
        code: &str,
        telegram_id: i64,
    ) -> Result<Option<User>, AuthError> {
        let user_id = {
            let con = self.conn.lock();
            let row: Option<(i64, String)> = con
                .query_row(
                    "SELECT user_id, expires_at FROM link_codes WHERE code=? AND used=0",
                    params![code],
                    |r| Ok((r.get(0)?, r.get(1)?)),
                )
                .optional()?;
            let Some((uid, expires_at)) = row else {
                return Ok(None);
            };
            let exp: DateTime<Utc> = match expires_at.parse() {
                Ok(t) => t,
                Err(_) => return Ok(None),
            };
            if exp < Utc::now() {
                return Ok(None);
            }
            con.execute(
                "UPDATE link_codes SET used=1 WHERE code=?",
                params![code],
            )?;
            let r = con.execute(
                "UPDATE users SET telegram_id=? WHERE id=?",
                params![telegram_id, uid],
            );
            if let Err(rusqlite::Error::SqliteFailure(e, _)) = &r {
                if e.code == rusqlite::ErrorCode::ConstraintViolation {
                    return Ok(None);
                }
            }
            r?;
            uid
        };
        self.get_user(user_id)
    }

    // ── Audit log ──────────────────────────────────────────────────────────

    pub fn audit(
        &self,
        user_id: Option<i64>,
        action: &str,
        target: Option<&str>,
        ip: Option<&str>,
        ua: Option<&str>,
    ) -> Result<(), AuthError> {
        let now = self.now();
        let con = self.conn.lock();
        con.execute(
            "INSERT INTO audit_log (ts, user_id, action, target, ip, ua) VALUES (?,?,?,?,?,?)",
            params![now, user_id, action, target, ip, ua],
        )?;
        Ok(())
    }

    pub fn list_audit(
        &self,
        user_id: Option<i64>,
        limit: i64,
    ) -> Result<Vec<AuditEntry>, AuthError> {
        let con = self.conn.lock();
        let mapper = |row: &Row<'_>| -> rusqlite::Result<AuditEntry> {
            Ok(AuditEntry {
                id: row.get(0)?,
                ts: row.get(1)?,
                user_id: row.get(2)?,
                action: row.get(3)?,
                target: row.get(4)?,
                ip: row.get(5)?,
                ua: row.get(6)?,
            })
        };
        let entries: Vec<AuditEntry> = match user_id {
            Some(uid) => {
                let mut stmt = con.prepare(
                    "SELECT id, ts, user_id, action, target, ip, ua FROM audit_log WHERE user_id=? ORDER BY id DESC LIMIT ?",
                )?;
                let v: Vec<AuditEntry> = stmt
                    .query_map(params![uid, limit], mapper)?
                    .collect::<rusqlite::Result<Vec<_>>>()?;
                v
            }
            None => {
                let mut stmt = con.prepare(
                    "SELECT id, ts, user_id, action, target, ip, ua FROM audit_log ORDER BY id DESC LIMIT ?",
                )?;
                let v: Vec<AuditEntry> = stmt
                    .query_map(params![limit], mapper)?
                    .collect::<rusqlite::Result<Vec<_>>>()?;
                v
            }
        };
        Ok(entries)
    }

    // ── Nodes ──────────────────────────────────────────────────────────────

    pub fn record_node_heartbeat(
        &self,
        user_id: i64,
        node_id: &str,
        host: &str,
        version: &str,
    ) -> Result<(), AuthError> {
        let now = self.now();
        let con = self.conn.lock();
        con.execute(
            "INSERT INTO nodes (user_id, node_id, host, version, last_seen) \
             VALUES (?,?,?,?,?) \
             ON CONFLICT(user_id, node_id) DO UPDATE SET \
             host=excluded.host, version=excluded.version, last_seen=excluded.last_seen",
            params![user_id, node_id, host, version, now],
        )?;
        Ok(())
    }

    pub fn list_nodes(&self, user_id: Option<i64>) -> Result<Vec<NodeEntry>, AuthError> {
        let con = self.conn.lock();
        let entries: Vec<NodeEntry> = match user_id {
            Some(uid) => {
                let mut stmt = con.prepare(
                    "SELECT user_id, node_id, host, version, last_seen FROM nodes WHERE user_id=? ORDER BY last_seen DESC",
                )?;
                let v: Vec<NodeEntry> = stmt
                    .query_map(params![uid], |r| {
                        Ok(NodeEntry {
                            user_id: r.get(0)?,
                            node_id: r.get(1)?,
                            host: r.get::<_, Option<String>>(2)?.unwrap_or_default(),
                            version: r.get::<_, Option<String>>(3)?.unwrap_or_default(),
                            last_seen: r.get(4)?,
                            username: None,
                        })
                    })?
                    .collect::<rusqlite::Result<Vec<_>>>()?;
                v
            }
            None => {
                let mut stmt = con.prepare(
                    "SELECT n.user_id, n.node_id, n.host, n.version, n.last_seen, u.username \
                     FROM nodes n JOIN users u ON u.id=n.user_id ORDER BY n.last_seen DESC",
                )?;
                let v: Vec<NodeEntry> = stmt
                    .query_map([], |r| {
                        Ok(NodeEntry {
                            user_id: r.get(0)?,
                            node_id: r.get(1)?,
                            host: r.get::<_, Option<String>>(2)?.unwrap_or_default(),
                            version: r.get::<_, Option<String>>(3)?.unwrap_or_default(),
                            last_seen: r.get(4)?,
                            username: r.get(5)?,
                        })
                    })?
                    .collect::<rusqlite::Result<Vec<_>>>()?;
                v
            }
        };
        Ok(entries)
    }
}

// ── helpers ────────────────────────────────────────────────────────────────

fn secret_path(db_path: &Path) -> PathBuf {
    let mut p = db_path.to_path_buf();
    p.set_extension("secret");
    p
}

fn load_or_create_secret(path: &Path) -> Result<Vec<u8>, AuthError> {
    if path.exists() {
        return Ok(std::fs::read(path)?);
    }
    if let Some(parent) = path.parent() {
        if !parent.as_os_str().is_empty() {
            std::fs::create_dir_all(parent)?;
        }
    }
    let mut bytes = vec![0u8; 64];
    OsRng.fill_bytes(&mut bytes);
    std::fs::write(path, &bytes)?;
    secure_perms(path);
    Ok(bytes)
}

#[cfg(unix)]
fn secure_perms(p: &Path) {
    use std::os::unix::fs::PermissionsExt;
    let _ = std::fs::set_permissions(p, std::fs::Permissions::from_mode(0o600));
}

#[cfg(not(unix))]
fn secure_perms(_p: &Path) {}

fn hash_password(password: &str) -> Result<String, AuthError> {
    let salt = SaltString::generate(&mut OsRng);
    let argon = Argon2::default();
    argon
        .hash_password(password.as_bytes(), &salt)
        .map(|h| h.to_string())
        .map_err(|e| AuthError::Argon2(e.to_string()))
}

fn b64url_encode(b: &[u8]) -> String {
    URL_SAFE_NO_PAD.encode(b)
}

fn random_hex(n_bytes: usize) -> String {
    let mut buf = vec![0u8; n_bytes];
    OsRng.fill_bytes(&mut buf);
    let mut s = String::with_capacity(n_bytes * 2);
    for byte in buf {
        s.push_str(&format!("{:02x}", byte));
    }
    s
}

fn constant_time_eq(a: &[u8], b: &[u8]) -> bool {
    if a.len() != b.len() {
        return false;
    }
    let mut acc = 0u8;
    for (x, y) in a.iter().zip(b.iter()) {
        acc |= x ^ y;
    }
    acc == 0
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    fn fresh_hub() -> (TempDir, Hub) {
        let dir = TempDir::new().unwrap();
        let db = dir.path().join("hub.db");
        let hub = Hub::open(&db).unwrap();
        (dir, hub)
    }

    #[test]
    fn create_and_lookup_user() {
        let (_d, hub) = fresh_hub();
        let u = hub.create_user("alice", "secret-password", "user", None).unwrap();
        assert_eq!(u.username, "alice");
        assert!(!u.disabled);
        let by_name = hub.get_user_by_username("alice").unwrap().unwrap();
        assert_eq!(by_name.id, u.id);
    }

    #[test]
    fn reject_short_password() {
        let (_d, hub) = fresh_hub();
        let e = hub
            .create_user("alice", "short", "user", None)
            .unwrap_err();
        assert!(matches!(e, AuthError::PasswordTooShort));
    }

    #[test]
    fn reject_invalid_role() {
        let (_d, hub) = fresh_hub();
        let e = hub
            .create_user("alice", "secret-password", "root", None)
            .unwrap_err();
        assert!(matches!(e, AuthError::InvalidRole));
    }

    #[test]
    fn duplicate_username_rejected() {
        let (_d, hub) = fresh_hub();
        hub.create_user("alice", "secret-password", "user", None)
            .unwrap();
        let e = hub
            .create_user("alice", "another-password", "user", None)
            .unwrap_err();
        assert!(matches!(e, AuthError::DuplicateUsername(_)));
    }

    #[test]
    fn verify_password_happy_path() {
        let (_d, hub) = fresh_hub();
        hub.create_user("alice", "secret-password", "user", None)
            .unwrap();
        let u = hub.verify_password("alice", "secret-password").unwrap();
        assert!(u.is_some());
        assert!(u.unwrap().last_login_at.is_some());
    }

    #[test]
    fn verify_password_wrong_password() {
        let (_d, hub) = fresh_hub();
        hub.create_user("alice", "secret-password", "user", None)
            .unwrap();
        assert!(hub.verify_password("alice", "wrong-pw-x").unwrap().is_none());
    }

    #[test]
    fn verify_password_unknown_user_runs_dummy_hash() {
        let (_d, hub) = fresh_hub();
        // Just shouldn't panic and should return None
        assert!(hub.verify_password("ghost", "any-password").unwrap().is_none());
    }

    #[test]
    fn disabled_user_rejected() {
        let (_d, hub) = fresh_hub();
        let u = hub.create_user("alice", "secret-password", "user", None).unwrap();
        hub.disable_user(u.id).unwrap();
        assert!(hub.verify_password("alice", "secret-password").unwrap().is_none());
        hub.enable_user(u.id).unwrap();
        assert!(hub.verify_password("alice", "secret-password").unwrap().is_some());
    }

    #[test]
    fn jwt_round_trip() {
        let (_d, hub) = fresh_hub();
        let u = hub.create_user("alice", "secret-password", "admin", None).unwrap();
        let tok = hub.issue_jwt(u.id, 7);
        let v = hub.verify_jwt(&tok).unwrap().unwrap();
        assert_eq!(v.id, u.id);
        assert_eq!(v.role, "admin");
    }

    #[test]
    fn jwt_revocation_blocks_verify() {
        let (_d, hub) = fresh_hub();
        let u = hub.create_user("alice", "secret-password", "user", None).unwrap();
        let tok = hub.issue_jwt(u.id, 7);
        assert!(hub.revoke_jwt(&tok).unwrap());
        assert!(hub.verify_jwt(&tok).unwrap().is_none());
    }

    #[test]
    fn jwt_tampered_signature_rejected() {
        let (_d, hub) = fresh_hub();
        let u = hub.create_user("alice", "secret-password", "user", None).unwrap();
        let tok = hub.issue_jwt(u.id, 7);
        // Flip last byte of signature
        let mut chars: Vec<char> = tok.chars().collect();
        let last = chars.last_mut().unwrap();
        *last = if *last == 'A' { 'B' } else { 'A' };
        let tampered: String = chars.into_iter().collect();
        assert!(hub.verify_jwt(&tampered).unwrap().is_none());
    }

    #[test]
    fn jwt_disabled_user_rejected_after_issue() {
        let (_d, hub) = fresh_hub();
        let u = hub.create_user("alice", "secret-password", "user", None).unwrap();
        let tok = hub.issue_jwt(u.id, 7);
        hub.disable_user(u.id).unwrap();
        assert!(hub.verify_jwt(&tok).unwrap().is_none());
    }

    #[test]
    fn api_token_lookup() {
        let (_d, hub) = fresh_hub();
        let u = hub.create_user("alice", "secret-password", "user", None).unwrap();
        let tok = hub.issue_api_token(u.id).unwrap();
        assert!(tok.starts_with("aim_"));
        let back = hub.get_user_by_token(&tok).unwrap().unwrap();
        assert_eq!(back.id, u.id);
        hub.revoke_api_token(u.id).unwrap();
        assert!(hub.get_user_by_token(&tok).unwrap().is_none());
    }

    #[test]
    fn link_code_round_trip() {
        let (_d, hub) = fresh_hub();
        let u = hub.create_user("alice", "secret-password", "user", None).unwrap();
        let code = hub.create_link_code(u.id, 10).unwrap();
        assert_eq!(code.len(), 6);
        let bound = hub.consume_link_code(&code, 12345).unwrap().unwrap();
        assert_eq!(bound.id, u.id);
        assert_eq!(bound.telegram_id, Some(12345));
        // Second consume should fail (used)
        assert!(hub.consume_link_code(&code, 12345).unwrap().is_none());
    }

    #[test]
    fn link_code_expired() {
        let (_d, hub) = fresh_hub();
        let u = hub.create_user("alice", "secret-password", "user", None).unwrap();
        let code = hub.create_link_code(u.id, -1).unwrap(); // already expired
        assert!(hub.consume_link_code(&code, 12345).unwrap().is_none());
    }

    #[test]
    fn audit_round_trip() {
        let (_d, hub) = fresh_hub();
        let u = hub.create_user("alice", "secret-password", "user", None).unwrap();
        hub.audit(Some(u.id), "login", Some("cli"), Some("127.0.0.1"), None)
            .unwrap();
        hub.audit(None, "anonymous", None, None, None).unwrap();
        let mine = hub.list_audit(Some(u.id), 100).unwrap();
        assert_eq!(mine.len(), 1);
        assert_eq!(mine[0].action, "login");
        let all = hub.list_audit(None, 100).unwrap();
        assert_eq!(all.len(), 2);
    }

    #[test]
    fn nodes_heartbeat_upsert() {
        let (_d, hub) = fresh_hub();
        let u = hub.create_user("alice", "secret-password", "user", None).unwrap();
        hub.record_node_heartbeat(u.id, "laptop-jaba", "alice-pc", "7.0")
            .unwrap();
        hub.record_node_heartbeat(u.id, "laptop-jaba", "alice-pc-2", "7.0")
            .unwrap();
        let nodes = hub.list_nodes(Some(u.id)).unwrap();
        assert_eq!(nodes.len(), 1);
        assert_eq!(nodes[0].host, "alice-pc-2");
        let global = hub.list_nodes(None).unwrap();
        assert_eq!(global.len(), 1);
        assert_eq!(global[0].username.as_deref(), Some("alice"));
    }

    #[test]
    fn banned_column_check_passes_on_clean_schema() {
        let (_d, hub) = fresh_hub();
        let con = hub.conn.lock();
        assert!(assert_no_llm_key_columns(&con).is_ok());
    }

    #[test]
    fn banned_column_check_trips_on_violation() {
        let dir = TempDir::new().unwrap();
        let db = dir.path().join("dirty.db");
        let con = rusqlite::Connection::open(&db).unwrap();
        con.execute_batch(SCHEMA).unwrap();
        con.execute("ALTER TABLE users ADD COLUMN deepseek_api_key TEXT", [])
            .unwrap();
        let e = assert_no_llm_key_columns(&con).unwrap_err();
        assert!(matches!(e, AuthError::BannedKeyColumn(_, _)));
    }

    #[test]
    fn secret_persisted_across_reopen() {
        let dir = TempDir::new().unwrap();
        let db = dir.path().join("hub.db");
        let h1 = Hub::open(&db).unwrap();
        let u = h1.create_user("alice", "secret-password", "user", None).unwrap();
        let tok = h1.issue_jwt(u.id, 7);
        drop(h1);
        let h2 = Hub::open(&db).unwrap();
        let v = h2.verify_jwt(&tok).unwrap().unwrap();
        assert_eq!(v.id, u.id);
    }
}
