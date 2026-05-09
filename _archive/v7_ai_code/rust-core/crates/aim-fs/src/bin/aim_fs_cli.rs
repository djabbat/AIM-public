//! aim-fs-cli — terse human-friendly CLI shortcuts over `aim-fs` JSON Port.
//!
//! Dispatches to the same Port the Phoenix Port-bridge uses, but renders
//! human-readable output instead of JSON.  Designed for the doctor's daily
//! shell workflow:
//!
//!   aim-fs-cli inbox                     # list pending
//!   aim-fs-cli approve <8-char-prefix>   # approve by short id
//!   aim-fs-cli reject <id> [reason]
//!   aim-fs-cli search <query> [--project LC_CDATA] [--schema feedback_v1]
//!   aim-fs-cli profile
//!   aim-fs-cli projects
//!   aim-fs-cli patients
//!   aim-fs-cli entity <id>
//!   aim-fs-cli digest                    # one-line summary
//!
//! Tenant defaults from env `AIM_FS_TENANT` (else "djabbat"); aim-fs binary
//! from `AIM_FS_BIN` (else `aim-fs` on PATH).
use serde_json::Value;
use std::io::Write;
use std::process::{Command, Stdio};

fn main() {
    let argv: Vec<String> = std::env::args().collect();
    if argv.len() < 2 || argv[1] == "-h" || argv[1] == "--help" {
        print_help();
        return;
    }
    let cmd = argv[1].as_str();
    let rest: Vec<&str> = argv[2..].iter().map(|s| s.as_str()).collect();
    let result = match cmd {
        "inbox" => cmd_inbox(),
        "approve" => cmd_approve(&rest),
        "reject" => cmd_reject(&rest),
        "search" => cmd_search(&rest),
        "profile" => cmd_profile(),
        "projects" => cmd_projects(),
        "patients" => cmd_patients(),
        "disputes" => cmd_disputes(),
        "entity" => cmd_entity(&rest),
        "digest" => cmd_digest(),
        other => Err(format!("unknown command: {other}")),
    };
    match result {
        Ok(s) => println!("{s}"),
        Err(e) => {
            eprintln!("aim-fs-cli ERROR: {e}");
            std::process::exit(1);
        }
    }
}

fn tenant() -> String {
    std::env::var("AIM_FS_TENANT").unwrap_or_else(|_| "djabbat".to_string())
}

fn binary() -> String {
    std::env::var("AIM_FS_BIN").unwrap_or_else(|_| "aim-fs".to_string())
}

fn aim_root() -> String {
    std::env::var("AIM_FS_ROOT").unwrap_or_else(|_| {
        std::env::var("HOME")
            .map(|h| format!("{h}/.aim_fs"))
            .unwrap_or_else(|_| "/var/lib/aim_fs".to_string())
    })
}

fn call(payload: Value) -> Result<Value, String> {
    let mut child = Command::new(binary())
        .env("AIM_FS_ROOT", aim_root())
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|e| format!("spawn: {e}"))?;
    if let Some(stdin) = child.stdin.as_mut() {
        let line = format!("{}\n", payload);
        stdin
            .write_all(line.as_bytes())
            .map_err(|e| format!("write: {e}"))?;
    }
    let out = child.wait_with_output().map_err(|e| format!("wait: {e}"))?;
    let stdout = String::from_utf8_lossy(&out.stdout);
    let first = stdout.lines().next().unwrap_or("{}");
    let v: Value = serde_json::from_str(first).map_err(|e| format!("parse: {e}"))?;
    if v.get("ok").and_then(|b| b.as_bool()) == Some(true) {
        Ok(v.get("result").cloned().unwrap_or(Value::Null))
    } else {
        Err(v.get("error").and_then(|e| e.as_str()).unwrap_or("?").to_string())
    }
}

fn resolve_id(prefix: &str) -> Result<String, String> {
    if prefix.len() >= 26 {
        return Ok(prefix.to_string());
    }
    let r = call(serde_json::json!({
        "op": "list_pending",
        "tenant_id": tenant(),
        "limit": 200,
    }))?;
    let items = r.as_array().cloned().unwrap_or_default();
    let needle = prefix.to_uppercase();
    for p in &items {
        if let Some(id) = p.get("id").and_then(|v| v.as_str()) {
            if id.starts_with(&needle) {
                return Ok(id.to_string());
            }
        }
    }
    Err(format!("no pending proposal starts with `{prefix}`"))
}

fn cmd_inbox() -> Result<String, String> {
    let r = call(serde_json::json!({
        "op": "list_pending",
        "tenant_id": tenant(),
        "limit": 30,
    }))?;
    let items = r.as_array().cloned().unwrap_or_default();
    if items.is_empty() {
        return Ok("(inbox is empty)".to_string());
    }
    let mut out = format!("inbox: {} pending\n", items.len());
    for p in &items {
        let id = p.get("id").and_then(|v| v.as_str()).unwrap_or("?");
        let short = id.chars().take(8).collect::<String>();
        let kind = p.get("proposal_type").and_then(|v| v.as_str()).unwrap_or("?");
        let rationale = p.get("rationale").and_then(|v| v.as_str()).unwrap_or("");
        let date = p
            .get("created_at")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .split('T')
            .next()
            .unwrap_or("");
        out.push_str(&format!("  {short}  [{date}] {kind}  {}\n", truncate(rationale, 80)));
    }
    Ok(out)
}

fn cmd_approve(args: &[&str]) -> Result<String, String> {
    let id = args.first().ok_or("usage: approve <id>")?;
    let full = resolve_id(id)?;
    call(serde_json::json!({
        "op": "approve",
        "tenant_id": tenant(),
        "proposal_id": full,
        "actor": {"user_id": tenant(), "session_id": null},
    }))?;
    Ok(format!("✓ approved {}", &full[..full.len().min(12)]))
}

fn cmd_reject(args: &[&str]) -> Result<String, String> {
    let id = args.first().ok_or("usage: reject <id> [reason]")?;
    let reason = if args.len() > 1 {
        Some(args[1..].join(" "))
    } else {
        None
    };
    let full = resolve_id(id)?;
    call(serde_json::json!({
        "op": "reject",
        "tenant_id": tenant(),
        "proposal_id": full,
        "actor": {"user_id": tenant(), "session_id": null},
        "reason": reason,
    }))?;
    Ok(format!("✗ rejected {}", &full[..full.len().min(12)]))
}

fn cmd_search(args: &[&str]) -> Result<String, String> {
    if args.is_empty() {
        return Err("usage: search <query> [--project SLUG] [--schema NAME] [-k N]".into());
    }
    let mut query = String::new();
    let mut project: Option<String> = None;
    let mut schema: Option<String> = None;
    let mut k: i64 = 10;
    let mut i = 0;
    while i < args.len() {
        match args[i] {
            "--project" => {
                project = args.get(i + 1).map(|s| s.to_string());
                i += 2;
            }
            "--schema" => {
                schema = args.get(i + 1).map(|s| s.to_string());
                i += 2;
            }
            "-k" => {
                k = args
                    .get(i + 1)
                    .and_then(|s| s.parse().ok())
                    .unwrap_or(10);
                i += 2;
            }
            other => {
                if !query.is_empty() {
                    query.push(' ');
                }
                query.push_str(other);
                i += 1;
            }
        }
    }
    let mut scope = serde_json::Map::new();
    if let Some(p) = project {
        scope.insert("project_id".into(), Value::String(p));
    }
    if let Some(s) = schema {
        scope.insert("schema".into(), Value::String(s));
    }
    let r = call(serde_json::json!({
        "op": "search",
        "tenant_id": tenant(),
        "query": query,
        "scope": scope,
        "limit": k,
    }))?;
    let hits = r.as_array().cloned().unwrap_or_default();
    if hits.is_empty() {
        return Ok(format!("(no hits for `{query}`)"));
    }
    let mut out = format!("{} hits for `{query}`\n", hits.len());
    for h in &hits {
        let id = h.get("id").and_then(|v| v.as_str()).unwrap_or("?");
        let short = id.chars().take(8).collect::<String>();
        let score = h.get("score").and_then(|v| v.as_i64()).unwrap_or(0);
        let title = h.get("title").and_then(|v| v.as_str()).unwrap_or("");
        let schema = h.get("schema").and_then(|v| v.as_str()).unwrap_or("");
        out.push_str(&format!(
            "  {short}  {score:>5}  {schema:18}  {}\n",
            truncate(title, 60)
        ));
    }
    Ok(out)
}

fn cmd_profile() -> Result<String, String> {
    let r = call(serde_json::json!({
        "op": "profile_view",
        "tenant_id": tenant(),
    }))?;
    let counts = r.get("counts").cloned().unwrap_or(Value::Null);
    let mut out = format!("profile: {}\n", tenant());
    if let Some(obj) = counts.as_object() {
        for (k, v) in obj {
            out.push_str(&format!("  {k}: {v}\n"));
        }
    }
    Ok(out)
}

fn cmd_projects() -> Result<String, String> {
    let r = call(serde_json::json!({
        "op": "list_projects",
        "user_id": tenant(),
    }))?;
    let arr = r.as_array().cloned().unwrap_or_default();
    if arr.is_empty() {
        return Ok("(no projects)".into());
    }
    let mut out = format!("{} projects\n", arr.len());
    for p in &arr {
        let slug = p.get("slug").and_then(|v| v.as_str()).unwrap_or("?");
        let title = p.get("title").and_then(|v| v.as_str()).unwrap_or("");
        out.push_str(&format!("  {slug:30} {}\n", truncate(title, 55)));
    }
    Ok(out)
}

fn cmd_patients() -> Result<String, String> {
    let r = call(serde_json::json!({
        "op": "list_patients",
        "doctor_id": tenant(),
    }))?;
    let arr = r.as_array().cloned().unwrap_or_default();
    if arr.is_empty() {
        return Ok("(no patients)".into());
    }
    let mut out = format!("{} patients\n", arr.len());
    for p in &arr {
        let key = p.get("key").and_then(|v| v.as_str()).unwrap_or("?");
        let surname = p.get("surname").and_then(|v| v.as_str()).unwrap_or("");
        let name = p.get("name").and_then(|v| v.as_str()).unwrap_or("");
        let dob = p.get("dob").and_then(|v| v.as_str()).unwrap_or("");
        out.push_str(&format!("  {surname} {name} ({dob})  [{key}]\n"));
    }
    Ok(out)
}

fn cmd_disputes() -> Result<String, String> {
    let r = call(serde_json::json!({
        "op": "list_disputes",
        "tenant_id": tenant(),
    }))?;
    let arr = r.as_array().cloned().unwrap_or_default();
    if arr.is_empty() {
        return Ok("(no active disputes)".into());
    }
    let mut out = format!("{} disputes\n", arr.len());
    for d in &arr {
        let a_id = d.get("a_id").and_then(|v| v.as_str()).unwrap_or("?");
        let a_t = d.get("a_title").and_then(|v| v.as_str()).unwrap_or("");
        let b_id = d.get("b_id").and_then(|v| v.as_str()).unwrap_or("?");
        let b_t = d.get("b_title").and_then(|v| v.as_str()).unwrap_or("");
        out.push_str(&format!(
            "  {} A:`{}` {}\n  {} B:`{}` {}\n  ---\n",
            "⚖",
            a_id.chars().take(8).collect::<String>(),
            truncate(a_t, 60),
            "⚖",
            b_id.chars().take(8).collect::<String>(),
            truncate(b_t, 60)
        ));
    }
    Ok(out)
}

fn cmd_entity(args: &[&str]) -> Result<String, String> {
    let id = args.first().ok_or("usage: entity <id>")?;
    let full = if id.len() >= 26 {
        id.to_string()
    } else {
        // Search prefix.
        let hits = call(serde_json::json!({
            "op": "search",
            "tenant_id": tenant(),
            "query": id,
            "scope": {},
            "limit": 1,
        }))?;
        let arr = hits.as_array().cloned().unwrap_or_default();
        arr.first()
            .and_then(|h| h.get("id"))
            .and_then(|v| v.as_str())
            .map(String::from)
            .ok_or_else(|| format!("no entity for `{id}`"))?
    };
    let v = call(serde_json::json!({
        "op": "entity_detail",
        "tenant_id": tenant(),
        "id": full,
    }))?;
    let title = v.get("title").and_then(|v| v.as_str()).unwrap_or("(no title)");
    let schema = v.get("schema").and_then(|v| v.as_str()).unwrap_or("?");
    let status = v.get("status").and_then(|v| v.as_str()).unwrap_or("?");
    let body = v.get("body").and_then(|v| v.as_str()).unwrap_or("");
    let mut out = format!("=== {title} ===\n");
    out.push_str(&format!("id:     {full}\n"));
    out.push_str(&format!("schema: {schema}\nstatus: {status}\n\n"));
    out.push_str(body);
    Ok(out)
}

fn cmd_digest() -> Result<String, String> {
    let pending = call(serde_json::json!({
        "op": "list_pending", "tenant_id": tenant(), "limit": 100,
    }))?;
    let pending_n = pending.as_array().map(|a| a.len()).unwrap_or(0);
    let disputes = call(serde_json::json!({
        "op": "list_disputes", "tenant_id": tenant(),
    }))?;
    let disputes_n = disputes.as_array().map(|a| a.len()).unwrap_or(0);
    // Use stats.total_entities — counts ALL schemas, not just profile_view
    // categories (which omit fact_v1, audit_v1, project_state_v1, ai_artifact_v1).
    let stats = call(serde_json::json!({
        "op": "stats", "tenant_id": tenant(),
    }))?;
    let total = stats
        .get("total_entities")
        .and_then(|v| v.as_i64())
        .unwrap_or(0);
    let events = stats
        .get("events_total")
        .and_then(|v| v.as_i64())
        .unwrap_or(0);
    Ok(format!(
        "AIM_FS · {pending_n} pending · {disputes_n} disputes · {total} entities · {events} events"
    ))
}

fn truncate(s: &str, max: usize) -> String {
    if s.chars().count() <= max {
        s.to_string()
    } else {
        let cut: String = s.chars().take(max - 1).collect();
        format!("{cut}…")
    }
}

fn print_help() {
    println!(
        "aim-fs-cli — friendly shortcuts over aim-fs JSON Port\n\n\
         USAGE: aim-fs-cli <command> [args]\n\n\
         Commands:\n\
         \tinbox                            list pending proposals\n\
         \tapprove <id>                     approve by 8-char prefix or full ULID\n\
         \treject <id> [reason]             reject\n\
         \tsearch <query> [--project SLUG] [--schema NAME] [-k N]\n\
         \tprofile                          counts (user_facts, feedback, ...)\n\
         \tprojects                         list projects\n\
         \tpatients                         list patients\n\
         \tdisputes                         list disputed pairs\n\
         \tentity <id>                      show entity body\n\
         \tdigest                           one-line summary\n\n\
         Env: AIM_FS_TENANT (default djabbat), AIM_FS_BIN, AIM_FS_ROOT"
    );
}
