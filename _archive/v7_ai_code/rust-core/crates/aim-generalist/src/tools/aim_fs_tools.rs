//! AIM_FS bridge tools for the generalist.
//!
//! New companions to `memory_save` / `memory_recall` (which talk to
//! `aim-rag`) — these talk to AIM_FS through the `aim-fs` JSON Port.
//! Distinct because semantically they are NOT vector-search; they are the
//! approval-queue store.
//!
//!   memory_save_aim_fs  { title, body, schema?, tags?, scope_project_ids?,
//!                         confidence?, rationale?, source? }
//!   inbox_pending_aim_fs { limit?: 20 }
//!   inbox_approve_aim_fs { proposal_id }
//!   inbox_reject_aim_fs  { proposal_id, reason? }
//!
//! Behaviour:
//!   - default `source = "user_command"` so explicit "remember X" calls
//!     auto-approve per ApprovalPolicy
//!   - default schema = "fact_v1" (relaxed validation)
//!   - tenant_id resolves from env `AIM_FS_TENANT` or context user
//!
//! See AIM_FS SPEC.md §4 (approval queue) and §10.2 (Port).

use super::{Tool, ToolCtx};
use async_trait::async_trait;
use serde_json::{json, Value};
use std::process::Stdio;
use tokio::io::AsyncWriteExt;
use tokio::process::Command;

fn binary() -> String {
    std::env::var("AIM_FS_BIN").unwrap_or_else(|_| "aim-fs".into())
}
fn aim_root() -> String {
    std::env::var("AIM_FS_ROOT").unwrap_or_else(|_| {
        std::env::var("HOME")
            .map(|h| format!("{h}/.aim_fs"))
            .unwrap_or_else(|_| "/var/lib/aim_fs".into())
    })
}
fn tenant() -> String {
    std::env::var("AIM_FS_TENANT").unwrap_or_else(|_| "djabbat".into())
}

/// Send a single JSON-line command to `aim-fs` and parse its single-line reply.
async fn call(payload: Value) -> Result<Value, String> {
    let mut child = Command::new(binary())
        .env("AIM_FS_ROOT", aim_root())
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|e| format!("spawn aim-fs: {e}"))?;

    let mut stdin = child.stdin.take().ok_or("no stdin")?;
    let line = format!("{}\n", payload);
    stdin
        .write_all(line.as_bytes())
        .await
        .map_err(|e| format!("write: {e}"))?;
    drop(stdin);

    let out = child
        .wait_with_output()
        .await
        .map_err(|e| format!("wait: {e}"))?;
    let stdout = String::from_utf8_lossy(&out.stdout);
    let first = stdout.lines().next().unwrap_or("{}");
    let v: Value =
        serde_json::from_str(first).map_err(|e| format!("parse: {e} body={first}"))?;
    if v.get("ok").and_then(|b| b.as_bool()) == Some(true) {
        Ok(v.get("result").cloned().unwrap_or(Value::Null))
    } else {
        Err(v
            .get("error")
            .and_then(|e| e.as_str())
            .unwrap_or("unknown")
            .to_string())
    }
}

pub struct MemorySaveAimFs;
#[async_trait]
impl Tool for MemorySaveAimFs {
    fn name(&self) -> &'static str {
        "memory_save_aim_fs"
    }
    async fn run(&self, args: &Value, _ctx: &ToolCtx) -> Result<String, String> {
        let body = args
            .get("body")
            .or_else(|| args.get("text"))
            .and_then(|v| v.as_str())
            .ok_or_else(|| "missing arg: body (or text)".to_string())?;
        let title = args
            .get("title")
            .and_then(|v| v.as_str())
            .map(String::from)
            .unwrap_or_else(|| {
                body.lines()
                    .next()
                    .unwrap_or("(memory)")
                    .chars()
                    .take(80)
                    .collect()
            });
        let schema = args
            .get("schema")
            .and_then(|v| v.as_str())
            .unwrap_or("fact_v1");
        let source = args
            .get("source")
            .and_then(|v| v.as_str())
            .unwrap_or("user_command");
        let tags: Vec<String> = args
            .get("tags")
            .and_then(|v| v.as_array())
            .map(|a| a.iter().filter_map(|x| x.as_str().map(String::from)).collect())
            .unwrap_or_default();
        let project_ids: Option<Vec<String>> = args
            .get("scope_project_ids")
            .and_then(|v| v.as_array())
            .map(|a| a.iter().filter_map(|x| x.as_str().map(String::from)).collect());
        let patient_ids: Vec<String> = args
            .get("scope_patient_ids")
            .and_then(|v| v.as_array())
            .map(|a| a.iter().filter_map(|x| x.as_str().map(String::from)).collect())
            .unwrap_or_default();
        let confidence = args.get("confidence").and_then(|v| v.as_f64());
        let rationale = args.get("rationale").and_then(|v| v.as_str()).map(String::from);

        let tid = tenant();
        let policy = json!({
            "auto_approve_user_commands": true,
            "auto_approve_observational_with_confidence_above": 0.95,
            "auto_approve_service_events": true,
            "require_approval_for": ["feedback","proposal","recipe","diagnosis"],
            "max_inactivity_days": 30,
        });
        let payload = json!({
            "op": "propose",
            "tenant_id": tid,
            "rationale": rationale,
            "policy": policy,
            "new": {
                "schema": schema,
                "schema_version": 1,
                "title": title,
                "body": body,
                "source": source,
                "user_id": tid,
                "scope_global": false,
                "scope_user_ids": [tid],
                "scope_project_ids": project_ids,
                "scope_patient_ids": patient_ids,
                "tags": tags,
                "confidence": confidence,
                "requires_verification": false,
            }
        });
        let result = call(payload).await?;
        Ok(format!(
            "saved entity_id={} status={} auto_approved={}",
            result.get("entity_id").and_then(|v| v.as_str()).unwrap_or("?"),
            result.get("entity_status").and_then(|v| v.as_str()).unwrap_or("?"),
            result.get("auto_approved").and_then(|v| v.as_bool()).unwrap_or(false),
        ))
    }
}

pub struct InboxPendingAimFs;
#[async_trait]
impl Tool for InboxPendingAimFs {
    fn name(&self) -> &'static str {
        "inbox_pending_aim_fs"
    }
    async fn run(&self, args: &Value, _ctx: &ToolCtx) -> Result<String, String> {
        let limit = args.get("limit").and_then(|v| v.as_u64()).unwrap_or(20);
        let payload = json!({
            "op": "list_pending",
            "tenant_id": tenant(),
            "limit": limit as i64,
        });
        let result = call(payload).await?;
        let items = result.as_array().cloned().unwrap_or_default();
        if items.is_empty() {
            return Ok("(inbox is empty)".into());
        }
        let lines: Vec<String> = items
            .iter()
            .map(|p| {
                format!(
                    "  • {} [{}] {}",
                    p.get("created_at")
                        .and_then(|v| v.as_str())
                        .unwrap_or("?"),
                    p.get("proposal_type")
                        .and_then(|v| v.as_str())
                        .unwrap_or("?"),
                    p.get("rationale").and_then(|v| v.as_str()).unwrap_or("")
                )
            })
            .collect();
        Ok(format!(
            "{} pending:\n{}",
            items.len(),
            lines.join("\n")
        ))
    }
}

pub struct InboxApproveAimFs;
#[async_trait]
impl Tool for InboxApproveAimFs {
    fn name(&self) -> &'static str {
        "inbox_approve_aim_fs"
    }
    async fn run(&self, args: &Value, _ctx: &ToolCtx) -> Result<String, String> {
        let proposal_id = args
            .get("proposal_id")
            .and_then(|v| v.as_str())
            .ok_or_else(|| "missing arg: proposal_id".to_string())?;
        let payload = json!({
            "op": "approve",
            "tenant_id": tenant(),
            "proposal_id": proposal_id,
            "actor": {"user_id": tenant(), "session_id": null},
        });
        call(payload).await?;
        Ok(format!("approved {proposal_id}"))
    }
}

pub struct InboxRejectAimFs;
#[async_trait]
impl Tool for InboxRejectAimFs {
    fn name(&self) -> &'static str {
        "inbox_reject_aim_fs"
    }
    async fn run(&self, args: &Value, _ctx: &ToolCtx) -> Result<String, String> {
        let proposal_id = args
            .get("proposal_id")
            .and_then(|v| v.as_str())
            .ok_or_else(|| "missing arg: proposal_id".to_string())?;
        let reason = args.get("reason").and_then(|v| v.as_str());
        let payload = json!({
            "op": "reject",
            "tenant_id": tenant(),
            "proposal_id": proposal_id,
            "actor": {"user_id": tenant(), "session_id": null},
            "reason": reason,
        });
        call(payload).await?;
        Ok(format!("rejected {proposal_id}"))
    }
}

/// AIM_FS-backed semantic recall (FTS5 BM25). Symmetric counterpart to
/// `memory_save_aim_fs`. Use this when the agent needs to look up
/// previously approved facts/feedback rules during a conversation.
///
///   memory_recall_aim_fs { query, project_id?, schema?, k?: 5 }
pub struct MemoryRecallAimFs;
#[async_trait]
impl Tool for MemoryRecallAimFs {
    fn name(&self) -> &'static str {
        "memory_recall_aim_fs"
    }
    async fn run(&self, args: &Value, _ctx: &ToolCtx) -> Result<String, String> {
        let query = args
            .get("query")
            .and_then(|v| v.as_str())
            .ok_or_else(|| "missing arg: query".to_string())?;
        let k = args.get("k").and_then(|v| v.as_u64()).unwrap_or(5);

        let mut scope = serde_json::Map::new();
        if let Some(p) = args.get("project_id").and_then(|v| v.as_str()) {
            scope.insert("project_id".into(), Value::String(p.to_string()));
        }
        if let Some(p) = args.get("patient_id").and_then(|v| v.as_str()) {
            scope.insert("patient_id".into(), Value::String(p.to_string()));
        }
        if let Some(s) = args.get("schema").and_then(|v| v.as_str()) {
            scope.insert("schema".into(), Value::String(s.to_string()));
        }

        let payload = json!({
            "op": "search",
            "tenant_id": tenant(),
            "query": query,
            "scope": Value::Object(scope),
            "limit": k as i64,
        });
        let result = call(payload).await?;
        let hits = result.as_array().cloned().unwrap_or_default();
        if hits.is_empty() {
            return Ok(format!("(no AIM_FS hits for `{query}`)"));
        }
        let lines: Vec<String> = hits
            .iter()
            .map(|h| {
                let id = h.get("id").and_then(|v| v.as_str()).unwrap_or("?");
                let short = id.chars().take(8).collect::<String>();
                let score = h.get("score").and_then(|v| v.as_i64()).unwrap_or(0);
                let schema = h.get("schema").and_then(|v| v.as_str()).unwrap_or("?");
                let title = h.get("title").and_then(|v| v.as_str()).unwrap_or("");
                let snippet = h.get("snippet").and_then(|v| v.as_str()).unwrap_or("");
                format!(
                    "[{short} score={score} {schema}] {title}\n  {}",
                    snippet.chars().take(160).collect::<String>()
                )
            })
            .collect();
        Ok(lines.join("\n\n"))
    }
}
