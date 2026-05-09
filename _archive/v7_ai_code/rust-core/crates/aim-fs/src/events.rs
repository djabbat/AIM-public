use crate::error::Result;
use chrono::Utc;
use rusqlite::{params, Transaction};
use ulid::Ulid;

/// Append a row to the `events` table inside a caller-provided transaction.
/// Atomicity follows the wrapping transaction (BEGIN IMMEDIATE).
pub fn log_event_in_tx(
    tx: &Transaction,
    tenant_id: &str,
    entity_id: Option<&str>,
    event_type: &str,
    payload: &serde_json::Value,
) -> Result<()> {
    tx.execute(
        "INSERT INTO events (id, tenant_id, entity_id, event_type, payload, created_at)
         VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
        params![
            Ulid::new().to_string(),
            tenant_id,
            entity_id,
            event_type,
            serde_json::to_string(payload)?,
            Utc::now().to_rfc3339()
        ],
    )?;
    Ok(())
}
