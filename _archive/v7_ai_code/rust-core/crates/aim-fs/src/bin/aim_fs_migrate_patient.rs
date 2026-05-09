//! aim-fs-migrate-patient — careful PII-aware import of legacy
//! `Patients/<Surname>_<Name>_<DOB>/` folders into AIM_FS Phase B.0.5
//! encrypted layout.
//!
//! Workflow per patient folder:
//!
//!   1. Parse `<Surname>_<Name>_<DOB>` from the directory name; skip if
//!      the convention isn't met (e.g. `INBOX`, `anonymous`, `C1`–`C4`).
//!   2. Compute pseudonym = HMAC-SHA256(master_key, surname‖name‖DOB)[:16].
//!   3. Create `<aim_root>/users/<doctor>/patients/<pseudonym>/` with the
//!      standard subdirs (visits/, recipes/, notes/, _meta/, _inbox/).
//!   4. Generate plaintext identity.toml + ANAMNESIS.md, then encrypt them
//!      via AES-256-GCM and write `.enc` files alongside (Phase B.0.5
//!      stores ciphertext-only; readers detect AENC magic).
//!   5. Walk the legacy directory and copy every `*.md` / `*.txt` into the
//!      new patient folder under `imported/`, encrypted.
//!   6. Insert a `contact_v1` entity into AIM_FS DB scoped to the new
//!      pseudonym (NOT to the surname/name) so search hits don't leak PII.
//!
//! Refuses to run without `--accept-pii` flag — protects from accidental
//! invocation.
//!
//! Usage:
//!     aim-fs-migrate-patient \
//!         --aim-root ~/.aim_fs \
//!         --tenant-id djabbat \
//!         --legacy-patients ~/Desktop/LongevityCommon/AIM/Patients \
//!         --accept-pii [--dry-run]

use aim_fs::{AimFs, ApprovalPolicy, NewEntity, Source};
use aim_fs_crypto::{ensure_master_key, encrypt, patient_pseudonym, MasterKey};
use std::fs;
use std::path::{Path, PathBuf};

const REQUIRED_FLAG: &str = "--accept-pii";

fn main() -> std::process::ExitCode {
    let mut aim_root: Option<PathBuf> = None;
    let mut tenant: Option<String> = None;
    let mut legacy: Option<PathBuf> = None;
    let mut dry_run = false;
    let mut accept_pii = false;
    let argv: Vec<String> = std::env::args().collect();
    let mut i = 1;
    while i < argv.len() {
        match argv[i].as_str() {
            "-h" | "--help" => {
                println!(
                    "aim-fs-migrate-patient --aim-root <path> --tenant-id <uuid> \
                     --legacy-patients <path> --accept-pii [--dry-run]"
                );
                return std::process::ExitCode::SUCCESS;
            }
            "--aim-root" => {
                aim_root = argv.get(i + 1).map(PathBuf::from);
                i += 2;
            }
            "--tenant-id" => {
                tenant = argv.get(i + 1).cloned();
                i += 2;
            }
            "--legacy-patients" => {
                legacy = argv.get(i + 1).map(PathBuf::from);
                i += 2;
            }
            "--accept-pii" => {
                accept_pii = true;
                i += 1;
            }
            "--dry-run" => {
                dry_run = true;
                i += 1;
            }
            other => {
                eprintln!("unknown arg: {other}");
                return std::process::ExitCode::from(2);
            }
        }
    }
    if !accept_pii {
        eprintln!(
            "✗ refusing to run without {REQUIRED_FLAG} — this binary handles\n\
             real patient PII (names, DOBs, anamnesis, recipes).  Pass\n\
             {REQUIRED_FLAG} to confirm you understand and want to proceed.\n"
        );
        return std::process::ExitCode::from(2);
    }
    let aim_root = match aim_root {
        Some(p) => p,
        None => {
            eprintln!("--aim-root required");
            return std::process::ExitCode::from(2);
        }
    };
    let tenant = tenant.unwrap_or_else(|| "djabbat".to_string());
    let legacy = match legacy {
        Some(p) => p,
        None => {
            eprintln!("--legacy-patients required");
            return std::process::ExitCode::from(2);
        }
    };

    let master = match ensure_master_key() {
        Ok(k) => {
            println!("✓ master key loaded (or generated) — see ~/.aim_env");
            k
        }
        Err(e) => {
            eprintln!("✗ cannot ensure master key: {e}");
            return std::process::ExitCode::from(2);
        }
    };

    let fs = match AimFs::open(&aim_root) {
        Ok(f) => f,
        Err(e) => {
            eprintln!("✗ open aim_fs: {e}");
            return std::process::ExitCode::from(2);
        }
    };
    let policy = ApprovalPolicy {
        auto_approve_user_commands: true,
        auto_approve_observational_with_confidence_above: 1.0,
        auto_approve_service_events: true,
        require_approval_for: vec![],
        max_inactivity_days: 30,
    };

    let mut imported = 0;
    let mut skipped = 0;
    let mut errors = Vec::new();
    let entries = match fs::read_dir(&legacy) {
        Ok(e) => e,
        Err(e) => {
            eprintln!("✗ cannot read {}: {e}", legacy.display());
            return std::process::ExitCode::from(2);
        }
    };
    for entry in entries.flatten() {
        if !entry.file_type().map(|t| t.is_dir()).unwrap_or(false) {
            skipped += 1;
            continue;
        }
        let dir = entry.path();
        let folder = dir.file_name().and_then(|s| s.to_str()).unwrap_or("");
        if matches!(folder, "INBOX" | "anonymous") || folder.starts_with('_') || folder.starts_with('.') {
            skipped += 1;
            continue;
        }
        let parts: Vec<&str> = folder.split('_').collect();
        if parts.len() < 5 {
            // Convention: <Surname>_<Name>_<YYYY>_<MM>_<DD>
            skipped += 1;
            continue;
        }
        let surname = parts[0];
        let name = parts[1];
        let dob = parts[2..5].join("_");
        let pseudonym = patient_pseudonym(&master, surname, name, &dob);

        let dst = aim_root
            .join("users")
            .join(&tenant)
            .join("patients")
            .join(&pseudonym);

        if dry_run {
            println!(
                "  PLAN  {} → {}",
                folder,
                pseudonym
            );
            imported += 1;
            continue;
        }

        match migrate_one(&fs, &tenant, &master, &dir, &dst, surname, name, &dob, &pseudonym, &policy)
        {
            Ok(()) => {
                println!("  ✓ {} → {}", folder, pseudonym);
                imported += 1;
            }
            Err(e) => {
                errors.push(format!("{}: {e}", folder));
            }
        }
    }

    println!("\n=== summary ===");
    println!("  imported: {imported}");
    println!("  skipped:  {skipped}");
    println!("  errors:   {}", errors.len());
    for e in &errors {
        println!("    · {e}");
    }
    if errors.is_empty() {
        std::process::ExitCode::SUCCESS
    } else {
        std::process::ExitCode::from(1)
    }
}

#[allow(clippy::too_many_arguments)]
fn migrate_one(
    fs: &AimFs,
    tenant: &str,
    master: &MasterKey,
    src: &Path,
    dst: &Path,
    surname: &str,
    name: &str,
    dob: &str,
    pseudonym: &str,
    policy: &ApprovalPolicy,
) -> Result<(), String> {
    fs.ensure_patient(tenant, pseudonym)
        .map_err(|e| format!("ensure_patient: {e}"))?;
    fs::create_dir_all(dst.join("imported"))
        .map_err(|e| format!("create imported: {e}"))?;

    let identity_plain = format!(
        "# encrypted with AIM_FS Phase B.0.5\n\
         surname = \"{surname}\"\n\
         name = \"{name}\"\n\
         dob = \"{dob}\"\n\
         migrated_at = \"{}\"\n\
         legacy_folder = \"{}\"\n",
        chrono::Utc::now().to_rfc3339(),
        src.display()
    );
    let ad = format!("identity.toml/{pseudonym}/{tenant}");
    let blob = encrypt(master, identity_plain.as_bytes(), ad.as_bytes())
        .map_err(|e| format!("encrypt identity: {e}"))?;
    fs::write(dst.join("identity.toml.enc"), &blob)
        .map_err(|e| format!("write identity: {e}"))?;

    // Walk legacy dir; copy *.md / *.txt encrypted under imported/
    for ent in walkdir::WalkDir::new(src).max_depth(4) {
        let ent = ent.map_err(|e| format!("walk: {e}"))?;
        if !ent.file_type().is_file() {
            continue;
        }
        let p = ent.path();
        let ext = p.extension().and_then(|s| s.to_str()).unwrap_or("");
        if !matches!(ext, "md" | "txt" | "json") {
            continue;
        }
        let rel = p
            .strip_prefix(src)
            .map(|p| p.to_string_lossy().to_string())
            .unwrap_or_else(|_| p.file_name().unwrap_or_default().to_string_lossy().to_string());
        let body = fs::read(p).map_err(|e| format!("read {}: {e}", p.display()))?;
        let ad = format!("imported/{rel}/{pseudonym}/{tenant}");
        let blob = encrypt(master, &body, ad.as_bytes())
            .map_err(|e| format!("encrypt {rel}: {e}"))?;
        let dst_path = dst.join("imported").join(format!("{rel}.enc"));
        if let Some(parent) = dst_path.parent() {
            fs::create_dir_all(parent).ok();
        }
        fs::write(&dst_path, blob)
            .map_err(|e| format!("write {}: {e}", dst_path.display()))?;
    }

    // Insert contact_v1 entity scoped to pseudonym (no PII in DB).
    let new = NewEntity {
        schema: "contact_v1".into(),
        schema_version: 1,
        title: Some(format!("Patient {pseudonym}")),
        description: Some(format!(
            "Migrated patient (encrypted PII). Pseudonym: {pseudonym}."
        )),
        body: Some(format!(
            "Patient under AIM_FS care.  Real name + DOB encrypted in\n\
             `<aim_root>/users/{tenant}/patients/{pseudonym}/identity.toml.enc`.\n\
             Decrypt only via `aim-fs-crypto` with the doctor's master key.\n\n\
             Pseudonym: `{pseudonym}`\n\
             Migrated at: {}\n",
            chrono::Utc::now().to_rfc3339()
        )),
        source: Source::System,
        user_id: tenant.into(),
        session_id: None,
        llm_model: None,
        confidence: Some(1.0),
        requires_verification: false,
        scope_global: false,
        scope_user_ids: vec![tenant.into()],
        scope_project_ids: None,
        scope_patient_ids: vec![pseudonym.into()],
        tags: vec![
            "patient".into(),
            "contact".into(),
            "encrypted_pii".into(),
            "phase_b_0_5".into(),
        ],
        decay_ttl_days: None,
        decay_on_expire: None,
        initial_links: vec![],
    };
    fs.propose(tenant, new, Some("patient migration with PII encryption"), None, policy)
        .map_err(|e| format!("propose: {e}"))?;
    Ok(())
}
