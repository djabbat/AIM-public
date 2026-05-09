//! Folder-name pseudonyms — Phase B SPEC §3.3.
//!
//! `patient_pseudonym(master, surname, name, dob) → 32 hex chars (128 bits)`
//! using HMAC-SHA256 truncated to first 16 bytes.  Deterministic so the
//! same surname/name/dob always lands at the same path on disk.

use crate::master_key::MasterKey;
use hmac::{Hmac, Mac};
use secrecy::ExposeSecret;
use sha2::Sha256;

type HmacSha256 = Hmac<Sha256>;

/// Returns 32 hex chars (16 bytes / 128 bits — collision-resistant for
/// realistic patient counts on a single tenant).
pub fn patient_pseudonym(master: &MasterKey, surname: &str, name: &str, dob: &str) -> String {
    let mut mac = HmacSha256::new_from_slice(master.expose_secret())
        .expect("HMAC-SHA256 accepts any key length");
    mac.update(b"AIM_FS/patient/v1\n");
    mac.update(surname.as_bytes());
    mac.update(b"\0");
    mac.update(name.as_bytes());
    mac.update(b"\0");
    mac.update(dob.as_bytes());
    let full = mac.finalize().into_bytes();
    hex::encode(&full[..16])
}
