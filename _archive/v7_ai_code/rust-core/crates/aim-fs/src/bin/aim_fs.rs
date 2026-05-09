//! aim-fs CLI / Port-bridge for Phoenix.
//!
//! Reads JSON-RPC-style commands one per line from stdin, writes one JSON
//! response per line to stdout. Phoenix's Elixir-Port talks to this binary
//! per SPEC §10.2.
//!
//! Commands:
//!   {"op":"propose", "tenant_id":"...", "new":{...}, "rationale":"...",
//!    "idempotency_key":"...", "policy":{...}}
//!   {"op":"approve", "tenant_id":"...", "proposal_id":"...", "actor":{...}}
//!   {"op":"reject",  "tenant_id":"...", "proposal_id":"...", "actor":{...}, "reason":"..."}
//!   {"op":"list_pending", "tenant_id":"...", "limit":50}
//!   {"op":"scaffold_project", "user_id":"...", "slug":"...", "concept":"..."}
//!   {"op":"sweep"}
//!
//! Each response: {"ok": true, "result": <value>} or {"ok": false, "error": "..."}
use aim_fs::search::{Hit, SearchScope};
use aim_fs::{Actor, AimFs, ApprovalPolicy, LinkType, NewEntity};
use serde::{Deserialize, Serialize};
use std::io::{BufRead, Write};
use std::path::PathBuf;

#[derive(Debug, Deserialize)]
#[serde(tag = "op", rename_all = "snake_case")]
enum Cmd {
    Propose {
        tenant_id: String,
        new: NewEntity,
        rationale: Option<String>,
        idempotency_key: Option<String>,
        policy: ApprovalPolicyDto,
    },
    Approve {
        tenant_id: String,
        proposal_id: String,
        actor: Actor,
    },
    Reject {
        tenant_id: String,
        proposal_id: String,
        actor: Actor,
        reason: Option<String>,
    },
    ListPending {
        tenant_id: String,
        limit: i64,
    },
    ScaffoldProject {
        user_id: String,
        slug: String,
        concept: String,
    },
    EnsurePatient {
        doctor_id: String,
        patient_key: String,
    },
    Sweep,
    Ping,
    Search {
        tenant_id: String,
        query: String,
        #[serde(default)]
        scope: SearchScope,
        #[serde(default = "default_limit")]
        limit: i64,
    },
    AddLink {
        tenant_id: String,
        source_id: String,
        target_id: String,
        link_type: LinkType,
    },
    ListOutgoing {
        tenant_id: String,
        source_id: String,
    },
    ListProjects {
        user_id: String,
    },
    ListPatients {
        doctor_id: String,
    },
    ListDisputes {
        tenant_id: String,
    },
    ResolveDispute {
        tenant_id: String,
        winner_id: String,
        loser_id: String,
        actor: Actor,
    },
    ProfileView {
        tenant_id: String,
    },
    ProjectActivity {
        tenant_id: String,
        slug: String,
    },
    EntityDetail {
        tenant_id: String,
        id: String,
    },
    Stats {
        tenant_id: String,
    },
    ListEvents {
        tenant_id: String,
        limit: i64,
    },
}

fn default_limit() -> i64 {
    50
}

#[derive(Debug, Deserialize)]
struct ApprovalPolicyDto {
    #[serde(default)]
    auto_approve_user_commands: bool,
    #[serde(default)]
    auto_approve_observational_with_confidence_above: f64,
    #[serde(default)]
    auto_approve_service_events: bool,
    #[serde(default)]
    require_approval_for: Vec<String>,
    #[serde(default = "default_inactivity")]
    max_inactivity_days: i64,
}
fn default_inactivity() -> i64 {
    30
}

#[derive(Debug, Serialize)]
struct Reply {
    ok: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    result: Option<serde_json::Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    error: Option<String>,
}

fn main() -> anyhow::Result<()> {
    let root = std::env::var("AIM_FS_ROOT")
        .map(PathBuf::from)
        .unwrap_or_else(|_| {
            dirs_root().unwrap_or_else(|| PathBuf::from("/var/lib/aim_fs"))
        });
    let fs = AimFs::open(&root)?;

    let stdin = std::io::stdin();
    let stdout = std::io::stdout();
    let mut stdout = stdout.lock();
    for line in stdin.lock().lines() {
        let line = line?;
        if line.trim().is_empty() {
            continue;
        }
        let reply = match serde_json::from_str::<Cmd>(&line) {
            Ok(cmd) => dispatch(&fs, cmd),
            Err(e) => Reply {
                ok: false,
                result: None,
                error: Some(format!("parse: {e}")),
            },
        };
        writeln!(stdout, "{}", serde_json::to_string(&reply)?)?;
        stdout.flush()?;
    }
    Ok(())
}

fn dirs_root() -> Option<PathBuf> {
    std::env::var_os("HOME").map(|h| PathBuf::from(h).join(".aim_fs"))
}

fn dispatch(fs: &AimFs, cmd: Cmd) -> Reply {
    match cmd {
        Cmd::Ping => ok(serde_json::json!({"pong": true})),
        Cmd::Propose {
            tenant_id,
            new,
            rationale,
            idempotency_key,
            policy,
        } => {
            let pol = ApprovalPolicy {
                auto_approve_user_commands: policy.auto_approve_user_commands,
                auto_approve_observational_with_confidence_above: policy
                    .auto_approve_observational_with_confidence_above,
                auto_approve_service_events: policy.auto_approve_service_events,
                require_approval_for: policy.require_approval_for,
                max_inactivity_days: policy.max_inactivity_days,
            };
            match fs.propose(
                &tenant_id,
                new,
                rationale.as_deref(),
                idempotency_key.as_deref(),
                &pol,
            ) {
                Ok(o) => ok(serde_json::to_value(o).unwrap()),
                Err(e) => err(e),
            }
        }
        Cmd::Approve {
            tenant_id,
            proposal_id,
            actor,
        } => match fs.approve_proposal(&tenant_id, &proposal_id, &actor) {
            Ok(()) => ok(serde_json::json!({})),
            Err(e) => err(e),
        },
        Cmd::Reject {
            tenant_id,
            proposal_id,
            actor,
            reason,
        } => match fs.reject_proposal(&tenant_id, &proposal_id, &actor, reason.as_deref()) {
            Ok(()) => ok(serde_json::json!({})),
            Err(e) => err(e),
        },
        Cmd::ListPending { tenant_id, limit } => match fs.list_pending(&tenant_id, limit) {
            Ok(v) => ok(serde_json::to_value(v).unwrap()),
            Err(e) => err(e),
        },
        Cmd::ScaffoldProject {
            user_id,
            slug,
            concept,
        } => match fs.scaffold_project(&user_id, &slug, &concept) {
            Ok(p) => ok(serde_json::json!({"path": p.display().to_string()})),
            Err(e) => err(e),
        },
        Cmd::EnsurePatient {
            doctor_id,
            patient_key,
        } => match fs.ensure_patient(&doctor_id, &patient_key) {
            Ok(p) => ok(serde_json::json!({"path": p.display().to_string()})),
            Err(e) => err(e),
        },
        Cmd::Sweep => match aim_fs::sweeper::sweep_once(&unsafe_pool(fs)) {
            Ok(n) => ok(serde_json::json!({"expired": n})),
            Err(e) => err(e),
        },
        Cmd::Search {
            tenant_id,
            query,
            scope,
            limit,
        } => match fs.search(&tenant_id, &query, &scope, limit) {
            Ok(hits) => ok(serde_json::to_value::<Vec<Hit>>(hits).unwrap()),
            Err(e) => err(e),
        },
        Cmd::AddLink {
            tenant_id,
            source_id,
            target_id,
            link_type,
        } => match fs.add_link(&tenant_id, &source_id, &target_id, link_type) {
            Ok(()) => ok(serde_json::json!({})),
            Err(e) => err(e),
        },
        Cmd::ListOutgoing {
            tenant_id,
            source_id,
        } => match fs.list_outgoing_links(&tenant_id, &source_id) {
            Ok(rows) => ok(serde_json::to_value(
                rows.into_iter()
                    .map(|(t, lt)| serde_json::json!({"target_id": t, "link_type": lt}))
                    .collect::<Vec<_>>(),
            )
            .unwrap()),
            Err(e) => err(e),
        },
        Cmd::ListProjects { user_id } => match fs.list_projects(&user_id) {
            Ok(v) => ok(serde_json::to_value(v).unwrap()),
            Err(e) => err(e),
        },
        Cmd::ListPatients { doctor_id } => match fs.list_patients(&doctor_id) {
            Ok(v) => ok(serde_json::to_value(v).unwrap()),
            Err(e) => err(e),
        },
        Cmd::ListDisputes { tenant_id } => match fs.list_disputes(&tenant_id) {
            Ok(v) => ok(serde_json::to_value(v).unwrap()),
            Err(e) => err(e),
        },
        Cmd::ResolveDispute {
            tenant_id,
            winner_id,
            loser_id,
            actor,
        } => match fs.resolve_dispute(&tenant_id, &winner_id, &loser_id, &actor) {
            Ok(()) => ok(serde_json::json!({})),
            Err(e) => err(e),
        },
        Cmd::ProfileView { tenant_id } => match fs.profile_view(&tenant_id) {
            Ok(v) => ok(serde_json::to_value(v).unwrap()),
            Err(e) => err(e),
        },
        Cmd::ProjectActivity { tenant_id, slug } => match fs.project_activity(&tenant_id, &slug) {
            Ok(v) => ok(serde_json::to_value(v).unwrap()),
            Err(e) => err(e),
        },
        Cmd::EntityDetail { tenant_id, id } => match fs.entity_detail(&tenant_id, &id) {
            Ok(v) => ok(serde_json::to_value(v).unwrap()),
            Err(e) => err(e),
        },
        Cmd::Stats { tenant_id } => match fs.stats(&tenant_id) {
            Ok(v) => ok(serde_json::to_value(v).unwrap()),
            Err(e) => err(e),
        },
        Cmd::ListEvents { tenant_id, limit } => match fs.list_events(&tenant_id, limit) {
            Ok(v) => ok(serde_json::to_value(v).unwrap()),
            Err(e) => err(e),
        },
    }
}

fn ok(v: serde_json::Value) -> Reply {
    Reply {
        ok: true,
        result: Some(v),
        error: None,
    }
}
fn err<E: std::fmt::Display>(e: E) -> Reply {
    Reply {
        ok: false,
        result: None,
        error: Some(e.to_string()),
    }
}

// Sweeper needs the pool; helper exposes it via internal accessor.
// Keep this helper local — not part of the public AimFs API, since callers
// should always go through the impl methods.
fn unsafe_pool(fs: &AimFs) -> aim_fs::db::DbPool {
    fs_pool_clone(fs)
}

fn fs_pool_clone(fs: &AimFs) -> aim_fs::db::DbPool {
    // We cannot reach .pool directly because it's pub(crate). Re-open from disk.
    // Cheap: reuses WAL, no migrations re-applied (CREATE IF NOT EXISTS).
    let root = fs.root().to_path_buf();
    let inner = aim_fs::db::open_pool(&root.join("_service").join("db").join("aim_fs.db"))
        .expect("reopen db");
    inner
}
