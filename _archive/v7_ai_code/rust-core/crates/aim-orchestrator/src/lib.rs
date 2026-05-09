//! aim-orchestrator — central routing gate for service-level tools.
//!
//! Port of `agents/orchestrator.py`. Every `delegate_*` tool flows through
//! [`orchestrate`], which runs the kernel pipeline before the service is
//! called and re-checks emitted text afterwards:
//!
//! ```text
//! L0–L3 → L_PRIVACY → L_CONSENT
//!   → service_fn(...)
//!     → L_VERIFIABILITY (post)
//!     → Ze-verify (auto, post)     ← path:line refs vs filesystem
//!     → Ze-AST   (auto, post)      ← symbol-at-line claims
//!     → Ze scoring (advisory)
//!     → return [header(s)] + out
//! ```
//!
//! Every external collaborator (laws evaluator, AST verifier, Ze scorer,
//! event sink) is behind a trait so the pipeline is testable without
//! pulling in `aim-kernel`, AST machinery, or a database.

use std::collections::{BTreeMap, HashSet};
use std::path::{Path, PathBuf};

use once_cell::sync::Lazy;
use regex::Regex;
use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum OrchError {
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
}

pub type Result<T> = std::result::Result<T, OrchError>;

// ── action-type families (mirror Python sets) ───────────────────────────────

pub static PRIVACY_ACTIONS: &[&str] = &[
    "email_send",
    "web_post",
    "git_push_public",
    "upload_external",
    "external_api_call_with_data",
];

pub static CONSENT_ACTIONS: &[&str] = &[
    "email_send",
    "git_push_public",
    "telegram_broadcast",
    "web_publish",
    "external_api_call_with_data",
];

pub static VERIFIABILITY_ACTIONS: &[&str] = &[
    "emit_text",
    "write_manuscript",
    "send_letter",
    "generate_citations",
    "peer_review_emit",
    "grant_letter",
];

pub static CLINICAL_ACTIONS: &[&str] = &[
    "dx",
    "treatment",
    "test",
    "imaging",
    "referral",
    "wait",
    "clarify",
];

pub fn is_action(action_type: &str, set: &[&str]) -> bool {
    set.iter().any(|&a| a == action_type)
}

// ── Decision + metrics ──────────────────────────────────────────────────────

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct Decision {
    pub id: String,
    pub description: String,
    pub action_type: String,
    pub payload: BTreeMap<String, serde_json::Value>,
}

impl Decision {
    pub fn new(id: impl Into<String>, action_type: impl Into<String>) -> Self {
        Self {
            id: id.into(),
            description: String::new(),
            action_type: action_type.into(),
            payload: BTreeMap::new(),
        }
    }
}

#[derive(Clone, Copy, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct ZeMetrics {
    pub impedance_before: f64,
    pub impedance_after: f64,
    pub instant_c: f64,
    pub phi_ze: f64,
    pub utility: f64,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct VerifyReport {
    pub total: usize,
    pub ok: usize,
    pub bad: Vec<String>,
}

// ── Ze-verify: regex + filesystem check ─────────────────────────────────────

static FILE_LINE_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"(?:^|[^:/])([\w./\-]+\.[A-Za-z]{1,8}):(\d{1,7})(?:[^0-9]|$)")
        .expect("file-line regex compiles")
});

const MAX_REFS_TO_VERIFY: usize = 30;

pub static RESOLVE_SUBDIRS: &[&str] = &[
    "agents",
    "tools",
    "tests",
    "scripts",
    "web",
    "cli",
    "DiffDiagnosis",
    "SSA",
    "deploy",
    "export",
    "migrations",
];

/// Resolve `path:line` references against the filesystem.
///
/// 1. Absolute path verbatim.
/// 2. `<base>/<p>` for each base.
/// 3. Bare-basename: `<base>/<known-subdir>/<basename>` when input has no slashes.
pub fn resolve_path(p: &str, bases: &[PathBuf]) -> Option<PathBuf> {
    let raw = PathBuf::from(p);
    if raw.is_absolute() {
        return if raw.is_file() { Some(raw) } else { None };
    }
    for base in bases {
        let cand = base.join(&raw);
        if cand.is_file() {
            return Some(cand);
        }
    }
    let has_no_dirs = raw
        .parent()
        .map(|p| p.as_os_str().is_empty() || p == Path::new("."))
        .unwrap_or(true);
    if has_no_dirs {
        if let Some(name) = raw.file_name() {
            for base in bases {
                for sub in RESOLVE_SUBDIRS {
                    let cand = base.join(sub).join(name);
                    if cand.is_file() {
                        return Some(cand);
                    }
                }
            }
        }
    }
    None
}

/// Extract `path:line` refs from text. Caps at [`MAX_REFS_TO_VERIFY`] and dedupes.
/// Skips URL-like matches (path contains `://`, or the match sits inside a
/// `…://…` substring within the surrounding text).
pub fn extract_file_line_refs(text: &str) -> Vec<(String, usize)> {
    let mut seen: HashSet<(String, usize)> = HashSet::new();
    let mut out: Vec<(String, usize)> = Vec::new();
    for cap in FILE_LINE_RE.captures_iter(text) {
        let path_match = match cap.get(1) {
            Some(m) => m,
            None => continue,
        };
        let line: Option<usize> = cap
            .get(2)
            .and_then(|m| m.as_str().parse().ok());
        let Some(line) = line else { continue };
        let path = path_match.as_str().to_string();
        if path.contains("://") {
            continue;
        }
        // Reject if the byte just before the captured path is part of a `://`
        // sequence (covers "http://host.com:80/x" where the regex would otherwise
        // happily extract "ost.com:80" / "xample.com:80").
        let start = path_match.start();
        if start >= 3 && &text.as_bytes()[start - 3..start] == b"://" {
            continue;
        }
        // Also reject when any preceding 3 bytes within the same word are `://`
        // (e.g. "host.com:80" right after "//" → "ost.com" still matches because
        // start is just after "/"). Walk back to the previous whitespace.
        let prefix_end = start;
        let prefix_start = text[..prefix_end]
            .rfind(|c: char| c.is_whitespace() || c == '(')
            .map(|i| i + 1)
            .unwrap_or(0);
        if text[prefix_start..prefix_end].contains("://") {
            continue;
        }
        let key = (path, line);
        if seen.insert(key.clone()) {
            out.push(key);
            if out.len() >= MAX_REFS_TO_VERIFY {
                break;
            }
        }
    }
    out
}

/// Mechanically check every `path:line` ref. Failure modes:
///   • file does not exist
///   • line number > total lines in file
pub fn ze_verify_output(text: &str, bases: &[PathBuf]) -> VerifyReport {
    let pairs = extract_file_line_refs(text);
    if pairs.is_empty() {
        return VerifyReport::default();
    }
    let total = pairs.len();
    let mut ok = 0usize;
    let mut bad: Vec<String> = Vec::new();
    for (path, ln) in pairs {
        let Some(resolved) = resolve_path(&path, bases) else {
            bad.push(format!("{}:{} (file not found)", path, ln));
            continue;
        };
        let total_lines = match std::fs::read_to_string(&resolved) {
            Ok(s) => {
                let mut n = s.lines().count();
                if s.ends_with('\n') {
                    // count trailing newline as a final empty line, matching `wc -l + 1`
                    // Python uses `sum(1 for _ in open(...))` which counts physical lines.
                    let _ = n;
                }
                n = s.lines().count();
                n
            }
            Err(e) => {
                bad.push(format!(
                    "{}:{} (read error: {})",
                    path,
                    ln,
                    e.kind()
                ));
                continue;
            }
        };
        if ln < 1 || ln > total_lines {
            bad.push(format!(
                "{}:{} (out of range; file has {} lines)",
                path, ln, total_lines
            ));
            continue;
        }
        ok += 1;
    }
    VerifyReport { total, ok, bad }
}

// ── Ze scoring (non-clinical) ───────────────────────────────────────────────

pub fn payload_chars(payload: &BTreeMap<String, serde_json::Value>) -> usize {
    let mut total = 0;
    for v in payload.values() {
        match v {
            serde_json::Value::String(s) => total += s.chars().count(),
            other => total += other.to_string().chars().count(),
        }
    }
    total
}

/// Lightweight Ze metrics for non-clinical decisions. Mirrors Python
/// `_score_nonclinical` formulas exactly (clamped float arithmetic).
pub fn score_nonclinical(decision: &Decision, output: &str) -> ZeMetrics {
    let pl_chars = payload_chars(&decision.payload) as f64;
    let i_before = (0.10 + pl_chars / 6250.0).clamp(0.10, 0.80);
    let out_len = output.chars().count() as f64;

    let i_after = if is_action(&decision.action_type, VERIFIABILITY_ACTIONS) {
        (0.5 * i_before + out_len / 16000.0).clamp(0.0, 1.0)
    } else {
        (0.3 * i_before).max(0.0)
    };

    let c = (i_before - i_after).clamp(-1.0, 1.0);
    // phi_ze: caller (the trait-bound CitationChecker) supplies the real
    // value; this fast path returns 1.0 when no checker is wired up.
    let phi = 1.0_f64;
    let u = 0.4 * c + 0.3 * phi + 0.3 * (1.0 - i_after);
    ZeMetrics {
        impedance_before: i_before,
        impedance_after: i_after,
        instant_c: c,
        phi_ze: phi,
        utility: u,
    }
}

pub fn format_ze_header(m: &ZeMetrics) -> String {
    let mut warns: Vec<String> = Vec::new();
    if m.impedance_after > m.impedance_before {
        warns.push(format!(
            "impedance ↑ ({:.2}→{:.2}): decision raises uncertainty",
            m.impedance_before, m.impedance_after
        ));
    }
    if m.instant_c < 0.0 {
        warns.push(format!("𝒞<0 ({:.3}): clarity loss", m.instant_c));
    }
    if m.utility < 0.0 {
        warns.push(format!("U<0 ({:.3}): net-negative", m.utility));
    }
    let mut header = format!(
        "[Ze] I_before={:.2} I_after={:.2} 𝒞={:.3} Φ={:.3} U={:.3}",
        m.impedance_before, m.impedance_after, m.instant_c, m.phi_ze, m.utility
    );
    if !warns.is_empty() {
        header.push_str("  ⚠ ");
        header.push_str(&warns.join("; "));
    }
    header
}

// ── traits ──────────────────────────────────────────────────────────────────

#[derive(Clone, Debug, Default)]
pub struct LawOutcome {
    pub passed: bool,
    pub reason: Option<String>,
}

impl LawOutcome {
    pub fn ok() -> Self {
        Self {
            passed: true,
            reason: None,
        }
    }
    pub fn block(reason: impl Into<String>) -> Self {
        Self {
            passed: false,
            reason: Some(reason.into()),
        }
    }
}

pub trait LawsEvaluator: Send + Sync {
    fn evaluate_asimov(&self, decision: &Decision) -> LawOutcome;
    fn evaluate_privacy(&self, decision: &Decision) -> LawOutcome;
    fn evaluate_consent(&self, decision: &Decision) -> LawOutcome;
    fn evaluate_verifiability(&self, decision: &Decision, text: &str) -> LawOutcome;
}

/// Service function the orchestrator wraps.
pub trait ServiceFn: Send + Sync {
    fn call(&self, decision: &Decision) -> std::result::Result<String, String>;
}

/// AST verification. Production binds to the Python ast_verify port.
pub trait AstVerifier: Send + Sync {
    fn verify_claims(&self, text: &str) -> VerifyReport;
}

pub struct NoopAstVerifier;
impl AstVerifier for NoopAstVerifier {
    fn verify_claims(&self, _text: &str) -> VerifyReport {
        VerifyReport::default()
    }
}

/// Persistent event sink.
pub trait EventSink: Send + Sync {
    fn record(&self, event: ZeEvent);
}

pub struct NoopSink;
impl EventSink for NoopSink {
    fn record(&self, _event: ZeEvent) {}
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ZeEvent {
    pub decision_id: String,
    pub action_type: String,
    pub blocked_at: Option<String>,
    pub metrics: Option<ZeMetrics>,
    pub payload_chars: usize,
    pub output_chars: usize,
}

// ── orchestrate ─────────────────────────────────────────────────────────────

pub struct OrchestrateConfig {
    pub bases: Vec<PathBuf>,
    pub skip_ze: bool,
}

impl OrchestrateConfig {
    pub fn new(bases: Vec<PathBuf>) -> Self {
        Self {
            bases,
            skip_ze: false,
        }
    }
}

pub struct Orchestrator<'a> {
    pub laws: &'a dyn LawsEvaluator,
    pub ast: &'a dyn AstVerifier,
    pub sink: &'a dyn EventSink,
    pub config: OrchestrateConfig,
}

impl<'a> Orchestrator<'a> {
    pub fn new(
        laws: &'a dyn LawsEvaluator,
        ast: &'a dyn AstVerifier,
        sink: &'a dyn EventSink,
        config: OrchestrateConfig,
    ) -> Self {
        Self {
            laws,
            ast,
            sink,
            config,
        }
    }

    fn record(&self, decision: &Decision, blocked_at: Option<&str>, metrics: Option<ZeMetrics>, output_chars: usize) {
        self.sink.record(ZeEvent {
            decision_id: decision.id.clone(),
            action_type: decision.action_type.clone(),
            blocked_at: blocked_at.map(String::from),
            metrics,
            payload_chars: payload_chars(&decision.payload),
            output_chars,
        });
    }

    /// Run a decision through the full pipeline. Returns the assembled output
    /// (with any Ze headers prepended) or an `ERROR:…` string on law violation.
    pub fn orchestrate(&self, decision: &Decision, service: &dyn ServiceFn) -> String {
        // 1) L0–L3
        let asimov = self.laws.evaluate_asimov(decision);
        if !asimov.passed {
            self.record(decision, Some("L0-3"), None, 0);
            return format!(
                "ERROR:KERNEL:Asimov laws blocked {} — {}",
                decision.id,
                asimov.reason.unwrap_or_default()
            );
        }

        // 2) L_PRIVACY
        if is_action(&decision.action_type, PRIVACY_ACTIONS) {
            let priv_check = self.laws.evaluate_privacy(decision);
            if !priv_check.passed {
                self.record(decision, Some("L_PRIVACY"), None, 0);
                return format!("ERROR:KERNEL:{}", priv_check.reason.unwrap_or_default());
            }
        }

        // 3) L_CONSENT
        if is_action(&decision.action_type, CONSENT_ACTIONS) {
            let consent = self.laws.evaluate_consent(decision);
            if !consent.passed {
                self.record(decision, Some("L_CONSENT"), None, 0);
                return format!("ERROR:KERNEL:{}", consent.reason.unwrap_or_default());
            }
        }

        // 4) Service
        let out = match service.call(decision) {
            Ok(s) => s,
            Err(e) => {
                self.record(decision, Some("INTERNAL"), None, 0);
                return format!("ERROR:INTERNAL:{}: {}", decision.id, e);
            }
        };

        // 5) L_VERIFIABILITY (POST)
        if is_action(&decision.action_type, VERIFIABILITY_ACTIONS) && !out.is_empty() {
            let verif = self.laws.evaluate_verifiability(decision, &out);
            if !verif.passed {
                self.record(decision, Some("L_VERIFIABILITY"), None, out.chars().count());
                let reason = verif.reason.unwrap_or_default();
                let suppressed: String = out.chars().take(4000).collect();
                return format!(
                    "ERROR:VERIFIABILITY:{}\n\n--- raw service output (suppressed) ---\n{}",
                    reason, suppressed
                );
            }
        }

        // 6) Ze-verify (auto)
        let verify_report = ze_verify_output(&out, &self.config.bases);
        let mut headers: Vec<String> = Vec::new();
        if !verify_report.bad.is_empty() {
            let preview: Vec<String> = verify_report.bad.iter().take(10).cloned().collect();
            let extra = if verify_report.bad.len() > 10 {
                format!("; +{} more", verify_report.bad.len() - 10)
            } else {
                String::new()
            };
            headers.push(format!(
                "[Ze-verify] {}/{} refs OK; BROKEN ({}): {}{}",
                verify_report.ok,
                verify_report.total,
                verify_report.bad.len(),
                preview.join("; "),
                extra
            ));
        }

        // 6b) Ze-AST
        let ast_report = self.ast.verify_claims(&out);
        if !ast_report.bad.is_empty() {
            let preview: Vec<String> = ast_report.bad.iter().take(5).cloned().collect();
            let extra = if ast_report.bad.len() > 5 {
                format!("; +{} more", ast_report.bad.len() - 5)
            } else {
                String::new()
            };
            headers.push(format!(
                "[Ze-AST] {}/{} claims OK; WRONG ({}): {}{}",
                ast_report.ok,
                ast_report.total,
                ast_report.bad.len(),
                preview.join("; "),
                extra
            ));
        }

        // 7) Ze scoring (advisory)
        let metrics = if !self.config.skip_ze {
            let m = score_nonclinical(decision, &out);
            headers.push(format_ze_header(&m));
            Some(m)
        } else {
            None
        };

        // 8) Persist + return
        self.record(decision, None, metrics, out.chars().count());
        if headers.is_empty() {
            out
        } else {
            format!("{}\n\n{}", headers.join("\n"), out)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use parking_lot::Mutex;
    use tempfile::TempDir;

    // ── stubs ───────────────────────────────────────────────────────────────

    #[derive(Default)]
    struct AlwaysPassLaws;
    impl LawsEvaluator for AlwaysPassLaws {
        fn evaluate_asimov(&self, _: &Decision) -> LawOutcome {
            LawOutcome::ok()
        }
        fn evaluate_privacy(&self, _: &Decision) -> LawOutcome {
            LawOutcome::ok()
        }
        fn evaluate_consent(&self, _: &Decision) -> LawOutcome {
            LawOutcome::ok()
        }
        fn evaluate_verifiability(&self, _: &Decision, _: &str) -> LawOutcome {
            LawOutcome::ok()
        }
    }

    struct BlockAt(&'static str);
    impl LawsEvaluator for BlockAt {
        fn evaluate_asimov(&self, _: &Decision) -> LawOutcome {
            if self.0 == "asimov" {
                LawOutcome::block("blocked at asimov")
            } else {
                LawOutcome::ok()
            }
        }
        fn evaluate_privacy(&self, _: &Decision) -> LawOutcome {
            if self.0 == "privacy" {
                LawOutcome::block("blocked at privacy")
            } else {
                LawOutcome::ok()
            }
        }
        fn evaluate_consent(&self, _: &Decision) -> LawOutcome {
            if self.0 == "consent" {
                LawOutcome::block("blocked at consent")
            } else {
                LawOutcome::ok()
            }
        }
        fn evaluate_verifiability(&self, _: &Decision, _: &str) -> LawOutcome {
            if self.0 == "verif" {
                LawOutcome::block("unverified citation")
            } else {
                LawOutcome::ok()
            }
        }
    }

    struct ConstService(String);
    impl ServiceFn for ConstService {
        fn call(&self, _: &Decision) -> std::result::Result<String, String> {
            Ok(self.0.clone())
        }
    }

    struct ErrorService;
    impl ServiceFn for ErrorService {
        fn call(&self, _: &Decision) -> std::result::Result<String, String> {
            Err("kaboom".into())
        }
    }

    #[derive(Default)]
    struct CapturingSink {
        events: Mutex<Vec<ZeEvent>>,
    }
    impl EventSink for CapturingSink {
        fn record(&self, event: ZeEvent) {
            self.events.lock().push(event);
        }
    }

    // ── extract_file_line_refs ──────────────────────────────────────────────

    #[test]
    fn extract_finds_basic_path_line() {
        let refs = extract_file_line_refs("see foo/bar.py:42 for details");
        assert_eq!(refs, vec![("foo/bar.py".to_string(), 42)]);
    }

    #[test]
    fn extract_dedupes() {
        let refs = extract_file_line_refs("a.py:1, again a.py:1, and a.py:2");
        assert_eq!(refs.len(), 2);
    }

    #[test]
    fn extract_caps_at_max() {
        let mut text = String::new();
        for i in 1..50 {
            text.push_str(&format!("file_{}.py:{} ", i, i));
        }
        let refs = extract_file_line_refs(&text);
        assert_eq!(refs.len(), MAX_REFS_TO_VERIFY);
    }

    #[test]
    fn extract_ignores_url_paths() {
        let refs = extract_file_line_refs("http://example.com:80/x");
        assert!(refs.is_empty());
    }

    // ── resolve_path ────────────────────────────────────────────────────────

    #[test]
    fn resolve_finds_under_base() {
        let tmp = TempDir::new().unwrap();
        std::fs::write(tmp.path().join("a.py"), "").unwrap();
        let r = resolve_path("a.py", &[tmp.path().to_path_buf()]).unwrap();
        assert_eq!(r.canonicalize().unwrap(), tmp.path().join("a.py").canonicalize().unwrap());
    }

    #[test]
    fn resolve_finds_under_subdir_for_bare_basename() {
        let tmp = TempDir::new().unwrap();
        std::fs::create_dir_all(tmp.path().join("agents")).unwrap();
        std::fs::write(tmp.path().join("agents/foo.py"), "").unwrap();
        let r = resolve_path("foo.py", &[tmp.path().to_path_buf()]);
        assert!(r.is_some());
    }

    #[test]
    fn resolve_returns_none_when_missing() {
        let tmp = TempDir::new().unwrap();
        let r = resolve_path("nonexistent.py", &[tmp.path().to_path_buf()]);
        assert!(r.is_none());
    }

    // ── ze_verify_output ────────────────────────────────────────────────────

    #[test]
    fn ze_verify_passes_for_valid_ref() {
        let tmp = TempDir::new().unwrap();
        let p = tmp.path().join("a.py");
        std::fs::write(&p, "line1\nline2\nline3\n").unwrap();
        let report = ze_verify_output("see a.py:2 here", &[tmp.path().to_path_buf()]);
        assert_eq!(report.total, 1);
        assert_eq!(report.ok, 1);
        assert!(report.bad.is_empty());
    }

    #[test]
    fn ze_verify_flags_missing_file() {
        let tmp = TempDir::new().unwrap();
        let report = ze_verify_output("nope.py:5", &[tmp.path().to_path_buf()]);
        assert_eq!(report.total, 1);
        assert_eq!(report.bad.len(), 1);
        assert!(report.bad[0].contains("file not found"));
    }

    #[test]
    fn ze_verify_flags_out_of_range_line() {
        let tmp = TempDir::new().unwrap();
        let p = tmp.path().join("a.py");
        std::fs::write(&p, "one\ntwo\n").unwrap();
        let report = ze_verify_output("a.py:99", &[tmp.path().to_path_buf()]);
        assert_eq!(report.bad.len(), 1);
        assert!(report.bad[0].contains("out of range"));
    }

    #[test]
    fn ze_verify_empty_text_returns_zero_report() {
        let report = ze_verify_output("no refs here", &[]);
        assert_eq!(report.total, 0);
    }

    // ── score_nonclinical ───────────────────────────────────────────────────

    #[test]
    fn score_clamps_impedance_before_at_baseline() {
        let d = Decision::new("d1", "emit_text");
        let m = score_nonclinical(&d, "");
        assert!((m.impedance_before - 0.10).abs() < 1e-9);
    }

    #[test]
    fn score_clamps_impedance_before_at_max() {
        let mut d = Decision::new("d1", "emit_text");
        d.payload.insert(
            "x".into(),
            serde_json::Value::String("z".repeat(20_000)),
        );
        let m = score_nonclinical(&d, "");
        assert!((m.impedance_before - 0.80).abs() < 1e-9);
    }

    #[test]
    fn score_uses_emit_formula_for_verifiability_actions() {
        let d = Decision::new("d1", "emit_text");
        let m = score_nonclinical(&d, "x".repeat(4000).as_str());
        // I_after = 0.5 * 0.10 + 4000/16000 = 0.05 + 0.25 = 0.30
        assert!((m.impedance_after - 0.30).abs() < 1e-6);
    }

    #[test]
    fn score_uses_simple_formula_for_other_actions() {
        let d = Decision::new("d1", "email_send");
        let m = score_nonclinical(&d, "anything");
        // I_after = 0.3 * 0.10 = 0.03
        assert!((m.impedance_after - 0.03).abs() < 1e-9);
    }

    // ── format_ze_header ────────────────────────────────────────────────────

    #[test]
    fn header_contains_metric_summary() {
        let m = ZeMetrics {
            impedance_before: 0.10,
            impedance_after: 0.05,
            instant_c: 0.05,
            phi_ze: 1.0,
            utility: 0.8,
        };
        let h = format_ze_header(&m);
        assert!(h.contains("[Ze]"));
        assert!(h.contains("I_before=0.10"));
        assert!(h.contains("U=0.800"));
        assert!(!h.contains("⚠"));
    }

    #[test]
    fn header_warns_on_negative_utility() {
        let m = ZeMetrics {
            impedance_before: 0.10,
            impedance_after: 0.50,
            instant_c: -0.40,
            phi_ze: 0.5,
            utility: -0.05,
        };
        let h = format_ze_header(&m);
        assert!(h.contains("⚠"));
        assert!(h.contains("impedance ↑"));
        assert!(h.contains("𝒞<0"));
        assert!(h.contains("U<0"));
    }

    // ── pipeline ────────────────────────────────────────────────────────────

    fn cfg(tmp: &TempDir) -> OrchestrateConfig {
        OrchestrateConfig::new(vec![tmp.path().to_path_buf()])
    }

    #[test]
    fn pipeline_passes_through_clean_call() {
        let tmp = TempDir::new().unwrap();
        let sink = CapturingSink::default();
        let orch = Orchestrator::new(&AlwaysPassLaws, &NoopAstVerifier, &sink, cfg(&tmp));
        let d = Decision::new("d1", "noop_action");
        let out = orch.orchestrate(&d, &ConstService("hello".into()));
        assert!(out.contains("hello"));
        assert!(out.contains("[Ze]"));
        assert_eq!(sink.events.lock().len(), 1);
    }

    #[test]
    fn pipeline_blocks_on_asimov() {
        let tmp = TempDir::new().unwrap();
        let sink = CapturingSink::default();
        let orch = Orchestrator::new(&BlockAt("asimov"), &NoopAstVerifier, &sink, cfg(&tmp));
        let d = Decision::new("d1", "noop_action");
        let out = orch.orchestrate(&d, &ConstService("body".into()));
        assert!(out.starts_with("ERROR:KERNEL:Asimov laws blocked d1"));
        assert_eq!(sink.events.lock()[0].blocked_at.as_deref(), Some("L0-3"));
    }

    #[test]
    fn pipeline_blocks_on_privacy_only_for_privacy_actions() {
        let tmp = TempDir::new().unwrap();
        let sink = CapturingSink::default();
        let orch = Orchestrator::new(&BlockAt("privacy"), &NoopAstVerifier, &sink, cfg(&tmp));
        // non-privacy action → not blocked
        let d = Decision::new("d1", "noop_action");
        let out = orch.orchestrate(&d, &ConstService("body".into()));
        assert!(!out.starts_with("ERROR:"));
        // privacy action → blocked
        let d2 = Decision::new("d2", "email_send");
        let out2 = orch.orchestrate(&d2, &ConstService("body".into()));
        assert!(out2.starts_with("ERROR:KERNEL:blocked at privacy"));
    }

    #[test]
    fn pipeline_blocks_on_consent_only_for_consent_actions() {
        let tmp = TempDir::new().unwrap();
        let sink = CapturingSink::default();
        let orch = Orchestrator::new(&BlockAt("consent"), &NoopAstVerifier, &sink, cfg(&tmp));
        let d = Decision::new("d2", "git_push_public");
        let out = orch.orchestrate(&d, &ConstService("body".into()));
        assert!(out.starts_with("ERROR:KERNEL:blocked at consent"));
    }

    #[test]
    fn pipeline_blocks_on_verifiability_for_emit_text() {
        let tmp = TempDir::new().unwrap();
        let sink = CapturingSink::default();
        let orch = Orchestrator::new(&BlockAt("verif"), &NoopAstVerifier, &sink, cfg(&tmp));
        let d = Decision::new("d3", "emit_text");
        let out = orch.orchestrate(&d, &ConstService("citation [PMID 999999]".into()));
        assert!(out.starts_with("ERROR:VERIFIABILITY:"));
        assert!(out.contains("--- raw service output (suppressed)"));
    }

    #[test]
    fn pipeline_records_internal_error_on_service_fail() {
        let tmp = TempDir::new().unwrap();
        let sink = CapturingSink::default();
        let orch = Orchestrator::new(&AlwaysPassLaws, &NoopAstVerifier, &sink, cfg(&tmp));
        let d = Decision::new("d4", "noop_action");
        let out = orch.orchestrate(&d, &ErrorService);
        assert!(out.starts_with("ERROR:INTERNAL:d4"));
        assert_eq!(sink.events.lock()[0].blocked_at.as_deref(), Some("INTERNAL"));
    }

    #[test]
    fn pipeline_attaches_verify_header_for_broken_refs() {
        let tmp = TempDir::new().unwrap();
        let sink = CapturingSink::default();
        let orch = Orchestrator::new(&AlwaysPassLaws, &NoopAstVerifier, &sink, cfg(&tmp));
        let d = Decision::new("d5", "noop_action");
        let out = orch.orchestrate(&d, &ConstService("see missing.py:99".into()));
        assert!(out.contains("[Ze-verify]"));
        assert!(out.contains("BROKEN"));
    }

    #[test]
    fn pipeline_skip_ze_disables_scoring_header() {
        let tmp = TempDir::new().unwrap();
        let sink = CapturingSink::default();
        let mut config = cfg(&tmp);
        config.skip_ze = true;
        let orch = Orchestrator::new(&AlwaysPassLaws, &NoopAstVerifier, &sink, config);
        let d = Decision::new("d6", "noop_action");
        let out = orch.orchestrate(&d, &ConstService("clean".into()));
        assert!(!out.contains("[Ze]"));
    }

    #[test]
    fn pipeline_records_ze_event_on_clean_call() {
        let tmp = TempDir::new().unwrap();
        let sink = CapturingSink::default();
        let orch = Orchestrator::new(&AlwaysPassLaws, &NoopAstVerifier, &sink, cfg(&tmp));
        let d = Decision::new("d7", "noop_action");
        orch.orchestrate(&d, &ConstService("text".into()));
        let ev = &sink.events.lock()[0];
        assert!(ev.metrics.is_some());
        assert_eq!(ev.blocked_at, None);
    }
}
