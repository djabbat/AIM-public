//! Stable but anonymous worker ID per machine.
//!
//! sha256(hostname + per-install random salt)[:16] — same construction
//! as the Python version (`hive_telemetry::_worker_id`). The salt is
//! created on first call and persisted to `~/.cache/aim/hive_salt`,
//! never transmitted, so the queen cannot correlate an install with
//! its hostname or other installs.

use sha2::{Digest, Sha256};
use std::fs;
use std::io::Write;
use std::path::PathBuf;

const SALT_LEN: usize = 16;

fn salt_path() -> PathBuf {
    if let Ok(xdg) = std::env::var("XDG_CACHE_HOME") {
        return PathBuf::from(xdg).join("aim").join("hive_salt");
    }
    let home = std::env::var("HOME").unwrap_or_else(|_| ".".to_string());
    PathBuf::from(home).join(".cache").join("aim").join("hive_salt")
}

fn load_or_create_salt() -> String {
    let p = salt_path();
    if let Ok(s) = fs::read_to_string(&p) {
        let s = s.trim();
        if s.len() == SALT_LEN * 2 {
            return s.to_string();
        }
    }
    let mut bytes = [0u8; SALT_LEN];
    for b in bytes.iter_mut() {
        *b = (std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.subsec_nanos() as u8)
            .unwrap_or(0))
        .wrapping_add(rand_byte());
    }
    let salt = hex::encode(bytes);
    if let Some(parent) = p.parent() {
        let _ = fs::create_dir_all(parent);
    }
    if let Ok(mut f) = fs::File::create(&p) {
        let _ = f.write_all(salt.as_bytes());
    }
    salt
}

fn rand_byte() -> u8 {
    // Tiny noise without pulling rand into this module — uses
    // SystemTime nanos and process id mixed.
    let pid = std::process::id() as u64;
    let nanos = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_nanos() as u64)
        .unwrap_or(0);
    let mixed = pid.wrapping_mul(2654435761).wrapping_add(nanos);
    (mixed.wrapping_mul(0x9E3779B97F4A7C15) >> 56) as u8
}

/// 16-hex-char anonymous ID. sha256(hostname || salt)[:16].
pub fn worker_id() -> String {
    let host = hostname::get()
        .map(|h| h.to_string_lossy().to_string())
        .unwrap_or_else(|_| "unknown".to_string());
    let salt = load_or_create_salt();
    let mut h = Sha256::new();
    h.update(host.as_bytes());
    h.update(salt.as_bytes());
    let digest = h.finalize();
    hex::encode(&digest[..8]) // 16 hex chars = 8 bytes
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn id_is_16_hex() {
        // Use isolated salt via XDG override.
        let d = tempfile::tempdir().unwrap();
        std::env::set_var("XDG_CACHE_HOME", d.path());
        let id = worker_id();
        assert_eq!(id.len(), 16);
        assert!(id.chars().all(|c| c.is_ascii_hexdigit()));
    }

    #[test]
    fn id_is_stable_across_calls() {
        let d = tempfile::tempdir().unwrap();
        std::env::set_var("XDG_CACHE_HOME", d.path());
        let a = worker_id();
        let b = worker_id();
        assert_eq!(a, b);
    }
}
