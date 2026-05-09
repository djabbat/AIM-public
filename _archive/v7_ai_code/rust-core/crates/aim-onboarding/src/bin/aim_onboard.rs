//! aim-onboard — interactive guided creation.
//!
//! Usage:
//!     aim-onboard --template <path> --tenant-id <uuid> [--aim-root <path>]
use aim_fs::{AimFs, ApprovalPolicy};
use aim_onboarding::{cli, Answer, Answers, Session, Template};
use std::io::{stdin, stdout, BufReader, Read};
use std::path::PathBuf;

fn main() -> anyhow::Result<()> {
    let mut template_path: Option<PathBuf> = None;
    let mut tenant_id: Option<String> = None;
    let mut aim_root: Option<PathBuf> = None;
    let mut non_interactive = false;

    let argv: Vec<String> = std::env::args().collect();
    let mut i = 1;
    while i < argv.len() {
        match argv[i].as_str() {
            "-h" | "--help" => {
                print_help();
                return Ok(());
            }
            "--template" => {
                template_path = argv.get(i + 1).map(PathBuf::from);
                i += 2;
            }
            "--tenant-id" => {
                tenant_id = argv.get(i + 1).cloned();
                i += 2;
            }
            "--aim-root" => {
                aim_root = argv.get(i + 1).map(PathBuf::from);
                i += 2;
            }
            "--non-interactive" | "--ni" => {
                non_interactive = true;
                i += 1;
            }
            "--emit-template-json" => {
                // Emit template (parsed YAML) as JSON and exit. Used by Phoenix
                // OnboardLive to render the question form without needing a
                // YAML library on the Elixir side.
                let tp = template_path
                    .clone()
                    .ok_or_else(|| anyhow::anyhow!("--template must precede --emit-template-json"))?;
                let t = Template::from_yaml_file(&tp)?;
                println!("{}", serde_json::to_string(&t)?);
                return Ok(());
            }
            other => anyhow::bail!("unknown arg: {other}"),
        }
    }

    let template_path = template_path
        .ok_or_else(|| anyhow::anyhow!("missing --template <path>"))?;
    let tenant_id = tenant_id
        .ok_or_else(|| anyhow::anyhow!("missing --tenant-id <uuid>"))?;
    let aim_root = aim_root.unwrap_or_else(|| {
        std::env::var_os("AIM_FS_ROOT")
            .map(PathBuf::from)
            .unwrap_or_else(|| {
                std::env::var_os("HOME")
                    .map(|h| PathBuf::from(h).join(".aim_fs"))
                    .unwrap_or_else(|| PathBuf::from("/var/lib/aim_fs"))
            })
    });

    let template = Template::from_yaml_file(&template_path)?;
    let fs = AimFs::open(&aim_root)?;
    let mut session = Session::new(template, &tenant_id);

    if non_interactive {
        // Read JSON answers map from stdin: { "slug": "...", "feedback_rules": ["..."] }
        let mut buf = String::new();
        stdin().read_to_string(&mut buf)?;
        let raw: serde_json::Value = serde_json::from_str(&buf)?;
        let obj = raw
            .as_object()
            .ok_or_else(|| anyhow::anyhow!("JSON input must be an object"))?;
        let mut answers = Answers::new();
        for (k, v) in obj {
            let a: Answer = serde_json::from_value(v.clone())?;
            answers.set(k, a);
        }
        session.answers = answers;
    } else {
        let stdin = stdin();
        let stdout = stdout();
        let mut input = BufReader::new(stdin.lock());
        let mut output = stdout.lock();
        cli::run(&mut session, &mut input, &mut output)?;
    }

    let policy = default_policy();
    let outcome = session.apply_to_aim_fs(&fs, &tenant_id, &policy)?;
    if non_interactive {
        // Emit JSON for callers to parse.
        let v = serde_json::json!({
            "target_dir": outcome.target_dir.display().to_string(),
            "files_written": outcome.files_written,
            "entities_proposed": outcome.entities_proposed,
        });
        println!("{}", serde_json::to_string(&v)?);
    } else {
        println!("\n→ scaffold dir: {}", outcome.target_dir.display());
        println!("→ files written: {}", outcome.files_written.len());
        println!("→ entities proposed: {}", outcome.entities_proposed.len());
    }
    Ok(())
}

fn default_policy() -> ApprovalPolicy {
    ApprovalPolicy {
        auto_approve_user_commands: true,
        auto_approve_observational_with_confidence_above: 0.95,
        auto_approve_service_events: true,
        require_approval_for: vec![
            "feedback".into(),
            "proposal".into(),
            "recipe".into(),
            "diagnosis".into(),
        ],
        max_inactivity_days: 30,
    }
}

fn print_help() {
    println!(
        "aim-onboard — interactive AIM_FS onboarding\n\n\
         USAGE: aim-onboard --template <path> --tenant-id <uuid> [--aim-root <path>]\n\n\
         Flags:\n\
         \t--template <path>   YAML template (e.g. templates/research_project.yaml)\n\
         \t--tenant-id <uuid>  AIM tenant id\n\
         \t--aim-root <path>   AIM_FS data root (env: AIM_FS_ROOT, default: ~/.aim_fs)"
    );
}
