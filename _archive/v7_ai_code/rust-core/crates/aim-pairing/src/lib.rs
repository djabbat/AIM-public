//! aim-pairing — 6-digit device pairing codes (Tailscale-style).
//!
//! Port of `agents/pairing.py`. Hub-side issues a short code valid for N
//! minutes; node-side consumes the code and receives a long-lived API
//! token. Differs from `auth.link_codes` (which bind a Telegram account):
//! these bind a *device*.
//!
//! Storage + auth-side effects sit behind traits ([`PairCodeStore`],
//! [`AuthBackend`]) so the issue/consume/cleanup logic is testable
//! without sqlite or the real auth crate.

use chrono::{DateTime, Duration, Utc};
use rand::Rng;
use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum PairingError {
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
    #[error("store error: {0}")]
    Store(String),
    #[error("auth error: {0}")]
    Auth(String),
}

pub type Result<T> = std::result::Result<T, PairingError>;

// ── data ────────────────────────────────────────────────────────────────────

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct PairCode {
    pub code: String,
    pub user_id: i64,
    pub expires_at: DateTime<Utc>,
    pub used: bool,
    pub created_at: DateTime<Utc>,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct User {
    pub id: i64,
    pub username: String,
    pub disabled: bool,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct ConsumeOutcome {
    pub token: String,
    pub user: User,
}

// ── traits ──────────────────────────────────────────────────────────────────

/// Pluggable storage. Production uses rusqlite over `pair_codes`; tests
/// use an in-memory map.
pub trait PairCodeStore: Send + Sync {
    fn invalidate_unused_for_user(&self, user_id: i64) -> Result<usize>;
    fn insert(&self, pc: &PairCode) -> Result<()>;
    fn fetch_unused(&self, code: &str) -> Result<Option<PairCode>>;
    /// Atomic mark-used. Returns `Ok(true)` only on the single update.
    fn mark_used(&self, code: &str) -> Result<bool>;
    /// Delete codes older than `cutoff` OR (used && older than cutoff).
    fn cleanup_older_than(&self, cutoff: DateTime<Utc>) -> Result<usize>;
}

pub trait AuthBackend: Send + Sync {
    fn get_user(&self, user_id: i64) -> Result<Option<User>>;
    fn issue_api_token(&self, user_id: i64) -> Result<String>;
    fn record_node_heartbeat(
        &self,
        user_id: i64,
        node_id: &str,
        host: &str,
        version: &str,
    ) -> Result<()>;
    fn audit(&self, user_id: i64, action: &str, target: &str) -> Result<()>;
}

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

// ── code generation ─────────────────────────────────────────────────────────

/// Generate a fresh zero-padded 6-digit string in the range `[0, 1_000_000)`.
/// Mirrors Python `f"{secrets.randbelow(1_000_000):06d}"`.
pub fn generate_code() -> String {
    let n: u32 = rand::thread_rng().gen_range(0..1_000_000);
    format!("{:06}", n)
}

/// Validate a code: 6 ASCII digits.
pub fn is_well_formed(code: &str) -> bool {
    code.len() == 6 && code.chars().all(|c| c.is_ascii_digit())
}

// ── service ─────────────────────────────────────────────────────────────────

pub struct Pairing<'a> {
    pub store: &'a dyn PairCodeStore,
    pub auth: &'a dyn AuthBackend,
    pub clock: &'a dyn Clock,
}

impl<'a> Pairing<'a> {
    pub fn new(
        store: &'a dyn PairCodeStore,
        auth: &'a dyn AuthBackend,
        clock: &'a dyn Clock,
    ) -> Self {
        Self { store, auth, clock }
    }

    /// Issue a fresh code bound to `user_id`, valid for `ttl_min` minutes.
    /// Older non-used codes for the same user are invalidated.
    pub fn issue(&self, user_id: i64, ttl_min: i64) -> Result<(String, DateTime<Utc>)> {
        let _ = self.store.invalidate_unused_for_user(user_id)?;
        let code = generate_code();
        let now = self.clock.now();
        let expires_at = now + Duration::minutes(ttl_min);
        self.store.insert(&PairCode {
            code: code.clone(),
            user_id,
            expires_at,
            used: false,
            created_at: now,
        })?;
        // audit prints code's first 2 digits (rest masked) — verbatim Python
        let masked = format!("{}****", code.chars().take(2).collect::<String>());
        self.auth.audit(user_id, "pair.issue", &masked)?;
        Ok((code, expires_at))
    }

    /// Atomically validate a code, mark used, issue a token, and record
    /// the calling node. Returns `Ok(None)` when the code is invalid /
    /// expired / consumed / belongs to a disabled user.
    pub fn consume(
        &self,
        code: &str,
        node_id: &str,
        host: &str,
        version: &str,
    ) -> Result<Option<ConsumeOutcome>> {
        let trimmed = code.trim();
        if !is_well_formed(trimmed) {
            return Ok(None);
        }
        let row = match self.store.fetch_unused(trimmed)? {
            Some(r) => r,
            None => return Ok(None),
        };
        if row.expires_at < self.clock.now() {
            return Ok(None);
        }
        if !self.store.mark_used(trimmed)? {
            return Ok(None);
        }
        let user = match self.auth.get_user(row.user_id)? {
            Some(u) if !u.disabled => u,
            _ => return Ok(None),
        };
        let token = self.auth.issue_api_token(user.id)?;
        if !node_id.is_empty() {
            self.auth.record_node_heartbeat(user.id, node_id, host, version)?;
        }
        let target = if node_id.is_empty() { "?" } else { node_id };
        self.auth.audit(user.id, "pair.consume", target)?;
        Ok(Some(ConsumeOutcome { token, user }))
    }

    /// Delete codes older than `older_than_min` minutes. Returns the count.
    pub fn cleanup_expired(&self, older_than_min: i64) -> Result<usize> {
        let cutoff = self.clock.now() - Duration::minutes(older_than_min);
        self.store.cleanup_older_than(cutoff)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use parking_lot::Mutex;
    use std::collections::HashMap;
    use std::sync::Arc;

    // ── stubs ───────────────────────────────────────────────────────────────

    #[derive(Default)]
    struct InMemStore {
        codes: Mutex<HashMap<String, PairCode>>,
    }
    impl PairCodeStore for InMemStore {
        fn invalidate_unused_for_user(&self, user_id: i64) -> Result<usize> {
            let mut m = self.codes.lock();
            let mut n = 0;
            for v in m.values_mut() {
                if v.user_id == user_id && !v.used {
                    v.used = true;
                    n += 1;
                }
            }
            Ok(n)
        }
        fn insert(&self, pc: &PairCode) -> Result<()> {
            self.codes.lock().insert(pc.code.clone(), pc.clone());
            Ok(())
        }
        fn fetch_unused(&self, code: &str) -> Result<Option<PairCode>> {
            Ok(self
                .codes
                .lock()
                .get(code)
                .filter(|c| !c.used)
                .cloned())
        }
        fn mark_used(&self, code: &str) -> Result<bool> {
            let mut m = self.codes.lock();
            match m.get_mut(code) {
                Some(c) if !c.used => {
                    c.used = true;
                    Ok(true)
                }
                _ => Ok(false),
            }
        }
        fn cleanup_older_than(&self, cutoff: DateTime<Utc>) -> Result<usize> {
            let mut m = self.codes.lock();
            let before = m.len();
            m.retain(|_, c| !(c.created_at < cutoff || (c.used && c.created_at < cutoff)));
            Ok(before - m.len())
        }
    }

    #[derive(Default)]
    struct StubAuth {
        users: Mutex<HashMap<i64, User>>,
        token_seq: Mutex<u64>,
        heartbeats: Mutex<Vec<(i64, String, String, String)>>,
        audit_log: Mutex<Vec<(i64, String, String)>>,
    }
    impl StubAuth {
        fn add_user(&self, id: i64, username: &str, disabled: bool) {
            self.users.lock().insert(
                id,
                User {
                    id,
                    username: username.into(),
                    disabled,
                },
            );
        }
    }
    impl AuthBackend for StubAuth {
        fn get_user(&self, user_id: i64) -> Result<Option<User>> {
            Ok(self.users.lock().get(&user_id).cloned())
        }
        fn issue_api_token(&self, _user_id: i64) -> Result<String> {
            let mut s = self.token_seq.lock();
            *s += 1;
            Ok(format!("tok-{}", *s))
        }
        fn record_node_heartbeat(
            &self,
            user_id: i64,
            node_id: &str,
            host: &str,
            version: &str,
        ) -> Result<()> {
            self.heartbeats.lock().push((
                user_id,
                node_id.into(),
                host.into(),
                version.into(),
            ));
            Ok(())
        }
        fn audit(&self, user_id: i64, action: &str, target: &str) -> Result<()> {
            self.audit_log
                .lock()
                .push((user_id, action.into(), target.into()));
            Ok(())
        }
    }

    fn fixed(secs: i64) -> FixedClock {
        FixedClock(DateTime::from_timestamp(secs, 0).unwrap())
    }

    // ── code generation ─────────────────────────────────────────────────────

    #[test]
    fn generated_code_is_six_digits() {
        for _ in 0..50 {
            let c = generate_code();
            assert!(is_well_formed(&c), "bad code: {}", c);
        }
    }

    #[test]
    fn well_formed_rejects_bad_input() {
        assert!(!is_well_formed(""));
        assert!(!is_well_formed("12345"));
        assert!(!is_well_formed("12345 "));
        assert!(!is_well_formed("12345a"));
        assert!(!is_well_formed("0123456"));
        assert!(is_well_formed("000000"));
        assert!(is_well_formed("999999"));
    }

    // ── issue ───────────────────────────────────────────────────────────────

    #[test]
    fn issue_inserts_code_and_audits() {
        let store = InMemStore::default();
        let auth = StubAuth::default();
        auth.add_user(1, "alice", false);
        let clock = fixed(1_700_000_000);
        let svc = Pairing::new(&store, &auth, &clock);
        let (code, expires) = svc.issue(1, 10).unwrap();
        assert!(is_well_formed(&code));
        assert_eq!(expires, clock.0 + Duration::minutes(10));
        assert_eq!(store.codes.lock().len(), 1);
        let log = auth.audit_log.lock();
        assert_eq!(log.len(), 1);
        assert_eq!(log[0].1, "pair.issue");
        assert!(log[0].2.ends_with("****"));
    }

    #[test]
    fn issue_invalidates_previous_codes_for_user() {
        let store = InMemStore::default();
        let auth = StubAuth::default();
        auth.add_user(1, "alice", false);
        let clock = fixed(1_700_000_000);
        let svc = Pairing::new(&store, &auth, &clock);
        let (c1, _) = svc.issue(1, 10).unwrap();
        let (c2, _) = svc.issue(1, 10).unwrap();
        let codes = store.codes.lock();
        // c1 → used=true; c2 → used=false
        assert!(codes.get(&c1).unwrap().used);
        assert!(!codes.get(&c2).unwrap().used);
    }

    // ── consume happy path ─────────────────────────────────────────────────

    #[test]
    fn consume_valid_code_returns_outcome() {
        let store = InMemStore::default();
        let auth = StubAuth::default();
        auth.add_user(1, "alice", false);
        let clock = fixed(1_700_000_000);
        let svc = Pairing::new(&store, &auth, &clock);
        let (code, _) = svc.issue(1, 10).unwrap();
        let outcome = svc
            .consume(&code, "node-1", "host.local", "0.1.0")
            .unwrap()
            .unwrap();
        assert_eq!(outcome.user.id, 1);
        assert!(outcome.token.starts_with("tok-"));
        // node heartbeat recorded
        let hb = auth.heartbeats.lock();
        assert_eq!(hb.len(), 1);
        assert_eq!(hb[0].1, "node-1");
        // audit pair.consume recorded
        assert!(auth
            .audit_log
            .lock()
            .iter()
            .any(|(_, a, _)| a == "pair.consume"));
    }

    #[test]
    fn consume_skips_heartbeat_when_node_id_empty() {
        let store = InMemStore::default();
        let auth = StubAuth::default();
        auth.add_user(1, "alice", false);
        let clock = fixed(1_700_000_000);
        let svc = Pairing::new(&store, &auth, &clock);
        let (code, _) = svc.issue(1, 10).unwrap();
        svc.consume(&code, "", "", "").unwrap();
        assert!(auth.heartbeats.lock().is_empty());
        // audit target is "?"
        let consume_audit = auth
            .audit_log
            .lock()
            .iter()
            .find(|(_, a, _)| a == "pair.consume")
            .cloned();
        assert_eq!(consume_audit.unwrap().2, "?");
    }

    // ── consume guard branches ─────────────────────────────────────────────

    #[test]
    fn consume_malformed_code_returns_none() {
        let store = InMemStore::default();
        let auth = StubAuth::default();
        let clock = fixed(0);
        let svc = Pairing::new(&store, &auth, &clock);
        assert!(svc.consume("12345", "n", "h", "v").unwrap().is_none());
        assert!(svc.consume("abcdef", "n", "h", "v").unwrap().is_none());
    }

    #[test]
    fn consume_unknown_code_returns_none() {
        let store = InMemStore::default();
        let auth = StubAuth::default();
        let clock = fixed(0);
        let svc = Pairing::new(&store, &auth, &clock);
        assert!(svc.consume("123456", "n", "h", "v").unwrap().is_none());
    }

    #[test]
    fn consume_expired_code_returns_none() {
        // Use a clock that advances by Duration on every call past the first
        struct AdvancingClock {
            base: DateTime<Utc>,
            calls: Mutex<i64>,
            advance_after: i64,
            advance_by: Duration,
        }
        impl Clock for AdvancingClock {
            fn now(&self) -> DateTime<Utc> {
                let mut n = self.calls.lock();
                *n += 1;
                if *n > self.advance_after {
                    self.base + self.advance_by
                } else {
                    self.base
                }
            }
        }
        let store = InMemStore::default();
        let auth = StubAuth::default();
        auth.add_user(1, "alice", false);
        let clock = AdvancingClock {
            base: DateTime::from_timestamp(1_700_000_000, 0).unwrap(),
            calls: Mutex::new(0),
            // issue() makes 1 clock call; subsequent calls in consume() return advanced time
            advance_after: 1,
            advance_by: Duration::minutes(10),
        };
        let svc = Pairing::new(&store, &auth, &clock);
        let (code, _) = svc.issue(1, 5).unwrap();
        // consume() calls clock(s) — all advanced past expiry
        assert!(svc.consume(&code, "n", "h", "v").unwrap().is_none());
    }

    #[test]
    fn consume_already_used_returns_none() {
        let store = InMemStore::default();
        let auth = StubAuth::default();
        auth.add_user(1, "alice", false);
        let clock = fixed(1_700_000_000);
        let svc = Pairing::new(&store, &auth, &clock);
        let (code, _) = svc.issue(1, 10).unwrap();
        svc.consume(&code, "n", "h", "v").unwrap();
        // second consume of same code → None
        assert!(svc.consume(&code, "n", "h", "v").unwrap().is_none());
    }

    #[test]
    fn consume_disabled_user_returns_none() {
        let store = InMemStore::default();
        let auth = StubAuth::default();
        auth.add_user(1, "alice", true);
        let clock = fixed(1_700_000_000);
        let svc = Pairing::new(&store, &auth, &clock);
        let (code, _) = svc.issue(1, 10).unwrap();
        assert!(svc.consume(&code, "n", "h", "v").unwrap().is_none());
    }

    #[test]
    fn consume_missing_user_returns_none() {
        let store = InMemStore::default();
        let auth = StubAuth::default();
        // user id 1 not added to auth, but code refers to it
        let clock = fixed(1_700_000_000);
        let svc = Pairing::new(&store, &auth, &clock);
        store
            .insert(&PairCode {
                code: "555555".into(),
                user_id: 99,
                expires_at: clock.now() + Duration::minutes(5),
                used: false,
                created_at: clock.now(),
            })
            .unwrap();
        assert!(svc.consume("555555", "n", "h", "v").unwrap().is_none());
    }

    // ── cleanup ─────────────────────────────────────────────────────────────

    #[test]
    fn cleanup_drops_old_used_codes() {
        let store = InMemStore::default();
        let auth = StubAuth::default();
        auth.add_user(1, "alice", false);
        let clock = fixed(1_700_000_000);
        let svc = Pairing::new(&store, &auth, &clock);
        // Old used code
        store
            .insert(&PairCode {
                code: "111111".into(),
                user_id: 1,
                expires_at: clock.now(),
                used: true,
                created_at: clock.now() - Duration::hours(2),
            })
            .unwrap();
        // Recent unused code
        store
            .insert(&PairCode {
                code: "222222".into(),
                user_id: 1,
                expires_at: clock.now() + Duration::hours(1),
                used: false,
                created_at: clock.now(),
            })
            .unwrap();
        let n = svc.cleanup_expired(60).unwrap();
        assert_eq!(n, 1);
        let codes = store.codes.lock();
        assert!(codes.contains_key("222222"));
        assert!(!codes.contains_key("111111"));
    }
}
