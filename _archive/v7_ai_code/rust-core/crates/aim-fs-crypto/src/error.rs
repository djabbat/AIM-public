use thiserror::Error;

#[derive(Debug, Error)]
pub enum CryptoError {
    #[error("io: {0}")]
    Io(#[from] std::io::Error),
    #[error("hex: {0}")]
    Hex(#[from] hex::FromHexError),
    #[error("aes-gcm: {0}")]
    AesGcm(String),
    #[error("master key not configured (set AIM_FS_MASTER_KEY env var or run aim-fs-crypto-init)")]
    NoMasterKey,
    #[error("invalid magic header (expected AENC)")]
    BadMagic,
    #[error("unsupported encryption version {0}")]
    UnsupportedVersion(u8),
    #[error("ciphertext too short: {0} bytes")]
    TooShort(usize),
    #[error("master key length must be 32 bytes (got {0})")]
    BadKeyLength(usize),
}

pub type Result<T> = std::result::Result<T, CryptoError>;

impl From<aes_gcm::Error> for CryptoError {
    fn from(e: aes_gcm::Error) -> Self {
        Self::AesGcm(format!("{e}"))
    }
}
