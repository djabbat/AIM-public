//! aim-fs-fsck — integrity / consistency checker for an AIM_FS data root.
//!
//! Read-only diagnostic.  Reports issues but does not modify the DB or files.
//!
//! Checks:
//!   1. SQLite file exists and is openable.
//!   2. FTS5 virtual table is in sync with `entities` (counts match).
//!   3. No orphaned proposals (entity_id references missing entities).
//!   4. No orphaned links (source_id or target_id references missing entities).
//!   5. No stale `idempotency` rows in `processing` state older than 5 minutes.
//!   6. No `_service/tmp/*` files (atomic-write residue).
//!   7. Project directories under users/<u>/projects/ have CONCEPT.md.
//!   8. Patient directories under users/<u>/patients/ have ANAMNESIS.md or
//!      identity.toml.
//!
//! Exit code 0 = clean, 1 = issues found, 2 = fatal (can't open DB).

use rusqlite::Connection;
use std::path::{Path, PathBuf};

fn main() -> std::process::ExitCode {
    let mut aim_root: Option<PathBuf> = None;
    let argv: Vec<String> = std::env::args().collect();
    let mut i = 1;
    while i < argv.len() {
        match argv[i].as_str() {
            "-h" | "--help" => {
                println!("aim-fs-fsck [--aim-root <path>]");
                return std::process::ExitCode::SUCCESS;
            }
            "--aim-root" => {
                aim_root = argv.get(i + 1).map(PathBuf::from);
                i += 2;
            }
            other => {
                eprintln!("unknown arg: {other}");
                return std::process::ExitCode::from(2);
            }
        }
    }
    let aim_root = aim_root
        .or_else(|| std::env::var("AIM_FS_ROOT").ok().map(PathBuf::from))
        .or_else(|| {
            std::env::var("HOME")
                .ok()
                .map(|h| PathBuf::from(h).join(".aim_fs"))
        });
    let aim_root = match aim_root {
        Some(p) => p,
        None => {
            eprintln!("--aim-root or AIM_FS_ROOT or $HOME required");
            return std::process::ExitCode::from(2);
        }
    };

    println!("→ checking {}", aim_root.display());
    let mut issues = Vec::new();

    let db = aim_root.join("_service").join("db").join("aim_fs.db");
    if !db.is_file() {
        eprintln!("✗ {} missing", db.display());
        return std::process::ExitCode::from(2);
    }
    let conn = match Connection::open_with_flags(
        &db,
        rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY,
    ) {
        Ok(c) => c,
        Err(e) => {
            eprintln!("✗ cannot open {}: {e}", db.display());
            return std::process::ExitCode::from(2);
        }
    };

    // 1. FTS5 sync.
    let entities_n: i64 = conn
        .query_row("SELECT COUNT(*) FROM entities", [], |r| r.get(0))
        .unwrap_or(-1);
    let fts_n: i64 = conn
        .query_row("SELECT COUNT(*) FROM entities_fts", [], |r| r.get(0))
        .unwrap_or(-1);
    println!("  entities in DB:     {entities_n}");
    println!("  entities in FTS5:   {fts_n}");
    if entities_n != fts_n {
        issues.push(format!(
            "FTS5 desynced: entities={entities_n}, fts={fts_n} (Δ={})",
            entities_n - fts_n
        ));
    }

    // 2. Orphaned proposals.
    let orphan_props: i64 = conn
        .query_row(
            "SELECT COUNT(*) FROM proposals p \
             LEFT JOIN entities e ON e.id = p.entity_id \
             WHERE e.id IS NULL",
            [],
            |r| r.get(0),
        )
        .unwrap_or(0);
    if orphan_props > 0 {
        issues.push(format!("{orphan_props} orphaned proposals (entity missing)"));
    }

    // 3. Orphaned links.
    let orphan_links: i64 = conn
        .query_row(
            "SELECT COUNT(*) FROM links l \
             LEFT JOIN entities a ON a.id = l.source_id \
             LEFT JOIN entities b ON b.id = l.target_id \
             WHERE a.id IS NULL OR b.id IS NULL",
            [],
            |r| r.get(0),
        )
        .unwrap_or(0);
    if orphan_links > 0 {
        issues.push(format!("{orphan_links} orphaned links"));
    }

    // 4. Stale idempotency rows.
    let stale_idem: i64 = conn
        .query_row(
            "SELECT COUNT(*) FROM idempotency \
             WHERE status='processing' \
               AND datetime(created_at) < datetime('now','-5 minutes')",
            [],
            |r| r.get(0),
        )
        .unwrap_or(0);
    if stale_idem > 0 {
        issues.push(format!(
            "{stale_idem} stale idempotency rows in 'processing' state >5min"
        ));
    }

    // 5. tmp files.
    let tmp_dir = aim_root.join("_service").join("tmp");
    let tmp_n = if tmp_dir.is_dir() {
        std::fs::read_dir(&tmp_dir).map(|it| it.count()).unwrap_or(0)
    } else {
        0
    };
    if tmp_n > 0 {
        issues.push(format!("{tmp_n} files left in _service/tmp/ (atomic-write residue)"));
    }

    // 6. Project directories without CONCEPT.md.
    let mut projects_without_concept = Vec::new();
    let users_dir = aim_root.join("users");
    if users_dir.is_dir() {
        if let Ok(entries) = std::fs::read_dir(&users_dir) {
            for e in entries.flatten() {
                if !e.file_type().map(|t| t.is_dir()).unwrap_or(false) {
                    continue;
                }
                let projects_dir = e.path().join("projects");
                if !projects_dir.is_dir() {
                    continue;
                }
                if let Ok(projects) = std::fs::read_dir(&projects_dir) {
                    for p in projects.flatten() {
                        if !p.file_type().map(|t| t.is_dir()).unwrap_or(false) {
                            continue;
                        }
                        if !p.path().join("CONCEPT.md").is_file() {
                            projects_without_concept
                                .push(p.path().display().to_string());
                        }
                    }
                }
            }
        }
    }
    if !projects_without_concept.is_empty() {
        issues.push(format!(
            "{} project dirs missing CONCEPT.md",
            projects_without_concept.len()
        ));
        for p in &projects_without_concept {
            println!("    · {}", p);
        }
    }

    // 7. Patient directories without identity.toml or ANAMNESIS.md.
    let mut patients_missing_anamnesis = 0;
    if users_dir.is_dir() {
        if let Ok(entries) = std::fs::read_dir(&users_dir) {
            for e in entries.flatten() {
                let pdir = e.path().join("patients");
                if !pdir.is_dir() {
                    continue;
                }
                if let Ok(patients) = std::fs::read_dir(&pdir) {
                    for p in patients.flatten() {
                        if !p.file_type().map(|t| t.is_dir()).unwrap_or(false) {
                            continue;
                        }
                        if !p.path().join("identity.toml").is_file()
                            && !p.path().join("ANAMNESIS.md").is_file()
                        {
                            patients_missing_anamnesis += 1;
                        }
                    }
                }
            }
        }
    }
    if patients_missing_anamnesis > 0 {
        issues.push(format!(
            "{patients_missing_anamnesis} patient dirs missing identity.toml AND ANAMNESIS.md"
        ));
    }

    // 8. Schema sanity: no entities with NULL tenant_id.
    let bad_tenant: i64 = conn
        .query_row(
            "SELECT COUNT(*) FROM entities WHERE tenant_id IS NULL OR tenant_id = ''",
            [],
            |r| r.get(0),
        )
        .unwrap_or(0);
    if bad_tenant > 0 {
        issues.push(format!("{bad_tenant} entities with empty tenant_id"));
    }

    println!();
    if issues.is_empty() {
        println!("✓ all checks pass");
        std::process::ExitCode::SUCCESS
    } else {
        println!("✗ {} issue(s) found:", issues.len());
        for i in &issues {
            println!("  · {i}");
        }
        std::process::ExitCode::from(1)
    }
}

#[allow(dead_code)]
fn _unused(p: &Path) -> bool {
    p.is_dir()
}
