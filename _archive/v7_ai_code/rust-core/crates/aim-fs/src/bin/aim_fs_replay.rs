//! aim-fs-replay — reconstruct entity state at a past timestamp.
//!
//! Verifies SPEC §13 audit-trail / replay claim — the events table is
//! append-only, so we can fold over events with `created_at <= T` to
//! produce the snapshot at time `T`.
//!
//! Algorithm (single-pass over events ordered by created_at ASC):
//!   * `created`        — insert entity into snapshot with status='pending'
//!                         (or 'active' if auto-approved, recorded by
//!                         `auto_approved` event with payload.auto=true)
//!   * `auto_approved`  — set status='active'
//!   * `approved`       — set status='active'
//!   * `rejected`       — set status='rejected'
//!   * `superseded`     — set status='superseded'
//!   * `disputed`       — set status='disputed'
//!   * `expired/deprecated/stale` — sweeper events; emitted only at run
//!                         time, not folded here (sweeper's UPDATE happens
//!                         outside the events log).
//!
//! Usage:
//!     aim-fs-replay [--aim-root <path>] [--until 2026-05-01T00:00:00Z]
//!                   [--tenant-id <uuid>] [--json]
//!
//! Output: human-readable status table or `--json` array of {id, status,
//! events_seen}.
use rusqlite::{params, Connection};
use std::collections::BTreeMap;
use std::path::PathBuf;

#[derive(Debug, Default, Clone)]
struct EntitySnap {
    id: String,
    status: String,
    schema: String,
    title: Option<String>,
    events_seen: u32,
    last_event_at: String,
}

fn main() -> anyhow::Result<()> {
    let mut aim_root: Option<PathBuf> = None;
    let mut until: Option<String> = None;
    let mut tenant: Option<String> = None;
    let mut as_json = false;

    let argv: Vec<String> = std::env::args().collect();
    let mut i = 1;
    while i < argv.len() {
        match argv[i].as_str() {
            "-h" | "--help" => {
                print_help();
                return Ok(());
            }
            "--aim-root" => {
                aim_root = argv.get(i + 1).map(PathBuf::from);
                i += 2;
            }
            "--until" => {
                until = argv.get(i + 1).cloned();
                i += 2;
            }
            "--tenant-id" => {
                tenant = argv.get(i + 1).cloned();
                i += 2;
            }
            "--json" => {
                as_json = true;
                i += 1;
            }
            other => anyhow::bail!("unknown arg: {other}"),
        }
    }
    let aim_root = aim_root
        .or_else(|| std::env::var("AIM_FS_ROOT").ok().map(PathBuf::from))
        .or_else(|| {
            std::env::var("HOME")
                .ok()
                .map(|h| PathBuf::from(h).join(".aim_fs"))
        })
        .ok_or_else(|| anyhow::anyhow!("--aim-root or AIM_FS_ROOT required"))?;
    let until = until.unwrap_or_else(|| chrono::Utc::now().to_rfc3339());
    let tenant = tenant.unwrap_or_else(|| {
        std::env::var("AIM_FS_TENANT").unwrap_or_else(|_| "djabbat".into())
    });

    let db = aim_root.join("_service").join("db").join("aim_fs.db");
    let conn = Connection::open(&db)?;
    let snap = replay(&conn, &tenant, &until)?;

    if as_json {
        let arr: Vec<serde_json::Value> = snap
            .values()
            .map(|e| {
                serde_json::json!({
                    "id": e.id,
                    "status": e.status,
                    "schema": e.schema,
                    "title": e.title,
                    "events_seen": e.events_seen,
                    "last_event_at": e.last_event_at,
                })
            })
            .collect();
        println!("{}", serde_json::to_string_pretty(&arr)?);
    } else {
        let mut by_status: BTreeMap<&str, u32> = BTreeMap::new();
        for e in snap.values() {
            *by_status.entry(e.status.as_str()).or_insert(0) += 1;
        }
        println!("Replay snapshot at: {until}");
        println!("Tenant: {tenant}");
        println!("Total entities: {}", snap.len());
        println!("By status:");
        for (st, n) in &by_status {
            println!("  {:12} {}", st, n);
        }
    }
    Ok(())
}

fn replay(
    conn: &Connection,
    tenant: &str,
    until: &str,
) -> anyhow::Result<BTreeMap<String, EntitySnap>> {
    // Pull metadata for all entities ever created in this tenant.
    let mut snap: BTreeMap<String, EntitySnap> = BTreeMap::new();
    let mut stmt = conn.prepare(
        "SELECT id, schema, title FROM entities WHERE tenant_id = ?1",
    )?;
    let rows = stmt.query_map(params![tenant], |r| {
        Ok((
            r.get::<_, String>(0)?,
            r.get::<_, String>(1)?,
            r.get::<_, Option<String>>(2)?,
        ))
    })?;
    for row in rows {
        let (id, schema, title) = row?;
        snap.insert(
            id.clone(),
            EntitySnap {
                id,
                status: "(unknown)".into(),
                schema,
                title,
                events_seen: 0,
                last_event_at: String::new(),
            },
        );
    }

    // Fold events ordered by created_at ASC, until cutoff.
    let mut stmt = conn.prepare(
        "SELECT entity_id, event_type, payload, created_at
         FROM events
         WHERE tenant_id = ?1 AND created_at <= ?2 AND entity_id IS NOT NULL
         ORDER BY created_at ASC",
    )?;
    let rows = stmt.query_map(params![tenant, until], |r| {
        Ok((
            r.get::<_, Option<String>>(0)?.unwrap_or_default(),
            r.get::<_, String>(1)?,
            r.get::<_, Option<String>>(2)?,
            r.get::<_, String>(3)?,
        ))
    })?;
    for row in rows {
        let (id, ev, _payload, at) = row?;
        if let Some(e) = snap.get_mut(&id) {
            e.events_seen += 1;
            e.last_event_at = at;
            apply_event(&mut e.status, &ev);
        }
    }
    // Drop entities that were never seen (created after cutoff) by checking
    // whether they got at least one event before `until`.
    snap.retain(|_, e| e.events_seen > 0);
    Ok(snap)
}

fn apply_event(status: &mut String, event_type: &str) {
    match event_type {
        "created" => {
            if status.as_str() == "(unknown)" {
                *status = "pending".into();
            }
        }
        "auto_approved" | "approved" => *status = "active".into(),
        "rejected" => *status = "rejected".into(),
        "superseded" => *status = "superseded".into(),
        "disputed" => *status = "disputed".into(),
        // sweeper events not currently in events table per-entity; if added
        // later, fold here:
        "expired" => *status = "expired".into(),
        "deprecated" => *status = "deprecated".into(),
        "cascade_stale" => *status = "stale".into(),
        _ => {} // ignore link_added, etc.
    }
}

fn print_help() {
    println!(
        "aim-fs-replay — reconstruct entity state at a past timestamp\n\n\
         USAGE: aim-fs-replay [--aim-root <path>] [--until <rfc3339>]\n\
                              [--tenant-id <uuid>] [--json]\n\n\
         Folds the events table (append-only) up to the cutoff, producing\n\
         the entity-state snapshot at that point in time. Verifies the\n\
         SPEC §13 audit-trail / replay invariant."
    );
}
