use crate::db::DbPool;
use crate::error::Result;
use chrono::Utc;
use rusqlite::params;
use std::time::Duration;

/// Background decay sweeper. Runs every `interval` (60s by default per SPEC §7).
pub async fn run_sweeper(pool: DbPool, interval: Duration) {
    loop {
        if let Err(e) = sweep_once(&pool) {
            tracing::warn!("decay sweeper error: {e}");
        }
        tokio::time::sleep(interval).await;
    }
}

pub fn sweep_once(pool: &DbPool) -> Result<usize> {
    let mut conn = pool.get()?;
    let tx = conn.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;
    let now = Utc::now().to_rfc3339();
    // Step 1: regular decay — active entities whose TTL passed.
    let n_expired = tx.execute(
        "UPDATE entities
         SET status = CASE
             WHEN decay_on_expire = 'deprecate' THEN 'deprecated'
             ELSE 'expired'
         END,
         version = version + 1,
         updated_at = ?1
         WHERE status = 'active'
           AND decay_expires_at IS NOT NULL
           AND decay_expires_at < ?1",
        params![now],
    )?;

    // Step 2: cascade — for each entity whose status JUST changed (or was
    // already `expired`/`deprecated`), find any active entity that
    // `depends_on` it and mark it `stale`. Bounded recursion via fixpoint
    // loop with a visited set; max 10 iterations to guard against pathological
    // graphs.
    let mut total_stale = 0usize;
    for _round in 0..10 {
        let n = tx.execute(
            "UPDATE entities AS dep
             SET status='stale', version = version + 1, updated_at = ?1
             WHERE dep.status = 'active'
               AND dep.id IN (
                   SELECT l.source_id
                   FROM links l
                   JOIN entities src ON src.id = l.source_id
                   JOIN entities tgt ON tgt.id = l.target_id
                   WHERE l.link_type = 'depends_on'
                     AND src.status = 'active'                 -- dep itself still active
                     AND tgt.status IN ('expired','deprecated','stale')
               )",
            params![now],
        )?;
        if n == 0 {
            break;
        }
        total_stale += n;
    }

    if n_expired > 0 || total_stale > 0 {
        tx.execute(
            "INSERT INTO events (id, tenant_id, entity_id, event_type, payload, created_at)
             SELECT lower(hex(randomblob(16))), '_system', NULL, 'sweeper_run',
                    json_object('expired_count', ?1, 'cascade_stale', ?2), ?3",
            params![n_expired as i64, total_stale as i64, now],
        )?;
    }
    tx.commit()?;
    Ok(n_expired + total_stale)
}
