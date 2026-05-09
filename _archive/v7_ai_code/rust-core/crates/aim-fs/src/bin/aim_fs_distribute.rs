//! aim-fs-distribute — smart, content-aware import of Claude-style memory
//! and core .md files into the canonical AIM_FS layout.
//!
//! Improves over `aim-fs-migrate` (which only sets schema by filename prefix)
//! by:
//!   * detecting **project scope** from body content (LC_CDATA, FCLC, Ze, …)
//!     so each entity lands with `scope_project_ids` set;
//!   * detecting **dupes** via sha256 of normalised body so re-runs are
//!     idempotent;
//!   * splitting umbrella files (SESSION_STATE.md, CONTACTS.md, …) into
//!     per-section entities;
//!   * mapping per-subproject CLAUDE.md / MEMORY.md to that project's slug
//!     instead of dumping into the global pool.
//!
//! Sources walked by default:
//!   ~/.claude/projects/-home-oem/memory/*.md
//!   ~/Desktop/Claude/*.md      (excluding archive)
//!   ~/Desktop/Claude/{protocols,workflows,writing,audits}/*.md
//!   ~/Desktop/LongevityCommon/<sub>/{CLAUDE,MEMORY}.md
//!   /home/oem/CLAUDE.md
//!
//! Usage:
//!   aim-fs-distribute --aim-root ~/.aim_fs --tenant-id djabbat
//!                     [--dry-run] [--source <path> ...]
//!
//! Output: per-entity log + summary.  Manifest written to
//!     <aim_root>/_service/migrations/distribute_<epoch>.json

use aim_fs::{AimFs, ApprovalPolicy, NewEntity, Source};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, BTreeSet, HashSet};
use std::fs;
use std::path::{Path, PathBuf};

#[derive(Default)]
struct Args {
    aim_root: Option<PathBuf>,
    tenant_id: Option<String>,
    dry_run: bool,
    extra_sources: Vec<PathBuf>,
}

#[derive(Default, Serialize, Deserialize)]
struct DistributeManifest {
    imported: u64,
    duplicates: u64,
    skipped: u64,
    errors: Vec<String>,
    by_schema: BTreeMap<String, u64>,
    by_project_scope: BTreeMap<String, u64>,
}

fn main() {
    if let Err(e) = run() {
        eprintln!("aim-fs-distribute ERROR: {e}");
        std::process::exit(1);
    }
}

const HELP: &str = "\
aim-fs-distribute — smart import of Claude memory + core .md into AIM_FS

Required:
  --aim-root <path>       AIM_FS data root (created if missing)
  --tenant-id <uuid>      Tenant ID

Optional:
  --dry-run               Plan only — DB untouched
  --source <path>         Add an extra source directory (repeatable)

Default sources (each existing path used):
  ~/.claude/projects/-home-oem/memory/
  ~/Desktop/Claude/        (root + protocols/ workflows/ writing/ audits/)
  ~/Desktop/LongevityCommon/<sub>/{CLAUDE,MEMORY}.md
  /home/oem/CLAUDE.md
";

fn run() -> anyhow::Result<()> {
    let mut args = Args::default();
    let argv: Vec<String> = std::env::args().collect();
    let mut i = 1;
    while i < argv.len() {
        match argv[i].as_str() {
            "-h" | "--help" => {
                println!("{HELP}");
                return Ok(());
            }
            "--aim-root" => {
                args.aim_root = argv.get(i + 1).map(PathBuf::from);
                i += 2;
            }
            "--tenant-id" => {
                args.tenant_id = argv.get(i + 1).cloned();
                i += 2;
            }
            "--dry-run" => {
                args.dry_run = true;
                i += 1;
            }
            "--source" => {
                if let Some(p) = argv.get(i + 1) {
                    args.extra_sources.push(PathBuf::from(p));
                }
                i += 2;
            }
            other => anyhow::bail!("unknown arg: {other}\n{HELP}"),
        }
    }
    let aim_root = args
        .aim_root
        .or_else(|| std::env::var("AIM_FS_ROOT").ok().map(PathBuf::from))
        .ok_or_else(|| anyhow::anyhow!("--aim-root required"))?;
    let tenant_id = args
        .tenant_id
        .ok_or_else(|| anyhow::anyhow!("--tenant-id required"))?;

    let fs = AimFs::open(&aim_root)?;
    let policy = ApprovalPolicy {
        auto_approve_user_commands: true,
        auto_approve_observational_with_confidence_above: 1.0,
        auto_approve_service_events: true,
        require_approval_for: vec![],
        max_inactivity_days: 30,
    };

    let mut manifest = DistributeManifest::default();
    let mut seen_hashes: HashSet<String> = existing_hashes(&aim_root);
    println!("→ {} existing body hashes loaded for dedup", seen_hashes.len());

    for src in default_sources(&args.extra_sources) {
        if !src.exists() {
            continue;
        }
        println!("\n=== walking {} ===", src.display());
        walk_source(
            &fs,
            &tenant_id,
            &policy,
            &src,
            args.dry_run,
            &mut seen_hashes,
            &mut manifest,
        );
    }

    // Special: per-subproject CLAUDE.md / MEMORY.md.
    let lc_root = home().map(|h| h.join("Desktop/LongevityCommon"));
    if let Some(lc) = lc_root {
        if lc.is_dir() {
            println!("\n=== per-subproject CLAUDE/MEMORY ===");
            handle_lc_subprojects(
                &fs,
                &tenant_id,
                &policy,
                &lc,
                args.dry_run,
                &mut seen_hashes,
                &mut manifest,
            );
        }
    }

    // /home/oem/CLAUDE.md
    let user_claude = PathBuf::from("/home/oem/CLAUDE.md");
    if user_claude.is_file() {
        let _ = process_file(
            &fs,
            &tenant_id,
            &policy,
            &user_claude,
            "user_claude_md",
            args.dry_run,
            &mut seen_hashes,
            &mut manifest,
        );
    }

    write_manifest(&aim_root, &manifest)?;
    println!("\n=== SUMMARY ===");
    println!("  imported:   {}", manifest.imported);
    println!("  duplicates: {}", manifest.duplicates);
    println!("  skipped:    {}", manifest.skipped);
    println!("  errors:     {}", manifest.errors.len());
    println!("  by schema:");
    for (s, n) in &manifest.by_schema {
        println!("    {s:30} {n}");
    }
    println!("  by project scope:");
    for (s, n) in &manifest.by_project_scope {
        println!("    {s:30} {n}");
    }
    if !manifest.errors.is_empty() {
        for e in &manifest.errors {
            println!("    err: {e}");
        }
        std::process::exit(2);
    }
    Ok(())
}

fn home() -> Option<PathBuf> {
    std::env::var_os("HOME").map(PathBuf::from)
}

fn default_sources(extra: &[PathBuf]) -> Vec<PathBuf> {
    let mut out = vec![];
    if let Some(h) = home() {
        out.push(h.join(".claude/projects/-home-oem/memory"));
        out.push(h.join("Desktop/Claude"));
    }
    out.extend(extra.iter().cloned());
    out
}

/// Snapshot existing body sha256s so re-runs are idempotent.
fn existing_hashes(aim_root: &Path) -> HashSet<String> {
    let mut set = HashSet::new();
    let db = aim_root.join("_service/db/aim_fs.db");
    if !db.exists() {
        return set;
    }
    let conn = match rusqlite::Connection::open_with_flags(
        &db,
        rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY,
    ) {
        Ok(c) => c,
        Err(_) => return set,
    };
    let mut stmt = match conn.prepare("SELECT body FROM entities WHERE body IS NOT NULL") {
        Ok(s) => s,
        Err(_) => return set,
    };
    if let Ok(rows) = stmt.query_map([], |r| r.get::<_, String>(0)) {
        for row in rows.flatten() {
            set.insert(body_sha(&row));
        }
    }
    set
}

fn body_sha(body: &str) -> String {
    // Normalise: strip frontmatter + leading/trailing whitespace. The first
    // tuple element is the body, the second is the frontmatter map.
    let (body_only, _fm) = strip_frontmatter(body);
    let normalised = body_only.trim();
    let mut h = Sha256::new();
    h.update(normalised.as_bytes());
    format!("sha256:{}", hex::encode(h.finalize()))
}

fn walk_source(
    fs: &AimFs,
    tenant_id: &str,
    policy: &ApprovalPolicy,
    root: &Path,
    dry_run: bool,
    seen: &mut HashSet<String>,
    manifest: &mut DistributeManifest,
) {
    let walker = walkdir::WalkDir::new(root).max_depth(4);
    for entry in walker.into_iter().filter_map(|e| e.ok()) {
        if !entry.file_type().is_file() {
            continue;
        }
        let path = entry.path();
        let ext = path.extension().and_then(|s| s.to_str()).unwrap_or("");
        if ext != "md" {
            manifest.skipped += 1;
            continue;
        }
        let bucket = path
            .strip_prefix(root)
            .ok()
            .and_then(|p| p.parent())
            .and_then(|p| p.to_str())
            .filter(|s| !s.is_empty())
            .unwrap_or("root")
            .to_string();
        if let Err(e) = process_file(fs, tenant_id, policy, path, &bucket, dry_run, seen, manifest)
        {
            manifest.errors.push(format!("{}: {}", path.display(), e));
        }
    }
}

fn handle_lc_subprojects(
    fs: &AimFs,
    tenant_id: &str,
    policy: &ApprovalPolicy,
    lc: &Path,
    dry_run: bool,
    seen: &mut HashSet<String>,
    manifest: &mut DistributeManifest,
) {
    if let Ok(entries) = fs::read_dir(lc) {
        for entry in entries.flatten() {
            if !entry.file_type().map(|t| t.is_dir()).unwrap_or(false) {
                continue;
            }
            let dir = entry.path();
            let name = match dir.file_name().and_then(|n| n.to_str()) {
                Some(n) => n,
                None => continue,
            };
            if name.starts_with('_') {
                continue;
            }
            for fname in ["CLAUDE.md", "MEMORY.md"] {
                let p = dir.join(fname);
                if p.is_file() {
                    let bucket = format!("LC_{}", name);
                    let _ = process_file(
                        fs,
                        tenant_id,
                        policy,
                        &p,
                        &bucket,
                        dry_run,
                        seen,
                        manifest,
                    );
                }
            }
        }
    }
}

fn process_file(
    fs: &AimFs,
    tenant_id: &str,
    policy: &ApprovalPolicy,
    path: &Path,
    bucket: &str,
    dry_run: bool,
    seen: &mut HashSet<String>,
    manifest: &mut DistributeManifest,
) -> anyhow::Result<()> {
    let raw = fs::read_to_string(path)?;
    let (body, frontmatter) = strip_frontmatter(&raw);
    if body.trim().is_empty() {
        manifest.skipped += 1;
        return Ok(());
    }
    let sha = body_sha(body);
    if seen.contains(&sha) {
        manifest.duplicates += 1;
        return Ok(());
    }
    let fname = path.file_name().and_then(|s| s.to_str()).unwrap_or("");
    let schema = classify_schema(fname, &frontmatter, body, bucket);
    let title = extract_title(fname, &frontmatter, body);
    let project_scope = detect_project_scope(body, bucket, fname);
    let tags = extract_tags(&frontmatter, body, bucket);
    let confidence = if frontmatter.is_empty() { 0.7 } else { 0.95 };

    if dry_run {
        println!(
            "  PLAN  {schema:24} ← {} (bucket={bucket}, scope={:?})",
            path.file_name().unwrap_or_default().to_string_lossy(),
            project_scope
        );
        seen.insert(sha);
        manifest.imported += 1;
        bump(&mut manifest.by_schema, &schema);
        for p in &project_scope {
            bump(&mut manifest.by_project_scope, p);
        }
        if project_scope.is_empty() {
            bump(&mut manifest.by_project_scope, "(global)");
        }
        return Ok(());
    }

    let entity = NewEntity {
        schema: schema.clone(),
        schema_version: 1,
        title: Some(title),
        description: frontmatter.get("description").cloned(),
        body: Some(body.to_string()),
        source: Source::System,
        user_id: tenant_id.to_string(),
        session_id: None,
        llm_model: None,
        confidence: Some(confidence),
        requires_verification: false,
        scope_global: false,
        scope_user_ids: vec![tenant_id.to_string()],
        scope_project_ids: if project_scope.is_empty() {
            None
        } else {
            Some(project_scope.iter().cloned().collect())
        },
        scope_patient_ids: vec![],
        tags,
        decay_ttl_days: None,
        decay_on_expire: None,
        initial_links: vec![],
    };

    match fs.propose(
        tenant_id,
        entity,
        Some(&format!("distributed from {bucket}")),
        None,
        policy,
    ) {
        Ok(o) => {
            println!(
                "  ✓ {schema:24} {} → {} ({})",
                path.file_name().unwrap_or_default().to_string_lossy(),
                o.entity_id,
                o.entity_status.as_str()
            );
            seen.insert(sha);
            manifest.imported += 1;
            bump(&mut manifest.by_schema, &schema);
            for p in &project_scope {
                bump(&mut manifest.by_project_scope, p);
            }
            if project_scope.is_empty() {
                bump(&mut manifest.by_project_scope, "(global)");
            }
        }
        Err(e) => {
            // SchemaInvalid → skip rather than fail
            let msg = e.to_string();
            if msg.contains("SchemaInvalid") || msg.contains("schema validation") {
                manifest.skipped += 1;
            } else {
                manifest
                    .errors
                    .push(format!("{}: {}", path.display(), e));
            }
        }
    }
    Ok(())
}

fn bump(m: &mut BTreeMap<String, u64>, k: &str) {
    *m.entry(k.to_string()).or_insert(0) += 1;
}

fn extract_title(fname: &str, fm: &BTreeMap<String, String>, body: &str) -> String {
    if let Some(t) = fm.get("name").or_else(|| fm.get("title")) {
        return t.clone();
    }
    for line in body.lines() {
        let trimmed = line.trim_start_matches(|c: char| c == '#' || c.is_whitespace());
        if !trimmed.is_empty() && line.starts_with('#') {
            return trimmed.to_string();
        }
    }
    Path::new(fname)
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or("(untitled)")
        .to_string()
}

fn extract_tags(
    fm: &BTreeMap<String, String>,
    body: &str,
    bucket: &str,
) -> Vec<String> {
    let mut tags = BTreeSet::new();
    if let Some(t) = fm.get("tags") {
        for tok in t.split(',') {
            let v = tok.trim();
            if !v.is_empty() {
                tags.insert(v.to_string());
            }
        }
    }
    tags.insert("distributed".to_string());
    if !bucket.is_empty() && bucket != "root" {
        tags.insert(bucket.replace(['/', '\\'], "_"));
    }
    if body.contains("Bradford") || body.contains("PMID") || body.contains("DOI") {
        tags.insert("citation".into());
    }
    if body.contains("DeepSeek") || body.contains("Anthropic") || body.contains("LLM") {
        tags.insert("llm".into());
    }
    if body.contains("PhD") || body.contains("dissertation") {
        tags.insert("phd".into());
    }
    tags.into_iter().collect()
}

fn classify_schema(
    fname: &str,
    fm: &BTreeMap<String, String>,
    body: &str,
    bucket: &str,
) -> String {
    // 1. Explicit type in frontmatter wins.
    if let Some(t) = fm.get("type") {
        return match t.as_str() {
            "feedback" => "feedback_v1".into(),
            "user" => "user_fact_v1".into(),
            "contact" => "contact_v1".into(),
            "fact" => "fact_v1".into(),
            "reference" => "reference_v1".into(),
            "project" => "project_state_v1".into(),
            "format" => "format_v1".into(),
            "published" => "published_v1".into(),
            other => format!("{}_v1", other),
        };
    }
    // 2. Filename prefix (Claude convention).
    let lower = fname.to_lowercase();
    for (prefix, schema) in [
        ("feedback_", "feedback_v1"),
        ("project_", "project_state_v1"),
        ("user_", "user_fact_v1"),
        ("contact_", "contact_v1"),
        ("fact_", "fact_v1"),
        ("reference_", "reference_v1"),
        ("format_", "format_v1"),
        ("published_", "published_v1"),
        ("publications", "publications_v1"),
        ("pubmed", "publications_v1"),
        ("session_state", "session_state_v1"),
        ("audit_", "audit_v1"),
    ] {
        if lower.starts_with(prefix) {
            return schema.to_string();
        }
    }
    // 3. Bucket-based heuristics (whole-file CLAUDE.md / MEMORY.md per project).
    if bucket.starts_with("LC_") {
        return "project_state_v1".into();
    }
    if fname == "CLAUDE.md" || fname == "MEMORY.md" {
        return "project_state_v1".into();
    }
    // 4. Content-based.
    let l = body.to_lowercase();
    if l.contains("contact") && (l.contains("@") || l.contains("phone")) {
        return "contact_v1".into();
    }
    if lower.starts_with("audit") {
        return "audit_v1".into();
    }
    if l.contains("todo") && l.contains("- [ ]") {
        return "todo_v1".into();
    }
    if lower == "user_claude_md" {
        return "user_directive_v1".into();
    }
    "fact_v1".into()
}

const KNOWN_PROJECTS: &[(&str, &[&str])] = &[
    ("LC_CDATA", &["LC_CDATA", "CDATA", "centriolar damage"]),
    ("LC_MCOA", &["LC_MCOA", "MCOA", "Multi-Counter Architecture"]),
    ("LC_BioSense", &["LC_BioSense", "BioSense"]),
    ("LC_FCLC", &["LC_FCLC", "FCLC", "Federated Clinical Longevity"]),
    ("LC_Ze", &["LC_Ze ", "Ze Theory", "Ze theory", "v*_active"]),
    ("LC_AIM", &["LC_AIM", "AIM v7", "aim-fs", "AIM_FS"]),
    ("LC_HAP", &["LC_HAP", "Hepato-Affective"]),
    ("LC_Telomere", &["LC_Telomere", "Telomere shortening"]),
    ("LC_MitoROS", &["LC_MitoROS", "MitoROS"]),
    ("LC_Proteostasis", &["LC_Proteostasis", "Proteostasis"]),
    ("LC_EpigeneticDrift", &["LC_EpigeneticDrift", "epigenetic drift"]),
    ("LC_Ontogenesis", &["LC_Ontogenesis", "Ontogenesis"]),
    ("LC_CytogeneticTree", &["LC_CytogeneticTree", "CytogeneticTree"]),
    ("LC_AutomatedMicroscopy", &["LC_AutomatedMicroscopy", "AutomatedMicroscopy"]),
    ("LC_MCOA_Ze", &["MCOA + Ze"]),
    ("PhD", &["PhD/", "PhD UNED", "PhD UJ", "PhD UNISA", "PhD OUC"]),
    ("Marketing_JabaEkimi", &["JabaEkimi", "DrJaba"]),
    ("Marketing_Books", &["Marketing/Books"]),
    ("GLA_Annals", &["Annals of Rejuvenation"]),
    ("Iqalto_Aqtivirebuli", &["Aqtivirebuli", "Iqalto/Aqtivirebuli"]),
    ("Sulkalmakhi", &["Sulkalmakhi"]),
    ("Regenesis", &["Regenesis"]),
    ("WLRAbastumani", &["WLRAbastumani"]),
];

fn detect_project_scope(body: &str, bucket: &str, fname: &str) -> Vec<String> {
    let mut found = BTreeSet::new();
    // Bucket-based primary scope.
    if let Some(slug) = bucket.strip_prefix("LC_") {
        found.insert(format!("LC_{}", slug));
    }
    let l = body.to_lowercase();
    let f = fname.to_lowercase();
    for (slug, needles) in KNOWN_PROJECTS {
        for n in *needles {
            if body.contains(n)
                || l.contains(&n.to_lowercase())
                || f.contains(&n.to_lowercase())
            {
                found.insert(slug.to_string());
                break;
            }
        }
    }
    found.into_iter().collect()
}

fn strip_frontmatter(raw: &str) -> (&str, BTreeMap<String, String>) {
    let mut map = BTreeMap::new();
    let trimmed = raw.trim_start_matches('\u{FEFF}');
    if !trimmed.starts_with("---\n") && !trimmed.starts_with("---\r\n") {
        return (raw, map);
    }
    let after = &trimmed[4..];
    if let Some(end) = after.find("\n---\n").or_else(|| after.find("\n---\r\n")) {
        let fm = &after[..end];
        for line in fm.lines() {
            if let Some((k, v)) = line.split_once(':') {
                map.insert(
                    k.trim().to_string(),
                    v.trim().trim_matches('"').to_string(),
                );
            }
        }
        let body_start = end + "\n---\n".len();
        return (&after[body_start.min(after.len())..], map);
    }
    (raw, map)
}

fn write_manifest(aim_root: &Path, m: &DistributeManifest) -> anyhow::Result<()> {
    let dir = aim_root.join("_service").join("migrations");
    fs::create_dir_all(&dir)?;
    let path = dir.join(format!(
        "distribute_{}.json",
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_secs())
            .unwrap_or(0)
    ));
    fs::write(path, serde_json::to_string_pretty(m)?)?;
    Ok(())
}
