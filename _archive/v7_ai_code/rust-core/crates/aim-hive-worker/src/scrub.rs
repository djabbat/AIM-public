//! L_PRIVACY scrubber. Recursively walks the payload; on a PII match
//! either rejects (returns [`ScrubError`]) or redacts (rewrites the
//! match in-place), depending on the pattern's [`Action`].
//!
//! Hardened 2026-05-07 audit:
//! - `name_pair` switched from Reject → Redact (Title-Case bigrams like
//!   "Linux Kernel" / "User Activity" are too common for hard-reject).
//! - Added IPv4, ISO date, 9-12 digit IDs (SSN/INN/passport-shaped).
//!
//! Patterns are aligned with `AI/ai/hive_telemetry.py::_PII_PATTERNS`.

use once_cell::sync::Lazy;
use regex::Regex;
use serde_json::Value;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum ScrubError {
    #[error("PII pattern '{pattern}' matched in {sample}")]
    PiiMatch { pattern: &'static str, sample: String },
}

/// What to do when a pattern matches.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Action {
    /// Hard-reject the contribution. Use for unambiguous PII signals
    /// (email / phone / user paths / known IDs).
    Reject,
    /// Replace the match with a placeholder, preserve the rest of the
    /// string. Use for fuzzy patterns whose false-positive rate is high
    /// enough that hard-reject would silently kill legitimate
    /// contributions (e.g. Title-Case bigrams).
    Redact,
}

struct PiiPattern {
    name: &'static str,
    re: Regex,
    action: Action,
}

const REDACT_PLACEHOLDER: &str = "[redacted]";

static PATTERNS: Lazy<Vec<PiiPattern>> = Lazy::new(|| {
    vec![
        PiiPattern {
            name: "email",
            re: Regex::new(r"\b[\w._%+-]+@[\w.-]+\.[A-Za-z]{2,}\b").unwrap(),
            action: Action::Reject,
        },
        PiiPattern {
            name: "phone",
            re: Regex::new(r"\+\d{6,}").unwrap(),
            action: Action::Reject,
        },
        PiiPattern {
            name: "user_path",
            re: Regex::new(r"/home/\w+|/Users/\w+|C:\\Users\\\w+").unwrap(),
            action: Action::Reject,
        },
        PiiPattern {
            name: "publication_id",
            re: Regex::new(r"\bPMID[: ]?\d+|10\.\d{4,}/\S+").unwrap(),
            action: Action::Reject,
        },
        // P1.3 additions (2026-05-07 audit):
        PiiPattern {
            name: "ipv4",
            re: Regex::new(
                r"\b(?:25[0-5]|2[0-4]\d|1\d{2}|[1-9]?\d)(?:\.(?:25[0-5]|2[0-4]\d|1\d{2}|[1-9]?\d)){3}\b",
            )
            .unwrap(),
            action: Action::Reject,
        },
        PiiPattern {
            name: "iso_date",
            re: Regex::new(r"\b\d{4}-\d{2}-\d{2}\b").unwrap(),
            action: Action::Redact,
        },
        PiiPattern {
            name: "long_id",
            // 9-12 consecutive digits (SSN / INN / passport-shaped).
            // `\b` boundary handles non-word edges; lookarounds aren't
            // available in the regex crate, so a clean worker payload
            // simply must not contain a 9-12 digit run.
            re: Regex::new(r"\b\d{9,12}\b").unwrap(),
            action: Action::Reject,
        },
        // P1.2 — name_pair: Title-Case bigram, kept last so other
        // patterns (e.g. user_path, email) match first. Switched to
        // Redact in 2026-05-07 audit (was Reject) to avoid killing
        // contributions on benign collisions like "Linux Kernel" or
        // "User Activity".
        PiiPattern {
            name: "name_pair",
            re: Regex::new(r"\b[A-Z][a-z]+ [A-Z][a-z]+\b").unwrap(),
            action: Action::Redact,
        },
    ]
});

/// Walk a JSON value; reject on any pattern with `Action::Reject`,
/// redact (rewrite) any pattern with `Action::Redact`. Returns the
/// (possibly redacted) value on success.
pub fn scrub_value(mut v: Value) -> Result<Value, ScrubError> {
    scrub_inner(&mut v)?;
    Ok(v)
}

fn scrub_inner(v: &mut Value) -> Result<(), ScrubError> {
    match v {
        Value::String(s) => {
            for p in PATTERNS.iter() {
                match p.action {
                    Action::Reject => {
                        if let Some(m) = p.re.find(s) {
                            return Err(ScrubError::PiiMatch {
                                pattern: p.name,
                                sample: format!(
                                    "{}…",
                                    m.as_str().chars().take(60).collect::<String>()
                                ),
                            });
                        }
                    }
                    Action::Redact => {
                        if p.re.is_match(s) {
                            *s = p.re.replace_all(s, REDACT_PLACEHOLDER).into_owned();
                        }
                    }
                }
            }
            Ok(())
        }
        Value::Array(arr) => {
            for item in arr.iter_mut() {
                scrub_inner(item)?;
            }
            Ok(())
        }
        Value::Object(map) => {
            for (_k, val) in map.iter_mut() {
                scrub_inner(val)?;
            }
            Ok(())
        }
        _ => Ok(()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn pass_clean_payload() {
        let v = json!({"v":1,"counts":[1,2,3],"theme":"diagnosis"});
        scrub_value(v).unwrap();
    }

    #[test]
    fn block_email() {
        let v = json!({"contact":"djabbat@gmail.com"});
        let err = scrub_value(v).unwrap_err();
        assert!(matches!(err, ScrubError::PiiMatch { pattern: "email", .. }));
    }

    #[test]
    fn block_phone() {
        let v = json!({"contact":"+995555185161"});
        assert!(matches!(scrub_value(v).unwrap_err(),
            ScrubError::PiiMatch { pattern: "phone", .. }));
    }

    #[test]
    fn block_user_path() {
        let v = json!({"path":"/home/jaba/web"});
        assert!(matches!(scrub_value(v).unwrap_err(),
            ScrubError::PiiMatch { pattern: "user_path", .. }));
    }

    #[test]
    fn redact_name_pair_preserves_payload() {
        // P1.2: name_pair now redacts instead of rejecting. The
        // contribution survives, the name is replaced.
        let v = json!({"author":"Jaba Tkemaladze","ledger":{"n_runs":7}});
        let out = scrub_value(v).unwrap();
        assert_eq!(out["author"].as_str().unwrap(), REDACT_PLACEHOLDER);
        assert_eq!(out["ledger"]["n_runs"].as_u64().unwrap(), 7);
    }

    #[test]
    fn redact_name_pair_does_not_kill_legitimate_title_case() {
        // "Linux Kernel" used to be a hard-reject under the old policy;
        // now it just redacts and the rest of the doc passes.
        let v = json!({"theme":"Linux Kernel debugging tips"});
        let out = scrub_value(v).unwrap();
        let s = out["theme"].as_str().unwrap();
        assert!(s.contains(REDACT_PLACEHOLDER), "expected redaction, got {s}");
        assert!(s.contains("debugging"));
    }

    #[test]
    fn block_pmid() {
        let v = json!({"ref":"PMID 36583780"});
        assert!(matches!(scrub_value(v).unwrap_err(),
            ScrubError::PiiMatch { pattern: "publication_id", .. }));
    }

    #[test]
    fn block_doi() {
        let v = json!({"doi":"10.65649/xf5vp867"});
        assert!(matches!(scrub_value(v).unwrap_err(),
            ScrubError::PiiMatch { pattern: "publication_id", .. }));
    }

    #[test]
    fn block_nested_array() {
        let v = json!({"items":[{"x":1},{"contact":"djabbat@gmail.com"}]});
        assert!(scrub_value(v).is_err());
    }

    // ── P1.3 — extended PII patterns ───────────────────────────────

    #[test]
    fn block_ipv4() {
        let v = json!({"trace":"connected to 192.168.1.42"});
        assert!(matches!(scrub_value(v).unwrap_err(),
            ScrubError::PiiMatch { pattern: "ipv4", .. }));
    }

    #[test]
    fn block_ipv4_edge_max_octet() {
        let v = json!({"trace":"255.255.255.255"});
        assert!(matches!(scrub_value(v).unwrap_err(),
            ScrubError::PiiMatch { pattern: "ipv4", .. }));
    }

    #[test]
    fn does_not_block_invalid_ipv4_octet() {
        // 999 is not a valid octet — must NOT be flagged as IPv4.
        let v = json!({"build":"version 999.0.0.1-foo"});
        // The trailing 1-foo embeds a long_id-shaped match? '.1' is just 1
        // digit, fine. The leading "999.0.0.1" is not a valid IPv4. So this
        // payload should pass scrub.
        scrub_value(v).unwrap();
    }

    #[test]
    fn redact_iso_date() {
        let v = json!({"timeline":"event on 2026-05-07 at noon"});
        let out = scrub_value(v).unwrap();
        let s = out["timeline"].as_str().unwrap();
        assert!(s.contains(REDACT_PLACEHOLDER), "expected redaction, got {s}");
        assert!(s.contains("event on"));
    }

    #[test]
    fn block_long_id() {
        let v = json!({"id":"123456789"}); // 9 digits
        assert!(matches!(scrub_value(v).unwrap_err(),
            ScrubError::PiiMatch { pattern: "long_id", .. }));
    }

    #[test]
    fn block_long_id_12() {
        let v = json!({"id":"123456789012"}); // 12 digits
        assert!(matches!(scrub_value(v).unwrap_err(),
            ScrubError::PiiMatch { pattern: "long_id", .. }));
    }

    #[test]
    fn does_not_block_short_numeric() {
        // 8 digits — below threshold, not flagged.
        let v = json!({"counter":12345678});
        scrub_value(v).unwrap();
        let v = json!({"counter":"12345678"});
        scrub_value(v).unwrap();
    }

    #[test]
    fn name_pair_is_last_wins_for_user_path() {
        // user_path matches first (Reject), so a path with embedded
        // Title-Case must still be rejected as user_path, not redacted.
        let v = json!({"path":"/home/jaba/Linux Kernel"});
        assert!(matches!(scrub_value(v).unwrap_err(),
            ScrubError::PiiMatch { pattern: "user_path", .. }));
    }
}
