//! Link / graph layer.  Maps to the `links` table per SPEC §6.
//!
//! Link types: `depends_on`, `refines`, `supersedes`, `contradicts`,
//! `references`, `produced_by`.  Atomic operations live inside the same
//! `BEGIN IMMEDIATE` transactions as their entity events.

use crate::error::{AimFsError, Result};
use crate::events::log_event_in_tx;
use crate::types::*;
use crate::AimFs;
use chrono::Utc;
use rusqlite::{params, Transaction};

/// Insert one link inside a caller-provided transaction.
pub(crate) fn add_link_in_tx(
    tx: &Transaction,
    tenant_id: &str,
    source_id: &str,
    target_id: &str,
    link_type: LinkType,
) -> Result<()> {
    tx.execute(
        "INSERT OR IGNORE INTO links (source_id, target_id, link_type, tenant_id, created_at)
         VALUES (?1, ?2, ?3, ?4, ?5)",
        params![
            source_id,
            target_id,
            link_type.as_str(),
            tenant_id,
            Utc::now().to_rfc3339(),
        ],
    )?;
    Ok(())
}

/// Return all link rows whose source = `id`.
pub(crate) fn list_outgoing(
    tx: &Transaction,
    tenant_id: &str,
    source_id: &str,
) -> Result<Vec<(String, LinkType)>> {
    let mut stmt = tx.prepare(
        "SELECT target_id, link_type FROM links
         WHERE tenant_id = ?1 AND source_id = ?2",
    )?;
    let rows = stmt
        .query_map(params![tenant_id, source_id], |r| {
            Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?))
        })?
        .map(|res| res.map(|(t, lt)| (t, parse_link_type(&lt))))
        .collect::<std::result::Result<Vec<_>, _>>()?;
    Ok(rows)
}

/// Find every active entity that contradicts (or is contradicted by)
/// `entity_id`. Returns a Vec of (other_id, status).  Used by `propose()` to
/// short-circuit on conflict.
pub(crate) fn find_active_contradictors(
    tx: &Transaction,
    tenant_id: &str,
    entity_id: &str,
) -> Result<Vec<String>> {
    let mut stmt = tx.prepare(
        "SELECT e.id
         FROM entities e
         WHERE e.tenant_id = ?1
           AND e.status = 'active'
           AND (
               e.id IN (
                   SELECT target_id FROM links
                   WHERE tenant_id = ?1 AND source_id = ?2 AND link_type = 'contradicts'
               )
            OR e.id IN (
                   SELECT source_id FROM links
                   WHERE tenant_id = ?1 AND target_id = ?2 AND link_type = 'contradicts'
               )
           )",
    )?;
    let ids = stmt
        .query_map(params![tenant_id, entity_id], |r| r.get::<_, String>(0))?
        .collect::<std::result::Result<Vec<_>, _>>()?;
    Ok(ids)
}

fn parse_link_type(s: &str) -> LinkType {
    match s {
        "refines" => LinkType::Refines,
        "supersedes" => LinkType::Supersedes,
        "contradicts" => LinkType::Contradicts,
        "references" => LinkType::References,
        "produced_by" => LinkType::ProducedBy,
        _ => LinkType::DependsOn,
    }
}

/// One entity in a dispute pair, with the contradicting partner attached so
/// the UI can render side-by-side.
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct DisputeRecord {
    pub a_id: String,
    pub a_title: Option<String>,
    pub a_body: Option<String>,
    pub b_id: String,
    pub b_title: Option<String>,
    pub b_body: Option<String>,
}

impl AimFs {
    /// Return all disputed pairs for `tenant_id`.  Each pair appears once;
    /// `a` is the entity that triggered the dispute, `b` is the older active
    /// entity it now contradicts.
    pub fn list_disputes(&self, tenant_id: &str) -> Result<Vec<DisputeRecord>> {
        let conn = self.pool.get()?;
        let mut stmt = conn.prepare(
            "SELECT e.id, e.title, e.body, l.target_id
             FROM entities e
             JOIN links l ON l.source_id = e.id AND l.link_type = 'contradicts'
             WHERE e.tenant_id = ?1 AND e.status = 'disputed'",
        )?;
        let pairs = stmt
            .query_map(params![tenant_id], |r| {
                Ok((
                    r.get::<_, String>(0)?,
                    r.get::<_, Option<String>>(1)?,
                    r.get::<_, Option<String>>(2)?,
                    r.get::<_, String>(3)?,
                ))
            })?
            .collect::<std::result::Result<Vec<_>, _>>()?;

        let mut out = Vec::with_capacity(pairs.len());
        for (a_id, a_title, a_body, b_id) in pairs {
            let b_meta: Option<(Option<String>, Option<String>)> = conn
                .query_row(
                    "SELECT title, body FROM entities WHERE tenant_id = ?1 AND id = ?2",
                    params![tenant_id, b_id],
                    |r| Ok((r.get(0)?, r.get(1)?)),
                )
                .ok();
            let (b_title, b_body) = b_meta.unwrap_or((None, None));
            out.push(DisputeRecord {
                a_id,
                a_title,
                a_body,
                b_id,
                b_title,
                b_body,
            });
        }
        Ok(out)
    }

    /// Resolve a dispute by declaring `winner_id` active and `loser_id`
    /// superseded.  Both must currently be in `disputed` status and be
    /// connected by a `contradicts` link.
    pub fn resolve_dispute(
        &self,
        tenant_id: &str,
        winner_id: &str,
        loser_id: &str,
        actor: &Actor,
    ) -> Result<()> {
        let mut conn = self.pool.get()?;
        let tx = conn.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;
        let now = chrono::Utc::now().to_rfc3339();
        // Verify both are disputed.
        for id in [winner_id, loser_id] {
            let s: String = tx.query_row(
                "SELECT status FROM entities WHERE tenant_id = ?1 AND id = ?2",
                params![tenant_id, id],
                |r| r.get(0),
            )?;
            if s != "disputed" {
                return Err(crate::error::AimFsError::BadTransition {
                    from: s,
                    to: "active|superseded".into(),
                });
            }
        }
        tx.execute(
            "UPDATE entities SET status='active', version=version+1, updated_at=?3
             WHERE tenant_id=?1 AND id=?2",
            params![tenant_id, winner_id, now],
        )?;
        tx.execute(
            "UPDATE entities SET status='superseded', version=version+1, updated_at=?3
             WHERE tenant_id=?1 AND id=?2",
            params![tenant_id, loser_id, now],
        )?;
        crate::events::log_event_in_tx(
            &tx,
            tenant_id,
            Some(winner_id),
            "dispute_resolved",
            &serde_json::json!({"winner": winner_id, "loser": loser_id, "by": actor.user_id}),
        )?;
        tx.commit()?;
        Ok(())
    }

    /// Add a link between two existing entities (both must be in the same tenant).
    /// Atomic: opens BEGIN IMMEDIATE.  No-op if the link already exists.
    pub fn add_link(
        &self,
        tenant_id: &str,
        source_id: &str,
        target_id: &str,
        link_type: LinkType,
    ) -> Result<()> {
        let mut conn = self.pool.get()?;
        let tx = conn.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;
        // Ensure both endpoints exist & belong to tenant.
        for id in [source_id, target_id] {
            let n: i64 = tx.query_row(
                "SELECT COUNT(*) FROM entities WHERE tenant_id = ?1 AND id = ?2",
                params![tenant_id, id],
                |r| r.get(0),
            )?;
            if n == 0 {
                return Err(AimFsError::NotFound(format!(
                    "entity {id} not found for tenant {tenant_id}"
                )));
            }
        }
        add_link_in_tx(&tx, tenant_id, source_id, target_id, link_type)?;
        log_event_in_tx(
            &tx,
            tenant_id,
            Some(source_id),
            "link_added",
            &serde_json::json!({
                "target": target_id,
                "type": link_type.as_str(),
            }),
        )?;
        tx.commit()?;
        Ok(())
    }

    /// List the outgoing links of an entity.
    pub fn list_outgoing_links(
        &self,
        tenant_id: &str,
        source_id: &str,
    ) -> Result<Vec<(String, LinkType)>> {
        let mut conn = self.pool.get()?;
        let tx = conn.transaction_with_behavior(rusqlite::TransactionBehavior::Deferred)?;
        list_outgoing(&tx, tenant_id, source_id)
    }
}
