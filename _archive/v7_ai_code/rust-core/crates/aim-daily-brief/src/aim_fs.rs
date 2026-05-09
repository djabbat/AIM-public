//! Integration helper: render an AIM_FS inbox digest block for the daily
//! brief.  Pulls pending proposals through the `aim-fs` JSON Port (so we
//! don't link the database directly — keeps daily-brief a thin Rust binary).
//!
//! Usage in the binary:
//!
//! ```no_run
//! use aim_daily_brief::aim_fs::render_inbox_block;
//! let inbox = render_inbox_block("djabbat", "/usr/local/bin/aim-fs", "/var/lib/aim_fs", 5)
//!     .unwrap_or_default();
//! ```

use serde::{Deserialize, Serialize};
use std::io::Write;
use std::process::{Command, Stdio};

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(bound(deserialize = "T: serde::Deserialize<'de>"))]
struct Reply<T> {
    ok: bool,
    #[serde(default = "default_none")]
    result: Option<T>,
    #[serde(default)]
    error: Option<String>,
}

fn default_none<T>() -> Option<T> {
    None
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct Proposal {
    id: String,
    proposal_type: String,
    rationale: Option<String>,
    proposed_data: Option<String>,
    created_at: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct PatientSummary {
    surname: Option<String>,
    name: Option<String>,
    dob: Option<String>,
    last_visit_complaint: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct Hit {
    id: String,
    title: Option<String>,
    schema: String,
    score: i64,
    created_at: String,
}

/// Render a markdown-flavoured digest of the top `top_n` pending proposals
/// + total patient count.  Returns an empty string if the binary is missing
/// or any RPC fails (so the daily brief still renders without AIM_FS).
pub fn render_inbox_block(
    tenant_id: &str,
    binary: &str,
    aim_root: &str,
    top_n: usize,
) -> Option<String> {
    let pending_cmd = format!(
        r#"{{"op":"list_pending","tenant_id":"{}","limit":{}}}"#,
        tenant_id, top_n
    );
    let patients_cmd = format!(
        r#"{{"op":"list_patients","doctor_id":"{}"}}"#,
        tenant_id
    );
    let combined = format!("{pending_cmd}\n{patients_cmd}\n");

    let mut child = Command::new(binary)
        .env("AIM_FS_ROOT", aim_root)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .ok()?;

    if let Some(stdin) = child.stdin.as_mut() {
        let _ = stdin.write_all(combined.as_bytes());
    }
    let out = child.wait_with_output().ok()?;
    let stdout = String::from_utf8_lossy(&out.stdout).to_string();

    let mut lines = stdout.lines();
    let pending_reply: Reply<Vec<Proposal>> =
        serde_json::from_str(lines.next().unwrap_or("{}")).unwrap_or(Reply {
            ok: false,
            result: None,
            error: None,
        });
    let patients_reply: Reply<Vec<PatientSummary>> =
        serde_json::from_str(lines.next().unwrap_or("{}")).unwrap_or(Reply {
            ok: false,
            result: None,
            error: None,
        });

    let pending = pending_reply.result.unwrap_or_default();
    let patients = patients_reply.result.unwrap_or_default();

    // Pull recent decisions / disputes for richer brief.
    let recent = call_aim_fs::<Vec<Hit>>(
        binary,
        aim_root,
        &serde_json::json!({
            "op": "search",
            "tenant_id": tenant_id,
            "query": "today yesterday plan deadline",
            "scope": {"status": "active"},
            "limit": 3,
        }),
    )
    .unwrap_or_default();

    let disputes = call_aim_fs::<Vec<serde_json::Value>>(
        binary,
        aim_root,
        &serde_json::json!({"op": "list_disputes", "tenant_id": tenant_id}),
    )
    .unwrap_or_default();

    let mut out = String::new();
    out.push_str(&format!(
        "📥 AIM Inbox: **{}** pending · 🧑 patients: {} · ⚖ disputes: {}\n",
        pending.len(),
        patients.len(),
        disputes.len()
    ));
    if !pending.is_empty() {
        out.push_str("  pending:\n");
        for p in pending.iter().take(top_n) {
            let rationale = p.rationale.as_deref().unwrap_or("");
            let date = p.created_at.split('T').next().unwrap_or(&p.created_at);
            out.push_str(&format!(
                "    • [{}] {}: {}\n",
                date,
                p.proposal_type,
                truncate(rationale, 80)
            ));
        }
        out.push_str("    → Review at /inbox\n");
    }
    if !disputes.is_empty() {
        out.push_str(&format!(
            "  ⚖ {} unresolved disputes — open /fs/disputes\n",
            disputes.len()
        ));
    }
    if !recent.is_empty() {
        out.push_str("  recent active facts:\n");
        for h in recent.iter().take(3) {
            let title = h.title.as_deref().unwrap_or("(no title)");
            out.push_str(&format!("    • {}\n", truncate(title, 80)));
        }
    }
    Some(out)
}

/// Generic helper for one-shot Port calls — returns parsed result or None.
fn call_aim_fs<T: for<'de> Deserialize<'de>>(
    binary: &str,
    aim_root: &str,
    payload: &serde_json::Value,
) -> Option<T> {
    let mut child = Command::new(binary)
        .env("AIM_FS_ROOT", aim_root)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .ok()?;
    if let Some(stdin) = child.stdin.as_mut() {
        let _ = writeln!(stdin, "{}", serde_json::to_string(payload).ok()?);
    }
    let out = child.wait_with_output().ok()?;
    let stdout = String::from_utf8_lossy(&out.stdout).to_string();
    let first = stdout.lines().next().unwrap_or("{}");
    let v: Reply<T> = serde_json::from_str(first).ok()?;
    if v.ok {
        v.result
    } else {
        None
    }
}

fn truncate(s: &str, max: usize) -> String {
    if s.chars().count() <= max {
        s.to_string()
    } else {
        let cut: String = s.chars().take(max - 1).collect();
        format!("{cut}…")
    }
}
