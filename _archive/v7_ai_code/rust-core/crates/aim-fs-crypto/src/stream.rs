//! AES-256-GCM encrypted blob format — Phase B SPEC §3.4.
//!
//!     | magic(4) | version(1) | nonce(12) | ciphertext(N) | tag(16) |
//!     |  AENC    |    01      |    ...    |     ...       |    ...  |
//!
//! Magic `AENC` (0x41 0x45 0x4E 0x43) lets readers distinguish encrypted
//! body from plain text in the same column (graceful migration).

use crate::error::{CryptoError, Result};
use crate::master_key::MasterKey;
use aes_gcm::aead::{Aead, KeyInit, Payload};
use aes_gcm::{Aes256Gcm, Nonce};
use rand::RngCore;
use secrecy::ExposeSecret;

pub const MAGIC: &[u8; 4] = b"AENC";
pub const VERSION: u8 = 0x01;
const NONCE_LEN: usize = 12;

pub fn encrypt(key: &MasterKey, plaintext: &[u8], ad: &[u8]) -> Result<Vec<u8>> {
    let cipher = Aes256Gcm::new_from_slice(key.expose_secret())
        .map_err(|e| CryptoError::AesGcm(format!("key: {e}")))?;
    let mut nonce_bytes = [0u8; NONCE_LEN];
    rand::thread_rng().fill_bytes(&mut nonce_bytes);
    let nonce = Nonce::from_slice(&nonce_bytes);
    let ct_with_tag = cipher.encrypt(
        nonce,
        Payload {
            msg: plaintext,
            aad: ad,
        },
    )?;

    let mut out = Vec::with_capacity(MAGIC.len() + 1 + NONCE_LEN + ct_with_tag.len());
    out.extend_from_slice(MAGIC);
    out.push(VERSION);
    out.extend_from_slice(&nonce_bytes);
    out.extend_from_slice(&ct_with_tag);
    Ok(out)
}

pub fn decrypt(key: &MasterKey, blob: &[u8], ad: &[u8]) -> Result<Vec<u8>> {
    if blob.len() < MAGIC.len() + 1 + NONCE_LEN + 16 {
        return Err(CryptoError::TooShort(blob.len()));
    }
    if &blob[..MAGIC.len()] != MAGIC {
        return Err(CryptoError::BadMagic);
    }
    let version = blob[MAGIC.len()];
    if version != VERSION {
        return Err(CryptoError::UnsupportedVersion(version));
    }
    let nonce = Nonce::from_slice(&blob[MAGIC.len() + 1..MAGIC.len() + 1 + NONCE_LEN]);
    let ct = &blob[MAGIC.len() + 1 + NONCE_LEN..];
    let cipher = Aes256Gcm::new_from_slice(key.expose_secret())
        .map_err(|e| CryptoError::AesGcm(format!("key: {e}")))?;
    let pt = cipher.decrypt(nonce, Payload { msg: ct, aad: ad })?;
    Ok(pt)
}

/// Convenience: detect `AENC` magic to decide whether to decrypt or
/// pass-through.  Used by readers during Phase B migration.
pub fn is_encrypted(blob: &[u8]) -> bool {
    blob.len() >= MAGIC.len() && &blob[..MAGIC.len()] == MAGIC
}
