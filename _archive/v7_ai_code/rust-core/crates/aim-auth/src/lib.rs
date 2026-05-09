//! aim-auth — hub-side authentication primitives.
//!
//! Port of `agents/auth.py`, focused on the testable surface:
//!
//! - User / token / link-code data shapes
//! - URL-safe opaque token generation
//! - 6-digit numeric link-code generation
//! - JWT-shaped HMAC-SHA-256 signing/verification (compact, no external dep)
//! - Pluggable [`PasswordHasher`], [`UserStore`], and [`Clock`] traits
//!
//! Production wires `argon2` for password hashing, `rusqlite` for the
//! user store, and the `chrono` system clock. None of those are required
//! to exercise the orchestration logic in tests.
//!
//! ## Hub invariant
//! The hub MUST NEVER store, accept, or proxy LLM provider keys.
//! [`User`] intentionally has no `api_key` field. Adding one would break
//! the per-user billing model.

use std::time::Duration;

use base64::Engine;
use chrono::{DateTime, Duration as ChronoDuration, Utc};
use hmac::{Hmac, Mac};
use rand::Rng;
use serde::{Deserialize, Serialize};
use sha2::Sha256;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum AuthError {
    #[error("user not found: {0}")]
    UserNotFound(String),
    #[error("invalid password")]
    InvalidPassword,
    #[error("invalid token")]
    InvalidToken,
    #[error("expired")]
    Expired,
    #[error("disabled user")]
    Disabled,
    #[error("hash error: {0}")]
    Hash(String),
    #[error("store error: {0}")]
    Store(String),
}

pub type Result<T> = std::result::Result<T, AuthError>;

// ── data ────────────────────────────────────────────────────────────────────

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Role {
    Admin,
    User,
}

impl Default for Role {
    fn default() -> Self {
        Self::User
    }
}

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct User {
    pub id: i64,
    pub username: String,
    pub email: Option<String>,
    pub password_hash: String,
    pub role: Role,
    pub api_token: Option<String>,
    pub telegram_id: Option<i64>,
    pub disabled: bool,
    pub created_at: DateTime<Utc>,
    pub last_login_at: Option<DateTime<Utc>>,
    // No api_key field — hub MUST NEVER store LLM keys.
}

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct LinkCode {
    pub code: String,
    pub user_id: i64,
    pub expires_at: DateTime<Utc>,
    pub used: bool,
}

// ── token / code generation ────────────────────────────────────────────────

/// Generate an opaque URL-safe token. Default length matches Python's
/// `secrets.token_urlsafe(48)` (~64 chars).
pub fn issue_opaque_token(byte_len: usize) -> String {
    let bytes: Vec<u8> = (0..byte_len)
        .map(|_| rand::thread_rng().gen::<u8>())
        .collect();
    base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(&bytes)
}

/// Generate a 6-digit zero-padded link code in the range `[0, 1_000_000)`.
pub fn issue_link_code() -> String {
    let n: u32 = rand::thread_rng().gen_range(0..1_000_000);
    format!("{:06}", n)
}

pub fn is_well_formed_link_code(code: &str) -> bool {
    code.len() == 6 && code.chars().all(|c| c.is_ascii_digit())
}

// ── HMAC-signed compact JWT (HS256) ────────────────────────────────────────

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct JwtClaims {
    pub sub: i64,
    pub iat: i64,
    pub exp: i64,
}

fn b64url(input: &[u8]) -> String {
    base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(input)
}

fn b64url_decode(input: &str) -> Result<Vec<u8>> {
    base64::engine::general_purpose::URL_SAFE_NO_PAD
        .decode(input)
        .map_err(|_e| AuthError::InvalidToken)
}

const HEADER_HS256: &str = r#"{"alg":"HS256","typ":"JWT"}"#;

pub fn sign_jwt(secret: &[u8], claims: &JwtClaims) -> Result<String> {
    let header_b64 = b64url(HEADER_HS256.as_bytes());
    let payload_json = serde_json::to_string(claims)
        .map_err(|e| AuthError::Hash(format!("serialise: {}", e)))?;
    let payload_b64 = b64url(payload_json.as_bytes());
    let signing_input = format!("{}.{}", header_b64, payload_b64);
    let mut mac = <Hmac<Sha256> as Mac>::new_from_slice(secret)
        .map_err(|e| AuthError::Hash(format!("hmac key: {}", e)))?;
    mac.update(signing_input.as_bytes());
    let sig = mac.finalize().into_bytes();
    let sig_b64 = b64url(&sig);
    Ok(format!("{}.{}", signing_input, sig_b64))
}

pub fn verify_jwt(secret: &[u8], token: &str, now: DateTime<Utc>) -> Result<JwtClaims> {
    let parts: Vec<&str> = token.split('.').collect();
    if parts.len() != 3 {
        return Err(AuthError::InvalidToken);
    }
    let signing_input = format!("{}.{}", parts[0], parts[1]);
    let sig_bytes = b64url_decode(parts[2])?;
    let mut mac = <Hmac<Sha256> as Mac>::new_from_slice(secret)
        .map_err(|e| AuthError::Hash(format!("hmac key: {}", e)))?;
    mac.update(signing_input.as_bytes());
    mac.verify_slice(&sig_bytes)
        .map_err(|_| AuthError::InvalidToken)?;
    let payload_bytes = b64url_decode(parts[1])?;
    let claims: JwtClaims =
        serde_json::from_slice(&payload_bytes).map_err(|_| AuthError::InvalidToken)?;
    if claims.exp <= now.timestamp() {
        return Err(AuthError::Expired);
    }
    Ok(claims)
}

pub fn issue_jwt(
    secret: &[u8],
    user_id: i64,
    ttl: Duration,
    now: DateTime<Utc>,
) -> Result<String> {
    let exp = now + ChronoDuration::from_std(ttl).unwrap_or(ChronoDuration::days(7));
    let claims = JwtClaims {
        sub: user_id,
        iat: now.timestamp(),
        exp: exp.timestamp(),
    };
    sign_jwt(secret, &claims)
}

// ── traits ──────────────────────────────────────────────────────────────────

pub trait PasswordHasher: Send + Sync {
    /// Hash `password` and return the encoded hash string (e.g. argon2 PHC).
    fn hash(&self, password: &str) -> Result<String>;
    /// Verify against an encoded hash. Returns `Ok(())` on match,
    /// `Err(InvalidPassword)` on mismatch, other errors on storage corruption.
    fn verify(&self, encoded: &str, password: &str) -> Result<()>;
}

/// Plaintext-equality "hasher" — for tests only. Production binds argon2.
pub struct PlainHasher;
impl PasswordHasher for PlainHasher {
    fn hash(&self, password: &str) -> Result<String> {
        Ok(format!("plain${}", password))
    }
    fn verify(&self, encoded: &str, password: &str) -> Result<()> {
        let expected = format!("plain${}", password);
        if encoded == expected {
            Ok(())
        } else {
            Err(AuthError::InvalidPassword)
        }
    }
}

pub trait UserStore: Send + Sync {
    fn create_user(&self, user: User) -> Result<i64>;
    fn find_by_username(&self, username: &str) -> Result<Option<User>>;
    fn find_by_id(&self, id: i64) -> Result<Option<User>>;
    fn find_by_token(&self, api_token: &str) -> Result<Option<User>>;
    fn update_token(&self, id: i64, token: Option<String>) -> Result<()>;
    fn touch_login(&self, id: i64, when: DateTime<Utc>) -> Result<()>;
    fn set_disabled(&self, id: i64, disabled: bool) -> Result<()>;
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

// ── service ─────────────────────────────────────────────────────────────────

pub struct AuthService<'a> {
    pub store: &'a dyn UserStore,
    pub hasher: &'a dyn PasswordHasher,
    pub clock: &'a dyn Clock,
    pub jwt_secret: Vec<u8>,
}

impl<'a> AuthService<'a> {
    pub fn new(
        store: &'a dyn UserStore,
        hasher: &'a dyn PasswordHasher,
        clock: &'a dyn Clock,
        jwt_secret: Vec<u8>,
    ) -> Self {
        Self {
            store,
            hasher,
            clock,
            jwt_secret,
        }
    }

    pub fn create_user(
        &self,
        username: &str,
        password: &str,
        role: Role,
        email: Option<String>,
    ) -> Result<i64> {
        let hash = self.hasher.hash(password)?;
        let user = User {
            id: 0, // assigned by store
            username: username.into(),
            email,
            password_hash: hash,
            role,
            api_token: None,
            telegram_id: None,
            disabled: false,
            created_at: self.clock.now(),
            last_login_at: None,
        };
        self.store.create_user(user)
    }

    pub fn verify_password(&self, username: &str, password: &str) -> Result<User> {
        let user = self
            .store
            .find_by_username(username)?
            .ok_or_else(|| AuthError::UserNotFound(username.into()))?;
        if user.disabled {
            return Err(AuthError::Disabled);
        }
        self.hasher.verify(&user.password_hash, password)?;
        self.store.touch_login(user.id, self.clock.now())?;
        Ok(user)
    }

    pub fn issue_api_token(&self, user_id: i64) -> Result<String> {
        let token = issue_opaque_token(48);
        self.store.update_token(user_id, Some(token.clone()))?;
        Ok(token)
    }

    pub fn revoke_api_token(&self, user_id: i64) -> Result<()> {
        self.store.update_token(user_id, None)
    }

    pub fn user_for_token(&self, token: &str) -> Result<User> {
        self.store
            .find_by_token(token)?
            .ok_or(AuthError::InvalidToken)
            .and_then(|u| {
                if u.disabled {
                    Err(AuthError::Disabled)
                } else {
                    Ok(u)
                }
            })
    }

    pub fn issue_jwt(&self, user_id: i64, ttl: Duration) -> Result<String> {
        issue_jwt(&self.jwt_secret, user_id, ttl, self.clock.now())
    }

    pub fn verify_jwt(&self, token: &str) -> Result<User> {
        let claims = verify_jwt(&self.jwt_secret, token, self.clock.now())?;
        self.store
            .find_by_id(claims.sub)?
            .ok_or(AuthError::InvalidToken)
            .and_then(|u| {
                if u.disabled {
                    Err(AuthError::Disabled)
                } else {
                    Ok(u)
                }
            })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;
    use parking_lot::Mutex;

    // ── token / code generation ────────────────────────────────────────────

    #[test]
    fn opaque_token_is_url_safe_and_long() {
        let t = issue_opaque_token(48);
        assert!(t.chars().count() > 50);
        assert!(t
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_'));
    }

    #[test]
    fn opaque_tokens_unique_in_practice() {
        let a = issue_opaque_token(48);
        let b = issue_opaque_token(48);
        assert_ne!(a, b);
    }

    #[test]
    fn link_code_is_six_digits() {
        for _ in 0..50 {
            let c = issue_link_code();
            assert!(is_well_formed_link_code(&c));
        }
    }

    #[test]
    fn well_formed_link_code_rejects_bad_input() {
        assert!(!is_well_formed_link_code(""));
        assert!(!is_well_formed_link_code("12345"));
        assert!(!is_well_formed_link_code("abcdef"));
        assert!(is_well_formed_link_code("000000"));
    }

    // ── JWT ────────────────────────────────────────────────────────────────

    fn now() -> DateTime<Utc> {
        Utc.with_ymd_and_hms(2026, 5, 5, 12, 0, 0).unwrap()
    }

    #[test]
    fn jwt_sign_and_verify_roundtrip() {
        let secret = b"test-secret".to_vec();
        let token = issue_jwt(&secret, 42, Duration::from_secs(3600), now()).unwrap();
        let claims = verify_jwt(&secret, &token, now()).unwrap();
        assert_eq!(claims.sub, 42);
    }

    #[test]
    fn jwt_rejects_tampered_signature() {
        let secret = b"test-secret".to_vec();
        let mut token = issue_jwt(&secret, 42, Duration::from_secs(3600), now()).unwrap();
        // flip the last char
        let last = token.pop().unwrap();
        let flipped = if last == 'A' { 'B' } else { 'A' };
        token.push(flipped);
        let r = verify_jwt(&secret, &token, now());
        assert!(r.is_err());
    }

    #[test]
    fn jwt_rejects_wrong_secret() {
        let token = issue_jwt(b"a", 1, Duration::from_secs(60), now()).unwrap();
        let r = verify_jwt(b"b", &token, now());
        assert!(matches!(r, Err(AuthError::InvalidToken)));
    }

    #[test]
    fn jwt_expires() {
        let secret = b"x".to_vec();
        let token = issue_jwt(&secret, 1, Duration::from_secs(60), now()).unwrap();
        let later = now() + ChronoDuration::seconds(120);
        assert!(matches!(
            verify_jwt(&secret, &token, later),
            Err(AuthError::Expired)
        ));
    }

    #[test]
    fn jwt_malformed_token() {
        assert!(matches!(
            verify_jwt(b"x", "garbage", now()),
            Err(AuthError::InvalidToken)
        ));
    }

    // ── PlainHasher ────────────────────────────────────────────────────────

    #[test]
    fn plain_hasher_verifies_match() {
        let h = PlainHasher;
        let encoded = h.hash("hello").unwrap();
        h.verify(&encoded, "hello").unwrap();
        assert!(h.verify(&encoded, "wrong").is_err());
    }

    // ── AuthService stub-store flow ────────────────────────────────────────

    #[derive(Default)]
    struct InMemStore {
        users: Mutex<Vec<User>>,
        next_id: Mutex<i64>,
    }
    impl UserStore for InMemStore {
        fn create_user(&self, mut u: User) -> Result<i64> {
            let mut id = self.next_id.lock();
            *id += 1;
            u.id = *id;
            self.users.lock().push(u);
            Ok(*id)
        }
        fn find_by_username(&self, name: &str) -> Result<Option<User>> {
            Ok(self.users.lock().iter().find(|u| u.username == name).cloned())
        }
        fn find_by_id(&self, id: i64) -> Result<Option<User>> {
            Ok(self.users.lock().iter().find(|u| u.id == id).cloned())
        }
        fn find_by_token(&self, t: &str) -> Result<Option<User>> {
            Ok(self
                .users
                .lock()
                .iter()
                .find(|u| u.api_token.as_deref() == Some(t))
                .cloned())
        }
        fn update_token(&self, id: i64, token: Option<String>) -> Result<()> {
            let mut us = self.users.lock();
            if let Some(u) = us.iter_mut().find(|u| u.id == id) {
                u.api_token = token;
            }
            Ok(())
        }
        fn touch_login(&self, id: i64, when: DateTime<Utc>) -> Result<()> {
            let mut us = self.users.lock();
            if let Some(u) = us.iter_mut().find(|u| u.id == id) {
                u.last_login_at = Some(when);
            }
            Ok(())
        }
        fn set_disabled(&self, id: i64, disabled: bool) -> Result<()> {
            let mut us = self.users.lock();
            if let Some(u) = us.iter_mut().find(|u| u.id == id) {
                u.disabled = disabled;
            }
            Ok(())
        }
    }

    #[test]
    fn create_user_persists_with_hashed_password() {
        let store = InMemStore::default();
        let h = PlainHasher;
        let clk = FixedClock(now());
        let svc = AuthService::new(&store, &h, &clk, b"s".to_vec());
        let id = svc
            .create_user("alice", "passw0rd", Role::User, None)
            .unwrap();
        assert_eq!(id, 1);
        let u = store.find_by_username("alice").unwrap().unwrap();
        assert_eq!(u.password_hash, "plain$passw0rd");
        assert_eq!(u.created_at, now());
    }

    #[test]
    fn verify_password_happy_path_touches_login() {
        let store = InMemStore::default();
        let h = PlainHasher;
        let clk = FixedClock(now());
        let svc = AuthService::new(&store, &h, &clk, b"s".to_vec());
        svc.create_user("alice", "p", Role::User, None).unwrap();
        let user = svc.verify_password("alice", "p").unwrap();
        assert_eq!(user.username, "alice");
        let stored = store.find_by_id(user.id).unwrap().unwrap();
        assert_eq!(stored.last_login_at, Some(now()));
    }

    #[test]
    fn verify_password_wrong_password_errors() {
        let store = InMemStore::default();
        let h = PlainHasher;
        let clk = FixedClock(now());
        let svc = AuthService::new(&store, &h, &clk, b"s".to_vec());
        svc.create_user("alice", "p", Role::User, None).unwrap();
        let r = svc.verify_password("alice", "wrong");
        assert!(matches!(r, Err(AuthError::InvalidPassword)));
    }

    #[test]
    fn verify_password_disabled_user_errors() {
        let store = InMemStore::default();
        let h = PlainHasher;
        let clk = FixedClock(now());
        let svc = AuthService::new(&store, &h, &clk, b"s".to_vec());
        let id = svc
            .create_user("alice", "p", Role::User, None)
            .unwrap();
        store.set_disabled(id, true).unwrap();
        let r = svc.verify_password("alice", "p");
        assert!(matches!(r, Err(AuthError::Disabled)));
    }

    #[test]
    fn verify_password_unknown_user_errors() {
        let store = InMemStore::default();
        let h = PlainHasher;
        let clk = FixedClock(now());
        let svc = AuthService::new(&store, &h, &clk, b"s".to_vec());
        let r = svc.verify_password("ghost", "p");
        assert!(matches!(r, Err(AuthError::UserNotFound(_))));
    }

    #[test]
    fn api_token_issue_and_lookup() {
        let store = InMemStore::default();
        let h = PlainHasher;
        let clk = FixedClock(now());
        let svc = AuthService::new(&store, &h, &clk, b"s".to_vec());
        let id = svc
            .create_user("alice", "p", Role::User, None)
            .unwrap();
        let token = svc.issue_api_token(id).unwrap();
        let user = svc.user_for_token(&token).unwrap();
        assert_eq!(user.id, id);
    }

    #[test]
    fn api_token_revoke_invalidates() {
        let store = InMemStore::default();
        let h = PlainHasher;
        let clk = FixedClock(now());
        let svc = AuthService::new(&store, &h, &clk, b"s".to_vec());
        let id = svc
            .create_user("alice", "p", Role::User, None)
            .unwrap();
        let token = svc.issue_api_token(id).unwrap();
        svc.revoke_api_token(id).unwrap();
        assert!(matches!(
            svc.user_for_token(&token),
            Err(AuthError::InvalidToken)
        ));
    }

    #[test]
    fn jwt_full_round_trip_via_service() {
        let store = InMemStore::default();
        let h = PlainHasher;
        let clk = FixedClock(now());
        let svc = AuthService::new(&store, &h, &clk, b"s".to_vec());
        let id = svc
            .create_user("alice", "p", Role::User, None)
            .unwrap();
        let token = svc.issue_jwt(id, Duration::from_secs(3600)).unwrap();
        let user = svc.verify_jwt(&token).unwrap();
        assert_eq!(user.id, id);
    }
}
