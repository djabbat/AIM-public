use thiserror::Error;

#[derive(Debug, Error)]
pub enum AimFsError {
    #[error("io: {0}")]
    Io(#[from] std::io::Error),
    #[error("sqlite: {0}")]
    Sqlite(#[from] rusqlite::Error),
    #[error("pool: {0}")]
    Pool(#[from] r2d2::Error),
    #[error("serde_json: {0}")]
    Json(#[from] serde_json::Error),
    #[error("serde_yaml: {0}")]
    Yaml(#[from] serde_yaml::Error),
    #[error("not found: {0}")]
    NotFound(String),
    #[error("conflict: {0}")]
    Conflict(String),
    #[error("optimistic lock failed for {0}")]
    OptimisticLock(String),
    #[error("schema validation failed: {0}")]
    SchemaInvalid(String),
    #[error("idempotency in-flight for key {0}")]
    IdempotencyInFlight(String),
    #[error("invalid status transition {from} -> {to}")]
    BadTransition { from: String, to: String },
    #[error("blocked: {0}")]
    Blocked(String),
    #[error("other: {0}")]
    Other(String),
}

pub type Result<T> = std::result::Result<T, AimFsError>;
