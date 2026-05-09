//! Master key loading — Phase B.0.5 (env-var only).
//!
//! Reads `AIM_FS_MASTER_KEY=<64-hex>` from `~/.aim_env` or the process
//! environment.  Auto-generates one if `ensure_master_key()` is called and
//! none is configured.

use crate::error::{CryptoError, Result};
use rand::RngCore;
use secrecy::{ExposeSecret, Secret};
use std::fs;
use std::path::Path;
use zeroize::Zeroize;

const ENV_VAR: &str = "AIM_FS_MASTER_KEY";
const ENV_FILE: &str = ".aim_env";

/// A 32-byte master key wrapped so it zeroes on drop.
/// Using `Vec<u8>` (which has Zeroize impl) under `secrecy::Secret`.
/// Not `Clone` — we don't want accidental copies of the key in memory; if
/// you need to share it, wrap in `Arc<MasterKey>`.
pub struct MasterKey(Secret<Vec<u8>>);

impl MasterKey {
    pub fn from_bytes(bytes: [u8; 32]) -> Self {
        Self(Secret::new(bytes.to_vec()))
    }
    pub fn expose_secret(&self) -> &[u8] {
        self.0.expose_secret().as_slice()
    }
}

// Manual zeroize for the temp arr is unnecessary — `Vec<u8>` is zeroized
// inside `Secret::drop`.
fn _zeroize_compat(_: &mut [u8]) {
    // Type-check that zeroize crate is reachable — used in drops elsewhere.
}
impl Zeroize for MasterKey {
    fn zeroize(&mut self) {
        // No-op: Secret zeroes its inner on drop.
    }
}

impl std::fmt::Debug for MasterKey {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("MasterKey")
            .field("len", &32usize)
            .field("value", &"<redacted>")
            .finish()
    }
}

/// Read the master key from `$AIM_FS_MASTER_KEY` (process env), else from
/// `~/.aim_env`.  Returns `NoMasterKey` if neither has it.
pub fn load_master_key() -> Result<MasterKey> {
    if let Ok(hex) = std::env::var(ENV_VAR) {
        return parse_hex_key(&hex);
    }
    if let Some(home) = std::env::var_os("HOME") {
        let env_file = Path::new(&home).join(ENV_FILE);
        if env_file.exists() {
            let s = fs::read_to_string(&env_file)?;
            for line in s.lines() {
                let line = line.trim();
                if let Some(rest) = line.strip_prefix(&format!("{ENV_VAR}=")) {
                    let v = rest.trim().trim_matches('"').trim_matches('\'');
                    return parse_hex_key(v);
                }
            }
        }
    }
    Err(CryptoError::NoMasterKey)
}

/// Generate a new master key + write it to `~/.aim_env` (or return existing).
/// Used by `aim-fs-crypto-init`. Returns the loaded/created key.
pub fn ensure_master_key() -> Result<MasterKey> {
    if let Ok(k) = load_master_key() {
        return Ok(k);
    }
    let mut bytes = [0u8; 32];
    rand::thread_rng().fill_bytes(&mut bytes);
    let key = MasterKey::from_bytes(bytes);
    let hex = hex::encode(key.expose_secret());

    let home = std::env::var_os("HOME")
        .ok_or_else(|| CryptoError::Io(std::io::Error::new(
            std::io::ErrorKind::NotFound,
            "HOME env var not set",
        )))?;
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
    let new_contents = format!(
        "{prefix}# AIM_FS Phase B master key — auto-generated; do NOT commit\n{ENV_VAR}={hex}\n"
    );
    fs::write(&env_file, new_contents)?;
    // 0600 perms.
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mut perms = fs::metadata(&env_file)?.permissions();
        perms.set_mode(0o600);
        fs::set_permissions(&env_file, perms)?;
    }
    Ok(key)
}

fn parse_hex_key(hex: &str) -> Result<MasterKey> {
    let bytes = hex::decode(hex.trim())?;
    if bytes.len() != 32 {
        return Err(CryptoError::BadKeyLength(bytes.len()));
    }
    let mut arr = [0u8; 32];
    arr.copy_from_slice(&bytes);
    Ok(MasterKey::from_bytes(arr))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_valid_hex() {
        let hex = "00".repeat(32);
        let k = parse_hex_key(&hex).unwrap();
        assert_eq!(k.expose_secret(), &[0u8; 32][..]);
    }

    #[test]
    fn rejects_short_key() {
        let hex = "0123";
        assert!(matches!(parse_hex_key(hex), Err(CryptoError::BadKeyLength(2))));
    }
}
