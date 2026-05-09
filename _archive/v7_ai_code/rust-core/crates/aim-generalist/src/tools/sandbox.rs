//! Path sandbox for fs tools.
//!
//! AIM_GENERALIST_ROOT (default: $HOME/Desktop/LongevityCommon/AIM/Patients)
//! is the only directory read_file/write_file may touch.
//! AIM_GENERALIST_ALLOW_EXT — comma list of allowed extensions
//! (default: md,txt,json,csv,yml,yaml,py,rs,ex,exs,heex).

use std::path::{Path, PathBuf};

pub fn root() -> PathBuf {
    if let Ok(v) = std::env::var("AIM_GENERALIST_ROOT") {
        return PathBuf::from(v);
    }
    let home = std::env::var("HOME").unwrap_or_else(|_| "/home/oem".into());
    PathBuf::from(format!("{home}/Desktop/LongevityCommon/AIM/Patients"))
}

fn allowed_extensions() -> Vec<String> {
    let raw = std::env::var("AIM_GENERALIST_ALLOW_EXT")
        .unwrap_or_else(|_| "md,txt,json,csv,yml,yaml,py,rs,ex,exs,heex,toml,html,log".into());
    raw.split(',').map(|s| s.trim().to_lowercase()).filter(|s| !s.is_empty()).collect()
}

/// Validate path: must (canonically) live inside `root()`. Parent dirs
/// allowed to not yet exist (for write_file): we check the *closest existing
/// ancestor* + the rest of the path.
pub fn validate(path: &str, must_exist: bool) -> Result<PathBuf, String> {
    let root = root().canonicalize().map_err(|e| format!("sandbox root not accessible: {e}"))?;

    let p = Path::new(path);
    let abs: PathBuf = if p.is_absolute() { p.into() } else { root.join(p) };

    let resolved = if must_exist {
        abs.canonicalize().map_err(|e| format!("canonicalize {path}: {e}"))?
    } else {
        // For write: take the first existing ancestor, canonicalize it,
        // then append the unresolved tail. This blocks symlink escapes
        // through partially-existing paths.
        let mut existing = abs.clone();
        let mut tail: Vec<std::ffi::OsString> = Vec::new();
        while !existing.exists() {
            let name = existing.file_name()
                .ok_or_else(|| "path has no existing ancestor".to_string())?
                .to_os_string();
            tail.push(name);
            if !existing.pop() {
                return Err("path traverses above root".into());
            }
        }
        let mut out = existing.canonicalize().map_err(|e| format!("canonicalize ancestor: {e}"))?;
        for n in tail.into_iter().rev() {
            out.push(n);
        }
        out
    };

    if !resolved.starts_with(&root) {
        return Err(format!("path outside sandbox: {} (root={})",
            resolved.display(), root.display()));
    }

    if let Some(ext) = resolved.extension().and_then(|e| e.to_str()) {
        let exts = allowed_extensions();
        if !exts.iter().any(|e| e == &ext.to_lowercase()) {
            return Err(format!("extension '{}' not in allow-list {:?}", ext, exts));
        }
    } else if must_exist {
        // No extension on existing file → only allow directories
        if resolved.is_file() {
            return Err("file without extension is forbidden".into());
        }
    }

    Ok(resolved)
}

/// Truncate `s` at `max_bytes` but never split inside a UTF-8 char.
pub fn truncate_at_char(s: &str, max_bytes: usize) -> &str {
    if s.len() <= max_bytes { return s; }
    let mut i = max_bytes;
    while !s.is_char_boundary(i) && i > 0 { i -= 1; }
    &s[..i]
}
