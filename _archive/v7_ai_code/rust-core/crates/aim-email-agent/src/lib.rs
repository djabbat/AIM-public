//! aim-email-agent — Gmail integration with kernel-enforced consent + privacy.
//!
//! Port of `agents/email_agent.py`. The Python original drives Google's
//! `googleapiclient` directly. In Rust we keep the actual transport behind
//! a [`GmailTransport`] trait so:
//!   • production binds to a thin `reqwest`-based REST client (or shells
//!     out to `python -m agents.email_agent` during the migration window),
//!   • tests bind to an in-memory stub that asserts no network is touched.
//!
//! Kernel gates from `aim-kernel` enforce:
//!   • `evaluate_l_privacy` on every draft/send body
//!   • `evaluate_l_consent` on every send (`user_confirmed=true` required)

use base64::Engine;
use serde::{Deserialize, Serialize};
use thiserror::Error;

use aim_kernel::{
    evaluate_l_consent, evaluate_l_privacy, Context as KCtx, Decision as KDecision,
};

#[derive(Debug, Error)]
pub enum EmailError {
    #[error("permission denied: {0}")]
    Permission(String),
    #[error("transport error: {0}")]
    Transport(String),
}

pub type Result<T> = std::result::Result<T, EmailError>;

// ── data ────────────────────────────────────────────────────────────────────

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct Message {
    pub to: String,
    pub subject: String,
    pub body: String,
    pub cc: Option<String>,
    pub bcc: Option<String>,
    pub thread_id: Option<String>,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct ThreadSummary {
    pub thread_id: String,
    pub n_messages: usize,
    pub subject: String,
    pub from: String,
    pub date: String,
    pub snippet: String,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct GmailRawMessage {
    /// base64url-encoded RFC-5322 envelope.
    pub raw: String,
    pub thread_id: Option<String>,
}

// ── transport trait ─────────────────────────────────────────────────────────

pub trait GmailTransport: Send + Sync {
    fn list_threads(&self, q: &str, n: usize) -> Result<Vec<ThreadSummary>>;
    fn get_thread(&self, thread_id: &str) -> Result<serde_json::Value>;
    fn list_labels(&self) -> Result<Vec<serde_json::Value>>;
    fn create_draft(&self, msg: &GmailRawMessage) -> Result<serde_json::Value>;
    fn send_message(&self, msg: &GmailRawMessage) -> Result<serde_json::Value>;
}

// ── helpers ─────────────────────────────────────────────────────────────────

/// Build an RFC-5322 envelope (text/plain, UTF-8) and base64url-encode it.
/// Mirrors Python's `EmailMessage` + `urlsafe_b64encode`. UTF-8 bodies are
/// kept as-is in the body section — Gmail tolerates non-ASCII content
/// because we declare `charset=UTF-8`.
pub fn build_raw_message(m: &Message) -> GmailRawMessage {
    let mut envelope = String::new();
    envelope.push_str(&format!("To: {}\r\n", m.to));
    envelope.push_str(&format!("Subject: {}\r\n", m.subject));
    if let Some(cc) = &m.cc {
        envelope.push_str(&format!("Cc: {}\r\n", cc));
    }
    if let Some(bcc) = &m.bcc {
        envelope.push_str(&format!("Bcc: {}\r\n", bcc));
    }
    envelope.push_str("MIME-Version: 1.0\r\n");
    envelope.push_str("Content-Type: text/plain; charset=UTF-8\r\n");
    envelope.push_str("Content-Transfer-Encoding: 8bit\r\n");
    envelope.push_str("\r\n");
    envelope.push_str(&m.body);

    let raw = base64::engine::general_purpose::URL_SAFE
        .encode(envelope.as_bytes());
    GmailRawMessage {
        raw,
        thread_id: m.thread_id.clone(),
    }
}

fn privacy_decision(action: &str, body: &str) -> KDecision {
    let mut d = KDecision::new("email", "email_send");
    d.description = action.into();
    d.payload = serde_json::json!({"body": body});
    d
}

/// Run kernel `evaluate_l_privacy` on a body. Returns `Err(Permission)` on
/// block, `Ok(())` on pass.
pub fn check_privacy(body: &str, action: &str) -> Result<()> {
    let d = privacy_decision(action, body);
    let ctx = KCtx::default();
    let (ok, reason) = evaluate_l_privacy(&d, &ctx);
    if !ok {
        Err(EmailError::Permission(reason))
    } else {
        Ok(())
    }
}

/// Run kernel `evaluate_l_consent` for an email send. Requires
/// `user_confirmed=true` in the kernel context.
pub fn check_consent(to: &str, subject: &str, body_len: usize, user_confirmed: bool) -> Result<()> {
    let mut d = KDecision::new("email", "email_send");
    d.description = "email_send".into();
    d.payload = serde_json::json!({
        "to": to,
        "subject": subject,
        "body_len": body_len,
    });
    let mut ctx = KCtx::default();
    ctx.user_confirmed = Some(user_confirmed);
    let (ok, reason) = evaluate_l_consent(&d, &ctx);
    if !ok {
        Err(EmailError::Permission(reason))
    } else {
        Ok(())
    }
}

// ── EmailAgent ──────────────────────────────────────────────────────────────

pub struct EmailAgent<'a> {
    pub transport: &'a dyn GmailTransport,
}

impl<'a> EmailAgent<'a> {
    pub fn new(transport: &'a dyn GmailTransport) -> Self {
        Self { transport }
    }

    pub fn list_threads(&self, q: &str, n: usize) -> Result<Vec<ThreadSummary>> {
        self.transport.list_threads(q, n)
    }

    pub fn search(&self, query: &str, n: usize) -> Result<Vec<ThreadSummary>> {
        self.list_threads(query, n)
    }

    pub fn get_thread(&self, thread_id: &str) -> Result<serde_json::Value> {
        self.transport.get_thread(thread_id)
    }

    pub fn list_labels(&self) -> Result<Vec<serde_json::Value>> {
        self.transport.list_labels()
    }

    /// Create a draft — privacy-checked but never sent.
    pub fn draft(&self, msg: &Message) -> Result<serde_json::Value> {
        check_privacy(&msg.body, "email_draft")?;
        let raw = build_raw_message(msg);
        self.transport.create_draft(&raw)
    }

    /// Send an email — requires `user_confirmed=true` and passes privacy check.
    pub fn send(&self, msg: &Message, user_confirmed: bool) -> Result<serde_json::Value> {
        check_consent(&msg.to, &msg.subject, msg.body.len(), user_confirmed)?;
        check_privacy(&msg.body, "email_send")?;
        let raw = build_raw_message(msg);
        self.transport.send_message(&raw)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use parking_lot::Mutex;

    // ── stub transport ──────────────────────────────────────────────────────

    #[derive(Default)]
    struct StubTransport {
        sent: Mutex<Vec<GmailRawMessage>>,
        drafts: Mutex<Vec<GmailRawMessage>>,
        threads: Mutex<Vec<ThreadSummary>>,
    }
    impl GmailTransport for StubTransport {
        fn list_threads(&self, _q: &str, _n: usize) -> Result<Vec<ThreadSummary>> {
            Ok(self.threads.lock().clone())
        }
        fn get_thread(&self, thread_id: &str) -> Result<serde_json::Value> {
            Ok(serde_json::json!({"id": thread_id}))
        }
        fn list_labels(&self) -> Result<Vec<serde_json::Value>> {
            Ok(vec![serde_json::json!({"id": "INBOX"})])
        }
        fn create_draft(&self, msg: &GmailRawMessage) -> Result<serde_json::Value> {
            self.drafts.lock().push(msg.clone());
            Ok(serde_json::json!({"id": "draft-1"}))
        }
        fn send_message(&self, msg: &GmailRawMessage) -> Result<serde_json::Value> {
            self.sent.lock().push(msg.clone());
            Ok(serde_json::json!({"id": "sent-1"}))
        }
    }

    fn ok_message() -> Message {
        Message {
            to: "alice@example.com".into(),
            subject: "Hello".into(),
            body: "Plain body, no PII.".into(),
            cc: None,
            bcc: None,
            thread_id: None,
        }
    }

    // ── build_raw_message ───────────────────────────────────────────────────

    #[test]
    fn raw_message_round_trip_decode() {
        let m = Message {
            to: "alice@example.com".into(),
            subject: "Subj".into(),
            body: "Hello world".into(),
            cc: Some("cc@example.com".into()),
            bcc: None,
            thread_id: Some("t1".into()),
        };
        let raw = build_raw_message(&m);
        assert_eq!(raw.thread_id.as_deref(), Some("t1"));
        let bytes = base64::engine::general_purpose::URL_SAFE
            .decode(&raw.raw)
            .unwrap();
        let env = String::from_utf8(bytes).unwrap();
        assert!(env.contains("To: alice@example.com"));
        assert!(env.contains("Subject: Subj"));
        assert!(env.contains("Cc: cc@example.com"));
        assert!(!env.contains("Bcc:"));
        assert!(env.contains("\r\n\r\nHello world"));
    }

    #[test]
    fn raw_message_omits_optional_headers_when_none() {
        let m = ok_message();
        let raw = build_raw_message(&m);
        let env = String::from_utf8(
            base64::engine::general_purpose::URL_SAFE
                .decode(&raw.raw)
                .unwrap(),
        )
        .unwrap();
        assert!(!env.contains("Cc:"));
        assert!(!env.contains("Bcc:"));
    }

    #[test]
    fn raw_message_preserves_unicode_body() {
        let mut m = ok_message();
        m.body = "Привет мир 🇬🇪".into();
        let raw = build_raw_message(&m);
        let bytes = base64::engine::general_purpose::URL_SAFE
            .decode(&raw.raw)
            .unwrap();
        let env = String::from_utf8(bytes).unwrap();
        assert!(env.contains("Привет"));
        assert!(env.contains("Content-Type: text/plain; charset=UTF-8"));
    }

    // ── check_privacy / check_consent ───────────────────────────────────────

    #[test]
    fn check_privacy_passes_clean_body() {
        check_privacy("Hello world.", "email_draft").unwrap();
    }

    #[test]
    fn check_privacy_blocks_patients_path() {
        let err = check_privacy("see Patients/Doe_John", "email_send").unwrap_err();
        assert!(matches!(err, EmailError::Permission(_)));
    }

    #[test]
    fn check_privacy_blocks_phone_pattern() {
        let err = check_privacy("call +995 555 1234567", "email_send").unwrap_err();
        assert!(matches!(err, EmailError::Permission(_)));
    }

    #[test]
    fn check_consent_blocks_when_unconfirmed() {
        let err = check_consent("a@b.com", "subj", 100, false).unwrap_err();
        if let EmailError::Permission(s) = err {
            assert!(s.contains("L_CONSENT"));
        } else {
            panic!();
        }
    }

    #[test]
    fn check_consent_passes_when_confirmed() {
        check_consent("a@b.com", "subj", 100, true).unwrap();
    }

    // ── EmailAgent.draft ────────────────────────────────────────────────────

    #[test]
    fn draft_creates_message_via_transport_after_privacy_check() {
        let t = StubTransport::default();
        let agent = EmailAgent::new(&t);
        let r = agent.draft(&ok_message()).unwrap();
        assert_eq!(r.get("id").and_then(|v| v.as_str()), Some("draft-1"));
        assert_eq!(t.drafts.lock().len(), 1);
        assert!(t.sent.lock().is_empty());
    }

    #[test]
    fn draft_blocks_patient_path_in_body() {
        let t = StubTransport::default();
        let agent = EmailAgent::new(&t);
        let mut m = ok_message();
        m.body = "case at Patients/Smith_John/notes.md".into();
        let err = agent.draft(&m).unwrap_err();
        assert!(matches!(err, EmailError::Permission(_)));
        assert!(t.drafts.lock().is_empty());
    }

    // ── EmailAgent.send ─────────────────────────────────────────────────────

    #[test]
    fn send_blocks_unconfirmed() {
        let t = StubTransport::default();
        let agent = EmailAgent::new(&t);
        let err = agent.send(&ok_message(), false).unwrap_err();
        assert!(matches!(err, EmailError::Permission(_)));
        assert!(t.sent.lock().is_empty());
    }

    #[test]
    fn send_blocks_pii_even_when_confirmed() {
        let t = StubTransport::default();
        let agent = EmailAgent::new(&t);
        let mut m = ok_message();
        m.body = "phone +995 555 1234567".into();
        let err = agent.send(&m, true).unwrap_err();
        assert!(matches!(err, EmailError::Permission(_)));
        assert!(t.sent.lock().is_empty());
    }

    #[test]
    fn send_succeeds_when_confirmed_and_clean() {
        let t = StubTransport::default();
        let agent = EmailAgent::new(&t);
        let r = agent.send(&ok_message(), true).unwrap();
        assert_eq!(r.get("id").and_then(|v| v.as_str()), Some("sent-1"));
        assert_eq!(t.sent.lock().len(), 1);
    }

    // ── read methods ────────────────────────────────────────────────────────

    #[test]
    fn search_delegates_to_list_threads() {
        let t = StubTransport::default();
        *t.threads.lock() = vec![ThreadSummary {
            thread_id: "t1".into(),
            n_messages: 3,
            subject: "Hi".into(),
            ..Default::default()
        }];
        let agent = EmailAgent::new(&t);
        let r = agent.search("from:alice", 5).unwrap();
        assert_eq!(r.len(), 1);
        assert_eq!(r[0].subject, "Hi");
    }

    #[test]
    fn get_thread_returns_payload() {
        let t = StubTransport::default();
        let agent = EmailAgent::new(&t);
        let r = agent.get_thread("t-42").unwrap();
        assert_eq!(r.get("id").and_then(|v| v.as_str()), Some("t-42"));
    }

    #[test]
    fn list_labels_returns_labels() {
        let t = StubTransport::default();
        let agent = EmailAgent::new(&t);
        let r = agent.list_labels().unwrap();
        assert_eq!(r.len(), 1);
    }
}
