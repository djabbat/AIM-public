//! aim-fs-export — dump every active entity to a markdown tree.
//!
//! Useful for:
//!   * verifying what's in AIM_FS (look at the files);
//!   * version-controlling the memory contents (`git add export/`);
//!   * portability — humans/other systems can read plain markdown.
//!
//! Layout under `<out>/`:
//!
//!   _by_schema/<schema>/<short_id>__<title-slug>.md
//!   _by_project/<project_slug>/<schema>/<short_id>__<title-slug>.md
//!   _index.md                — index of every entity by schema
//!
//! Each .md file has full frontmatter + body. Markdown bodies are written
//! verbatim (already markdown). Other bodies are dropped under a fenced
//! code block.
//!
//! Usage:
//!   aim-fs-export --aim-root ~/.aim_fs --tenant-id djabbat --out ~/aim_fs_export
//!
//! Idempotent: deletes existing `<out>` first if `--clean`.

use rusqlite::Connection;
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};

#[derive(Default, Serialize, Deserialize)]
struct ExportSummary {
    written: u64,
    skipped: u64,
    by_schema: BTreeMap<String, u64>,
    by_project: BTreeMap<String, u64>,
    out_dir: String,
}

fn main() -> anyhow::Result<()> {
    let mut aim_root: Option<PathBuf> = None;
    let mut tenant: Option<String> = None;
    let mut out: Option<PathBuf> = None;
    let mut clean = false;
    let mut include_inactive = false;

    let argv: Vec<String> = std::env::args().collect();
    let mut i = 1;
    while i < argv.len() {
        match argv[i].as_str() {
            "-h" | "--help" => {
                println!(
                    "aim-fs-export --aim-root <path> --tenant-id <uuid> --out <dir> [--clean] [--include-inactive]"
                );
                return Ok(());
            }
            "--aim-root" => {
                aim_root = argv.get(i + 1).map(PathBuf::from);
                i += 2;
            }
            "--tenant-id" => {
                tenant = argv.get(i + 1).cloned();
                i += 2;
            }
            "--out" => {
                out = argv.get(i + 1).map(PathBuf::from);
                i += 2;
            }
            "--clean" => {
                clean = true;
                i += 1;
            }
            "--include-inactive" => {
                include_inactive = true;
                i += 1;
            }
            other => anyhow::bail!("unknown arg: {other}"),
        }
    }
    let aim_root = aim_root
        .or_else(|| std::env::var("AIM_FS_ROOT").ok().map(PathBuf::from))
        .ok_or_else(|| anyhow::anyhow!("--aim-root required"))?;
    let tenant = tenant.ok_or_else(|| anyhow::anyhow!("--tenant-id required"))?;
    let out = out.ok_or_else(|| anyhow::anyhow!("--out required"))?;
    if clean && out.exists() {
        fs::remove_dir_all(&out)?;
    }
    fs::create_dir_all(&out)?;

    let db = aim_root.join("_service").join("db").join("aim_fs.db");
    let conn = Connection::open(&db)?;
    let mut summary = ExportSummary {
        out_dir: out.display().to_string(),
        ..Default::default()
    };

    let mut stmt = conn.prepare(
        "SELECT id, schema, status, title, description, body, source, user_id,
                session_id, llm_model, confidence, requires_verification,
                scope_global, scope_user_ids, scope_project_ids, scope_patient_ids,
                tags, decay_ttl_days, decay_expires_at, decay_on_expire,
                version, created_at, updated_at
         FROM entities
         WHERE tenant_id = ?1
           AND (status = 'active' OR ?2 = 1)
         ORDER BY schema, created_at DESC",
    )?;
    let rows = stmt.query_map(rusqlite::params![tenant, include_inactive as i64], |r| {
        Ok(EntityRow {
            id: r.get(0)?,
            schema: r.get(1)?,
            status: r.get(2)?,
            title: r.get(3)?,
            description: r.get(4)?,
            body: r.get(5)?,
            source: r.get(6)?,
            user_id: r.get(7)?,
            session_id: r.get(8)?,
            llm_model: r.get(9)?,
            confidence: r.get(10)?,
            requires_verification: r.get::<_, i64>(11)? != 0,
            scope_global: r.get::<_, i64>(12)? != 0,
            scope_user_ids: r.get(13)?,
            scope_project_ids: r.get(14)?,
            scope_patient_ids: r.get(15)?,
            tags: r.get(16)?,
            decay_ttl_days: r.get(17)?,
            decay_expires_at: r.get(18)?,
            decay_on_expire: r.get(19)?,
            version: r.get(20)?,
            created_at: r.get(21)?,
            updated_at: r.get(22)?,
        })
    })?;

    let mut all: Vec<EntityRow> = Vec::new();
    for row in rows {
        all.push(row?);
    }

    for e in &all {
        let body_md = render_md(e);
        let slug = title_slug(e.title.as_deref().unwrap_or("untitled"));
        let short = e.id.chars().take(12).collect::<String>();
        let fname = format!("{}__{}.md", short, slug);

        // _by_schema/<schema>/<file>
        let by_schema_dir = out.join("_by_schema").join(&e.schema);
        fs::create_dir_all(&by_schema_dir)?;
        fs::write(by_schema_dir.join(&fname), &body_md)?;

        // _by_project/<project>/<schema>/<file>  for each project in scope
        if let Some(scope) = e
            .scope_project_ids
            .as_deref()
            .and_then(|s| serde_json::from_str::<Vec<String>>(s).ok())
        {
            for proj in scope {
                let dir = out.join("_by_project").join(&proj).join(&e.schema);
                fs::create_dir_all(&dir)?;
                fs::write(dir.join(&fname), &body_md)?;
                bump(&mut summary.by_project, &proj);
            }
        } else {
            bump(&mut summary.by_project, "_global");
            let dir = out.join("_by_project").join("_global").join(&e.schema);
            fs::create_dir_all(&dir)?;
            fs::write(dir.join(&fname), &body_md)?;
        }
        bump(&mut summary.by_schema, &e.schema);
        summary.written += 1;
    }

    // _index.md
    let mut idx = String::new();
    idx.push_str(&format!(
        "# AIM_FS export — tenant `{}` — {} entities\n\nGenerated {}\n\n",
        tenant,
        summary.written,
        chrono::Utc::now().to_rfc3339()
    ));
    idx.push_str("## By schema\n");
    for (k, v) in &summary.by_schema {
        idx.push_str(&format!("- **{k}** — {v}\n"));
    }
    idx.push_str("\n## By project\n");
    for (k, v) in &summary.by_project {
        idx.push_str(&format!("- **{k}** — {v}\n"));
    }
    fs::write(out.join("_index.md"), idx)?;

    println!(
        "✓ exported {} entities to {}",
        summary.written,
        summary.out_dir
    );
    println!("  by schema:");
    for (k, v) in &summary.by_schema {
        println!("    {k:30} {v}");
    }
    Ok(())
}

#[derive(Debug)]
struct EntityRow {
    id: String,
    schema: String,
    status: String,
    title: Option<String>,
    description: Option<String>,
    body: Option<String>,
    source: String,
    user_id: String,
    session_id: Option<String>,
    llm_model: Option<String>,
    confidence: Option<f64>,
    requires_verification: bool,
    scope_global: bool,
    scope_user_ids: Option<String>,
    scope_project_ids: Option<String>,
    scope_patient_ids: Option<String>,
    tags: Option<String>,
    decay_ttl_days: Option<i64>,
    decay_expires_at: Option<String>,
    decay_on_expire: Option<String>,
    version: i64,
    created_at: String,
    updated_at: String,
}

fn render_md(e: &EntityRow) -> String {
    let mut out = String::new();
    out.push_str("---\n");
    out.push_str(&format!("id: {}\n", e.id));
    out.push_str(&format!("schema: {}\n", e.schema));
    out.push_str(&format!("status: {}\n", e.status));
    if let Some(t) = &e.title {
        out.push_str(&format!("title: {}\n", yaml_quote(t)));
    }
    if let Some(d) = &e.description {
        out.push_str(&format!("description: {}\n", yaml_quote(d)));
    }
    out.push_str(&format!("source: {}\n", e.source));
    out.push_str(&format!("user_id: {}\n", e.user_id));
    if let Some(s) = &e.session_id {
        out.push_str(&format!("session_id: {}\n", s));
    }
    if let Some(m) = &e.llm_model {
        out.push_str(&format!("llm_model: {}\n", m));
    }
    if let Some(c) = e.confidence {
        out.push_str(&format!("confidence: {}\n", c));
    }
    out.push_str(&format!("requires_verification: {}\n", e.requires_verification));
    out.push_str(&format!("scope_global: {}\n", e.scope_global));
    if let Some(t) = &e.tags {
        if let Ok(v) = serde_json::from_str::<Vec<String>>(t) {
            if !v.is_empty() {
                out.push_str(&format!("tags: [{}]\n", v.join(", ")));
            }
        }
    }
    if let Some(s) = &e.scope_project_ids {
        out.push_str(&format!("scope_project_ids: {}\n", s));
    }
    if let Some(s) = &e.scope_patient_ids {
        out.push_str(&format!("scope_patient_ids: {}\n", s));
    }
    if let Some(d) = e.decay_ttl_days {
        out.push_str(&format!("decay_ttl_days: {}\n", d));
    }
    if let Some(e2) = &e.decay_expires_at {
        out.push_str(&format!("decay_expires_at: {}\n", e2));
    }
    if let Some(d) = &e.decay_on_expire {
        out.push_str(&format!("decay_on_expire: {}\n", d));
    }
    out.push_str(&format!("version: {}\n", e.version));
    out.push_str(&format!("created_at: {}\n", e.created_at));
    out.push_str(&format!("updated_at: {}\n", e.updated_at));
    out.push_str("---\n\n");
    if let Some(b) = &e.body {
        out.push_str(b);
        if !b.ends_with('\n') {
            out.push('\n');
        }
    }
    out
}

fn yaml_quote(s: &str) -> String {
    if s.contains(':')
        || s.contains('"')
        || s.contains('\n')
        || s.starts_with(' ')
        || s.starts_with('-')
    {
        format!("\"{}\"", s.replace('"', "\\\""))
    } else {
        s.to_string()
    }
}

fn title_slug(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    let mut last_was_dash = false;
    for c in s.chars().take(60) {
        if c.is_ascii_alphanumeric() || c == '_' {
            out.push(c.to_ascii_lowercase());
            last_was_dash = false;
        } else if !last_was_dash && !out.is_empty() {
            out.push('-');
            last_was_dash = true;
        }
    }
    while out.ends_with('-') {
        out.pop();
    }
    if out.is_empty() {
        "untitled".to_string()
    } else {
        out
    }
}

fn bump(m: &mut BTreeMap<String, u64>, k: &str) {
    *m.entry(k.to_string()).or_insert(0) += 1;
}
