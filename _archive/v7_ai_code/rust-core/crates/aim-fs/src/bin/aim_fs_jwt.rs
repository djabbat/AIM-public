//! aim-fs-jwt — issue / verify HS256 JWT tokens for `aim-fs-http`.
//!
//! Phase B Hub-mode H.1 (MVP).  RS256 + key rotation deferred until
//! multi-tenant clinic deployment requires it (see HUB_MODE.md §3.1).
//!
//! Subcommands:
//!     aim-fs-jwt issue --tenant <id> [--scopes "fs:read fs:write"] [--ttl <secs>]
//!     aim-fs-jwt verify <token>
//!     aim-fs-jwt secret-init      — generate a new HS256 secret in ~/.aim_env
//!
//! Required env: `AIM_FS_JWT_SECRET=<32-byte-hex>` (set by `secret-init`).
//!
//! aim-fs-http reads the same secret env var and validates each Bearer token.
use jsonwebtoken::{decode, encode, Algorithm, DecodingKey, EncodingKey, Header, Validation};
use rand::RngCore;
use serde::{Deserialize, Serialize};
use std::fs;
use std::path::Path;

const ENV_VAR: &str = "AIM_FS_JWT_SECRET";
const ENV_FILE: &str = ".aim_env";

#[derive(Debug, Serialize, Deserialize)]
struct Claims {
    sub: String,                  // tenant_id
    iss: String,                  // "aim-fs-jwt"
    iat: u64,                     // issued at (unix)
    exp: u64,                     // expires at (unix)
    #[serde(default)]
    scopes: Vec<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    org: Option<String>,
}

fn main() -> std::process::ExitCode {
    let argv: Vec<String> = std::env::args().collect();
    if argv.len() < 2 {
        print_help();
        return std::process::ExitCode::SUCCESS;
    }
    match argv[1].as_str() {
        "issue" => cmd_issue(&argv[2..]),
        "verify" => cmd_verify(&argv[2..]),
        "secret-init" => cmd_secret_init(),
        "-h" | "--help" => {
            print_help();
            std::process::ExitCode::SUCCESS
        }
        other => {
            eprintln!("unknown subcommand: {other}");
            print_help();
            std::process::ExitCode::from(2)
        }
    }
}

fn print_help() {
    println!(
        "aim-fs-jwt — HS256 token tooling for aim-fs-http\n\n\
         USAGE:\n\
         \t aim-fs-jwt issue --tenant <id> [--scopes \"fs:read fs:write\"] [--ttl <secs>] [--org <id>]\n\
         \t aim-fs-jwt verify <token>\n\
         \t aim-fs-jwt secret-init     # generate AIM_FS_JWT_SECRET into ~/.aim_env\n\n\
         Default --ttl: 604800 (7 days). Default --scopes: \"fs:read fs:write fs:approve\""
    );
}

fn cmd_secret_init() -> std::process::ExitCode {
    if std::env::var(ENV_VAR).is_ok() || env_file_has(ENV_VAR) {
        eprintln!("✓ {ENV_VAR} already set (env or ~/.aim_env)");
        return std::process::ExitCode::SUCCESS;
    }
    let mut bytes = [0u8; 32];
    rand::thread_rng().fill_bytes(&mut bytes);
    let hex = hex::encode(&bytes);
    let home = std::env::var_os("HOME").expect("HOME not set");
    let env_file = Path::new(&home).join(ENV_FILE);
    let prefix = if env_file.exists() {
        let cur = fs::read_to_string(&env_file).unwrap_or_default();
        if cur.ends_with('\n') || cur.is_empty() {
            cur
        } else {
            format!("{cur}\n")
        }
    } else {
        String::new()
    };
    let new = format!(
        "{prefix}# AIM_FS Hub-mode JWT secret — auto-generated; do NOT commit\n{ENV_VAR}={hex}\n"
    );
    if let Err(e) = fs::write(&env_file, new) {
        eprintln!("✗ write {}: {e}", env_file.display());
        return std::process::ExitCode::from(1);
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        if let Ok(meta) = fs::metadata(&env_file) {
            let mut perms = meta.permissions();
            perms.set_mode(0o600);
            let _ = fs::set_permissions(&env_file, perms);
        }
    }
    println!("✓ generated {ENV_VAR} → {}", env_file.display());
    std::process::ExitCode::SUCCESS
}

fn env_file_has(var: &str) -> bool {
    let home = match std::env::var_os("HOME") {
        Some(h) => h,
        None => return false,
    };
    let env_file = Path::new(&home).join(ENV_FILE);
    if !env_file.exists() {
        return false;
    }
    fs::read_to_string(&env_file)
        .map(|s| s.lines().any(|l| l.trim_start().starts_with(&format!("{var}="))))
        .unwrap_or(false)
}

fn load_secret() -> Result<Vec<u8>, String> {
    if let Ok(hex_s) = std::env::var(ENV_VAR) {
        return hex::decode(hex_s.trim()).map_err(|e| format!("hex: {e}"));
    }
    if let Some(home) = std::env::var_os("HOME") {
        let env_file = Path::new(&home).join(ENV_FILE);
        if env_file.exists() {
            let s = fs::read_to_string(&env_file).map_err(|e| format!("read: {e}"))?;
            for line in s.lines() {
                let line = line.trim();
                if let Some(rest) = line.strip_prefix(&format!("{ENV_VAR}=")) {
                    let v = rest.trim().trim_matches(['"', '\'']);
                    return hex::decode(v).map_err(|e| format!("hex: {e}"));
                }
            }
        }
    }
    Err(format!("{ENV_VAR} not set; run `aim-fs-jwt secret-init` first"))
}

fn cmd_issue(args: &[String]) -> std::process::ExitCode {
    let mut tenant: Option<String> = None;
    let mut scopes_arg: Option<String> = None;
    let mut ttl: u64 = 604_800; // 7 days
    let mut org: Option<String> = None;
    let mut i = 0;
    while i < args.len() {
        match args[i].as_str() {
            "--tenant" => {
                tenant = args.get(i + 1).cloned();
                i += 2;
            }
            "--scopes" => {
                scopes_arg = args.get(i + 1).cloned();
                i += 2;
            }
            "--ttl" => {
                ttl = args
                    .get(i + 1)
                    .and_then(|s| s.parse().ok())
                    .unwrap_or(604_800);
                i += 2;
            }
            "--org" => {
                org = args.get(i + 1).cloned();
                i += 2;
            }
            other => {
                eprintln!("unknown flag: {other}");
                return std::process::ExitCode::from(2);
            }
        }
    }
    let tenant = match tenant {
        Some(t) => t,
        None => {
            eprintln!("--tenant <id> required");
            return std::process::ExitCode::from(2);
        }
    };
    let secret = match load_secret() {
        Ok(s) => s,
        Err(e) => {
            eprintln!("✗ {e}");
            return std::process::ExitCode::from(1);
        }
    };
    let scopes: Vec<String> = scopes_arg
        .unwrap_or_else(|| "fs:read fs:write fs:approve".into())
        .split_whitespace()
        .map(String::from)
        .collect();
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    let claims = Claims {
        sub: tenant,
        iss: "aim-fs-jwt".into(),
        iat: now,
        exp: now + ttl,
        scopes,
        org,
    };
    let token = match encode(
        &Header::new(Algorithm::HS256),
        &claims,
        &EncodingKey::from_secret(&secret),
    ) {
        Ok(t) => t,
        Err(e) => {
            eprintln!("✗ encode: {e}");
            return std::process::ExitCode::from(1);
        }
    };
    println!("{token}");
    std::process::ExitCode::SUCCESS
}

fn cmd_verify(args: &[String]) -> std::process::ExitCode {
    let token = match args.first() {
        Some(t) => t,
        None => {
            eprintln!("usage: aim-fs-jwt verify <token>");
            return std::process::ExitCode::from(2);
        }
    };
    let secret = match load_secret() {
        Ok(s) => s,
        Err(e) => {
            eprintln!("✗ {e}");
            return std::process::ExitCode::from(1);
        }
    };
    let mut validation = Validation::new(Algorithm::HS256);
    validation.set_issuer(&["aim-fs-jwt"]);
    match decode::<Claims>(token, &DecodingKey::from_secret(&secret), &validation) {
        Ok(d) => {
            println!("✓ valid HS256 token");
            println!("  sub:    {}", d.claims.sub);
            println!("  iss:    {}", d.claims.iss);
            println!("  iat:    {} (unix)", d.claims.iat);
            println!("  exp:    {} (unix)", d.claims.exp);
            if let Some(org) = &d.claims.org {
                println!("  org:    {org}");
            }
            println!("  scopes: {}", d.claims.scopes.join(" "));
            std::process::ExitCode::SUCCESS
        }
        Err(e) => {
            eprintln!("✗ verify failed: {e}");
            std::process::ExitCode::from(1)
        }
    }
}
