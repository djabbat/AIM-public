//! AIM_FS Phase B encryption — Phase B.0.5 (env-var master key).
//!
//! See `docs/AIM_FS/PHASE_B_ENCRYPTION.md` for full design.  This crate
//! ships only the crypto primitives + master-key loader; integration with
//! `aim-fs` (encrypt-on-propose / decrypt-on-read) lands separately.
//!
//! # Threat model (Phase B.0.5)
//!
//! Defends against:
//! - Backup / disk theft of `~/.aim_fs`
//! - PII leakage through accidental `git add Patients/`
//! - Folder-name PII leakage (pseudonym replaces `Beridze_Keti_2026_03_12`)
//!
//! Does NOT defend against:
//! - Operator with root (master key in env / process memory)
//! - Side-channel via swap (mitigated weakly by `secrecy` zeroize)
//!
//! # Phase B.1 upgrade path (deferred)
//!
//! Full OS keyring integration (Linux Secret Service / macOS Keychain /
//! Windows Credential) — only worth doing when AIM_FS hosts ≥2 doctors
//! or runs on a multi-user box.  Until then, env-var simplicity wins.

pub mod error;
pub mod master_key;
pub mod pseudonym;
pub mod stream;

pub use error::{CryptoError, Result};
pub use master_key::{ensure_master_key, load_master_key, MasterKey};
pub use pseudonym::patient_pseudonym;
pub use stream::{decrypt, encrypt, MAGIC, VERSION};

#[cfg(test)]
mod tests {
    use super::*;
    use secrecy::ExposeSecret;

    fn key32() -> MasterKey {
        MasterKey::from_bytes([0x42; 32])
    }

    #[test]
    fn roundtrip_encryption() {
        let key = key32();
        let plaintext = b"hello AIM_FS";
        let ad = b"tenant_id::feedback_v1";
        let ct = encrypt(&key, plaintext, ad).unwrap();
        // Magic + version prefix.
        assert_eq!(&ct[..4], MAGIC);
        assert_eq!(ct[4], VERSION);
        let pt = decrypt(&key, &ct, ad).unwrap();
        assert_eq!(pt, plaintext);
    }

    #[test]
    fn ad_mismatch_fails() {
        let key = key32();
        let ct = encrypt(&key, b"x", b"good").unwrap();
        assert!(decrypt(&key, &ct, b"bad").is_err());
    }

    #[test]
    fn pseudonym_is_deterministic_and_anon() {
        let key = key32();
        let a = patient_pseudonym(&key, "Beridze", "Keti", "2026_03_12");
        let b = patient_pseudonym(&key, "Beridze", "Keti", "2026_03_12");
        assert_eq!(a, b, "must be deterministic");
        assert_ne!(
            a,
            patient_pseudonym(&key, "Beridze", "Keti", "2026_03_13"),
            "1-day DOB delta must change pseudonym"
        );
        assert_eq!(a.len(), 32, "32 hex chars = 128 bits");
        // No PII in the pseudonym.
        assert!(!a.contains("Beridze") && !a.contains("Keti") && !a.contains("2026"));
    }

    #[test]
    fn master_key_exposes_32_bytes() {
        let key = MasterKey::from_bytes([0xAB; 32]);
        assert_eq!(key.expose_secret().len(), 32);
        assert!(key.expose_secret().iter().all(|&b| b == 0xAB));
    }
}
