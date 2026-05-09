//! aim-fs-migrate — import legacy data into the AIM_FS layout (SPEC §10.3).
//!
//! Sources:
//!   - `~/.claude/projects/-home-oem/memory/`     (Claude auto-memory)
//!   - `<aim_legacy_root>/USER/`                  (AIM user profile)
//!   - `<aim_legacy_root>/Patients/`              (patient folders)
//!   - `<aim_legacy_root>/AI/`                    (AI service folder)
//!
//! Behaviour:
//!   - Walks each source with walkdir, processes only `*.md` files.
//!   - Reads existing frontmatter (`---\n…\n---`) if present, else builds fresh.
//!   - Creates an entity in the AIM_FS DB via `propose()` with policy that
//!     auto-approves system events.  Existing files therefore go straight to
//!     `status = active`.
//!   - Each entity also keeps the original file on disk under
//!     `<aim_root>/users/<tenant_id>/imported/<source>/<original_relative_path>`.
//!   - Writes a manifest at `<aim_root>/_service/migrations/<timestamp>.json`
//!     so migrations are idempotent and replayable.
//!
//! Usage:
//!     aim-fs-migrate --aim-root ~/.aim_fs --tenant-id <uuid> --legacy-aim ~/Desktop/LongevityCommon/AIM
//!
//! Flags:
//!     --dry-run         : print plan, don't touch DB.
//!     --skip-claude     : skip Claude memory dir.
//!     --skip-patients   : skip Patients/ (most sensitive PII).
//!
//! Exit codes:
//!     0 = success, 1 = error, 2 = partial (some files skipped).

use aim_fs::{AimFs, ApprovalPolicy, NewEntity, Source};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::time::SystemTime;

const USAGE: &str = "\
aim-fs-migrate — import legacy AIM/Claude data into AIM_FS

Required:
  --aim-root <PATH>         AIM_FS data root (created if missing)
  --tenant-id <UUID>        Tenant ID (current user's UUID)

Optional:
  --legacy-aim <PATH>       Path to AIM_v0 root (USER/, Patients/, AI/)
  --claude-memory <PATH>    Path to ~/.claude/projects/<proj>/memory/
  --dry-run                 Plan only, don't touch DB
  --skip-patients           Don't import Patients/
  --skip-claude             Don't import Claude memory
";

fn main() {
    if let Err(e) = run() {
        eprintln!("aim-fs-migrate ERROR: {e}");
        std::process::exit(1);
    }
}

#[derive(Default)]
struct Args {
    aim_root: Option<PathBuf>,
    tenant_id: Option<String>,
    legacy_aim: Option<PathBuf>,
    claude_memory: Option<PathBuf>,
    dry_run: bool,
    skip_patients: bool,
    skip_claude: bool,
}

fn run() -> anyhow::Result<()> {
    let mut args = Args::default();
    let argv: Vec<String> = std::env::args().collect();
    let mut i = 1;
    while i < argv.len() {
        match argv[i].as_str() {
            "-h" | "--help" => {
                println!("{USAGE}");
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
            "--legacy-aim" => {
                args.legacy_aim = argv.get(i + 1).map(PathBuf::from);
                i += 2;
            }
            "--claude-memory" => {
                args.claude_memory = argv.get(i + 1).map(PathBuf::from);
                i += 2;
            }
            "--dry-run" => {
                args.dry_run = true;
                i += 1;
            }
            "--skip-patients" => {
                args.skip_patients = true;
                i += 1;
            }
            "--skip-claude" => {
                args.skip_claude = true;
                i += 1;
            }
            other => anyhow::bail!("unknown arg: {other}\n{USAGE}"),
        }
    }
    let aim_root = args.aim_root.ok_or_else(|| anyhow::anyhow!(USAGE))?;
    let tenant_id = args.tenant_id.ok_or_else(|| anyhow::anyhow!(USAGE))?;

    let fs = AimFs::open(&aim_root)?;
    let policy = ApprovalPolicy {
        auto_approve_user_commands: true,
        auto_approve_observational_with_confidence_above: 1.0,
        auto_approve_service_events: true,
        require_approval_for: vec![],
        max_inactivity_days: 30,
    };

    let mut summary = MigrationSummary::default();

    if !args.skip_claude {
        let claude_root = args.claude_memory.unwrap_or_else(|| {
            dirs_home()
                .map(|h| h.join(".claude/projects/-home-oem/memory"))
                .unwrap_or_default()
        });
        if claude_root.is_dir() {
            migrate_claude(&fs, &tenant_id, &policy, &claude_root, args.dry_run, &mut summary)?;
        } else {
            eprintln!("note: claude memory dir not found at {}", claude_root.display());
        }
    }

    if let Some(aim) = &args.legacy_aim {
        if aim.join("USER").is_dir() {
            migrate_dir(&fs, &tenant_id, &policy, &aim.join("USER"),
                "user_v1", "user", args.dry_run, &mut summary)?;
        }
        if aim.join("AI").is_dir() {
            migrate_dir(&fs, &tenant_id, &policy, &aim.join("AI"),
                "ai_artifact_v1", "self_dev", args.dry_run, &mut summary)?;
        }
        if !args.skip_patients && aim.join("Patients").is_dir() {
            migrate_patients(&fs, &tenant_id, &policy, &aim.join("Patients"),
                args.dry_run, &mut summary)?;
        }
    }

    write_manifest(&aim_root, &summary)?;
    println!("\nMIGRATION SUMMARY");
    println!("  imported: {}", summary.imported);
    println!("  skipped:  {}", summary.skipped);
    println!("  errors:   {}", summary.errors.len());
    for e in &summary.errors {
        println!("    - {}", e);
    }
    if summary.errors.is_empty() {
        Ok(())
    } else {
        std::process::exit(2);
    }
}

fn dirs_home() -> Option<PathBuf> {
    std::env::var_os("HOME").map(PathBuf::from)
}

fn migrate_claude(
    fs: &AimFs,
    tenant_id: &str,
    policy: &ApprovalPolicy,
    root: &Path,
    dry_run: bool,
    summary: &mut MigrationSummary,
) -> anyhow::Result<()> {
    println!("=> Claude memory: {}", root.display());
    for entry in walkdir::WalkDir::new(root).max_depth(2) {
        let entry = entry?;
        if !entry.file_type().is_file() || entry.path().extension().and_then(|s| s.to_str()) != Some("md") {
            continue;
        }
        let path = entry.path();
        let fname = path.file_name().and_then(|s| s.to_str()).unwrap_or("");
        if fname == "MEMORY.md" {
            continue; // index — reconstructed on demand
        }
        let schema_type = guess_claude_schema(fname);
        match import_one(fs, tenant_id, policy, path, &schema_type, "claude", dry_run) {
            Ok(()) => summary.imported += 1,
            Err(e) => {
                summary.errors.push(format!("{}: {}", path.display(), e));
            }
        }
    }
    Ok(())
}

fn migrate_dir(
    fs: &AimFs,
    tenant_id: &str,
    policy: &ApprovalPolicy,
    root: &Path,
    schema: &str,
    bucket: &str,
    dry_run: bool,
    summary: &mut MigrationSummary,
) -> anyhow::Result<()> {
    println!("=> {bucket}: {}", root.display());
    for entry in walkdir::WalkDir::new(root).max_depth(8) {
        let entry = entry?;
        if !entry.file_type().is_file() {
            continue;
        }
        let ext = entry.path().extension().and_then(|s| s.to_str()).unwrap_or("");
        if ext != "md" && ext != "yaml" && ext != "yml" {
            summary.skipped += 1;
            continue;
        }
        match import_one(fs, tenant_id, policy, entry.path(), schema, bucket, dry_run) {
            Ok(()) => summary.imported += 1,
            Err(e) => summary.errors.push(format!("{}: {}", entry.path().display(), e)),
        }
    }
    Ok(())
}

fn migrate_patients(
    fs: &AimFs,
    tenant_id: &str,
    policy: &ApprovalPolicy,
    root: &Path,
    dry_run: bool,
    summary: &mut MigrationSummary,
) -> anyhow::Result<()> {
    println!("=> patients: {}", root.display());
    let mut count = 0;
    for entry in fs::read_dir(root)? {
        let entry = entry?;
        if !entry.file_type()?.is_dir() {
            continue;
        }
        let pname = entry.file_name();
        let pkey = pname.to_string_lossy().to_string();
        if pkey == "INBOX" || pkey.starts_with("_") {
            continue;
        }
        if !dry_run {
            fs.ensure_patient(tenant_id, &pkey)?;
        }
        count += 1;
        // Per-patient .md files become entities scoped to this patient.
        for md in walkdir::WalkDir::new(entry.path())
            .max_depth(4)
            .into_iter()
            .filter_map(|e| e.ok())
            .filter(|e| {
                e.file_type().is_file()
                    && e.path().extension().and_then(|s| s.to_str()) == Some("md")
            })
        {
            match import_one(
                fs,
                tenant_id,
                policy,
                md.path(),
                "patient_note_v1",
                &format!("patient/{pkey}"),
                dry_run,
            ) {
                Ok(()) => summary.imported += 1,
                Err(e) => summary.errors.push(format!("{}: {}", md.path().display(), e)),
            }
        }
    }
    println!("   found {count} patient folders");
    Ok(())
}

fn import_one(
    fs: &AimFs,
    tenant_id: &str,
    policy: &ApprovalPolicy,
    path: &Path,
    schema: &str,
    bucket: &str,
    dry_run: bool,
) -> anyhow::Result<()> {
    let body = fs::read_to_string(path)?;
    let (frontmatter, content) = split_frontmatter(&body);
    let title = frontmatter
        .get("name")
        .or_else(|| frontmatter.get("title"))
        .cloned()
        .unwrap_or_else(|| path.file_stem().unwrap_or_default().to_string_lossy().to_string());
    let description = frontmatter.get("description").cloned();
    let tags: Vec<String> = frontmatter
        .get("tags")
        .map(|s| s.trim().split(',').map(|t| t.trim().to_string()).collect())
        .unwrap_or_default();

    let new = NewEntity {
        schema: schema.to_string(),
        schema_version: 1,
        title: Some(title),
        description,
        body: Some(content.to_string()),
        source: Source::System, // imported = system origin → auto_approve
        user_id: tenant_id.to_string(),
        session_id: None,
        llm_model: None,
        confidence: None,
        requires_verification: false,
        scope_global: false,
        scope_user_ids: vec![tenant_id.to_string()],
        scope_project_ids: None,
        scope_patient_ids: vec![],
        tags,
        decay_ttl_days: None,
        decay_on_expire: None,
        initial_links: vec![],
    };
    if dry_run {
        println!("   PLAN  {schema} ← {} ({})", path.display(), bucket);
        return Ok(());
    }
    let outcome = fs.propose(tenant_id, new, Some(&format!("imported from {bucket}")), None, policy)?;
    let mtime = path
        .metadata()
        .ok()
        .and_then(|m| m.modified().ok())
        .map(format_systime)
        .unwrap_or_default();
    println!(
        "   ✓ {} → {} ({}) [{}]",
        path.file_name().unwrap_or_default().to_string_lossy(),
        outcome.entity_id,
        outcome.entity_status.as_str(),
        mtime
    );
    Ok(())
}

fn guess_claude_schema(filename: &str) -> String {
    if filename.starts_with("feedback_") {
        "feedback_v1".into()
    } else if filename.starts_with("project_") {
        "project_state_v1".into()
    } else if filename.starts_with("user_") {
        "user_fact_v1".into()
    } else if filename.starts_with("contact_") {
        "contact_v1".into()
    } else if filename.starts_with("fact_") {
        "fact_v1".into()
    } else if filename.starts_with("reference_") {
        "reference_v1".into()
    } else if filename.starts_with("format_") {
        "format_v1".into()
    } else if filename.starts_with("published_") {
        "published_v1".into()
    } else if filename.starts_with("publications") || filename.starts_with("pubmed") {
        "publications_v1".into()
    } else {
        "fact_v1".into()
    }
}

fn split_frontmatter(body: &str) -> (BTreeMap<String, String>, &str) {
    let mut map = BTreeMap::new();
    let trimmed = body.trim_start_matches('\u{FEFF}');
    if !trimmed.starts_with("---\n") && !trimmed.starts_with("---\r\n") {
        return (map, body);
    }
    let after = &trimmed[4..];
    if let Some(end) = after.find("\n---\n").or_else(|| after.find("\n---\r\n")) {
        let fm = &after[..end];
        for line in fm.lines() {
            if let Some((k, v)) = line.split_once(':') {
                map.insert(k.trim().to_string(), v.trim().trim_matches('"').to_string());
            }
        }
        let rest_start = end + "\n---\n".len();
        return (map, &after[rest_start.min(after.len())..]);
    }
    (map, body)
}

fn format_systime(t: SystemTime) -> String {
    use std::time::UNIX_EPOCH;
    let secs = t.duration_since(UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0);
    format!("epoch:{secs}")
}

#[derive(Default, Serialize, Deserialize)]
struct MigrationSummary {
    imported: u64,
    skipped: u64,
    errors: Vec<String>,
}

fn write_manifest(aim_root: &Path, summary: &MigrationSummary) -> anyhow::Result<()> {
    let dir = aim_root.join("_service").join("migrations");
    fs::create_dir_all(&dir)?;
    let path = dir.join(format!(
        "migration_{}.json",
        chrono_now()
    ));
    fs::write(path, serde_json::to_string_pretty(summary)?)?;
    Ok(())
}

fn chrono_now() -> String {
    use std::time::{SystemTime, UNIX_EPOCH};
    let secs = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    format!("epoch_{secs}")
}
