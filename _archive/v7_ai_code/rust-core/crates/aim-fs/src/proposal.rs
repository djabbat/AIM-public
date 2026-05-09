use crate::entity::create_entity_in_tx;
use crate::error::{AimFsError, Result};
use crate::events::log_event_in_tx;
use crate::links::{add_link_in_tx, find_active_contradictors};
use crate::search::SearchScope;
use crate::types::*;
use crate::AimFs;
use chrono::Utc;
use rusqlite::{params, OptionalExtension};
use ulid::Ulid;

/// Threshold for "may be duplicate" warning. Empirically tuned over the
/// 358-entity production corpus — 2800 sits between the average BM25 score
/// for unrelated co-token false-positives (~2700) and a real same-topic hit
/// (~3100+). Title-on-title hits in feedback_v1 routinely exceed 3000.
const DUP_SCORE_THRESHOLD: i64 = 2_800;

impl AimFs {
    /// Propose a new entity. Goes through approval queue unless auto-approved.
    /// Auto-approve rules (per spec §4.3):
    ///   - source = user_command + policy.auto_approve_user_commands → active immediately
    ///   - source = system + policy.auto_approve_service_events → active
    ///   - confidence >= threshold → active
    /// Otherwise: entity = pending, proposal row created, awaits approve/reject.
    pub fn propose(
        &self,
        tenant_id: &str,
        new: NewEntity,
        rationale: Option<&str>,
        idempotency_key: Option<&str>,
        policy: &ApprovalPolicy,
    ) -> Result<ProposeOutcome> {
        let mut conn = self.pool.get()?;
        let tx = conn.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;

        // 1. idempotency
        if let Some(key) = idempotency_key {
            if let Some((status, result)) = lookup_idempotency(&tx, tenant_id, key)? {
                if status == "done" {
                    let outcome: ProposeOutcome = serde_json::from_str(
                        result
                            .as_deref()
                            .ok_or_else(|| AimFsError::Other("idempotent done w/o result".into()))?,
                    )?;
                    return Ok(outcome);
                } else {
                    return Err(AimFsError::IdempotencyInFlight(key.to_string()));
                }
            }
            insert_idempotency_processing(&tx, tenant_id, key)?;
        }

        // 1b. schema validation (SPEC §3.2)
        crate::schemas::validate(&new)?;

        // 2. auto-approve check
        let auto_approve = should_auto_approve(&new, policy);
        let initial_status = if auto_approve {
            EntityStatus::Active
        } else {
            EntityStatus::Pending
        };

        // 3. create entity
        let entity_id = create_entity_in_tx(&tx, tenant_id, &new, initial_status)?;

        // 3a. insert initial links (depends_on / refines / supersedes / contradicts ...)
        for link in &new.initial_links {
            add_link_in_tx(&tx, tenant_id, &entity_id, &link.target_id, link.link_type)?;
            // supersedes → mark target as `superseded`
            if link.link_type == LinkType::Supersedes {
                tx.execute(
                    "UPDATE entities SET status='superseded',
                                         version = version + 1,
                                         updated_at = ?3
                     WHERE tenant_id = ?1 AND id = ?2 AND status = 'active'",
                    params![tenant_id, link.target_id, Utc::now().to_rfc3339()],
                )?;
                log_event_in_tx(
                    &tx,
                    tenant_id,
                    Some(&link.target_id),
                    "superseded",
                    &serde_json::json!({"by": entity_id}),
                )?;
            }
        }

        // 3b. contradiction check — if the new entity's contradicts links
        // hit an active entity (or the inverse), put new entity in `disputed`.
        let contradictors = find_active_contradictors(&tx, tenant_id, &entity_id)?;
        let final_status = if !contradictors.is_empty() {
            tx.execute(
                "UPDATE entities SET status='disputed', version = version + 1, updated_at = ?3
                 WHERE tenant_id = ?1 AND id = ?2",
                params![tenant_id, entity_id, Utc::now().to_rfc3339()],
            )?;
            log_event_in_tx(
                &tx,
                tenant_id,
                Some(&entity_id),
                "disputed",
                &serde_json::json!({"contradictors": contradictors}),
            )?;
            // Mirror the dispute on the active counterpart(s) so they are
            // visible in the inbox.
            for other in &contradictors {
                tx.execute(
                    "UPDATE entities SET status='disputed', version = version + 1, updated_at = ?3
                     WHERE tenant_id = ?1 AND id = ?2 AND status = 'active'",
                    params![tenant_id, other, Utc::now().to_rfc3339()],
                )?;
                log_event_in_tx(
                    &tx,
                    tenant_id,
                    Some(other),
                    "disputed",
                    &serde_json::json!({"by": entity_id}),
                )?;
            }
            EntityStatus::Disputed
        } else {
            initial_status
        };

        // 4. create proposal row (always; lets us audit even auto-approved decisions)
        let proposal_id = Ulid::new().to_string();
        let now = Utc::now().to_rfc3339();
        let proposal_status = if auto_approve {
            ProposalStatus::Approved
        } else {
            ProposalStatus::Pending
        };
        let approved_by = if auto_approve {
            Some(new.user_id.clone())
        } else {
            None
        };
        tx.execute(
            "INSERT INTO proposals
             (id, tenant_id, entity_id, proposal_type, status, proposed_data,
              rationale, proposed_by_user_id, approved_by_user_id, blocked_reason,
              version_at_proposal, created_at, updated_at)
             VALUES (?1,?2,?3,'create',?4,?5,?6,?7,?8,NULL,1,?9,?10)",
            params![
                proposal_id,
                tenant_id,
                entity_id,
                proposal_status.as_str(),
                serde_json::to_string(&new)?,
                rationale,
                new.user_id,
                approved_by,
                now,
                now,
            ],
        )?;

        // 5. log event
        log_event_in_tx(
            &tx,
            tenant_id,
            Some(&entity_id),
            if auto_approve { "auto_approved" } else { "proposed" },
            &serde_json::json!({"proposal_id": proposal_id, "auto": auto_approve}),
        )?;

        let outcome = ProposeOutcome {
            entity_id: entity_id.clone(),
            proposal_id: proposal_id.clone(),
            auto_approved: auto_approve,
            entity_status: final_status,
            similar_existing: vec![], // filled below, after commit
        };

        // 6. mark idempotency done
        if let Some(key) = idempotency_key {
            mark_idempotency_done(&tx, key, &serde_json::to_string(&outcome)?)?;
        }

        tx.commit()?;

        // Post-commit: search for similar existing entities. Read-only, so
        // no need to be in the BEGIN IMMEDIATE tx.  Only run for schemas where
        // dupes are common (feedback / fact / user_fact).  Skip when this
        // entity itself was just-created (it would always match strongly).
        let mut outcome = outcome;
        if matches!(
            outcome.entity_status,
            EntityStatus::Pending | EntityStatus::Disputed
        ) && matches!(
            new.schema.as_str(),
            "feedback_v1" | "fact_v1" | "user_fact_v1"
        ) {
            if let Some(t) = &new.title {
                if !t.trim().is_empty() {
                    let scope = SearchScope {
                        schema: Some(new.schema.clone()),
                        status: Some("active".into()),
                        ..Default::default()
                    };
                    if let Ok(hits) = self.search(tenant_id, t, &scope, 5) {
                        outcome.similar_existing = hits
                            .into_iter()
                            .filter(|h| h.score >= DUP_SCORE_THRESHOLD && h.id != outcome.entity_id)
                            .map(|h| {
                                let suggest = if h.score >= 4_500 {
                                    "refines".to_string()
                                } else {
                                    "references".to_string()
                                };
                                SimilarHit {
                                    id: h.id,
                                    title: h.title,
                                    schema: h.schema,
                                    score: h.score,
                                    suggest_link_type: suggest,
                                }
                            })
                            .collect();
                    }
                }
            }
        }

        Ok(outcome)
    }

    /// Approve a pending proposal: entity → active, proposal → approved.
    /// Optimistic-locking by version_at_proposal.
    pub fn approve_proposal(
        &self,
        tenant_id: &str,
        proposal_id: &str,
        actor: &Actor,
    ) -> Result<()> {
        let mut conn = self.pool.get()?;
        let tx = conn.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;

        let (entity_id, status, version_at): (String, String, i64) = tx.query_row(
            "SELECT entity_id, status, version_at_proposal FROM proposals
             WHERE tenant_id = ?1 AND id = ?2",
            params![tenant_id, proposal_id],
            |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
        )?;
        if status != "pending" {
            return Err(AimFsError::BadTransition {
                from: status,
                to: "approved".into(),
            });
        }

        // Optimistic lock: ensure entity version unchanged.
        let current_version: i64 = tx.query_row(
            "SELECT version FROM entities WHERE tenant_id = ?1 AND id = ?2",
            params![tenant_id, entity_id],
            |r| r.get(0),
        )?;
        if current_version != version_at {
            return Err(AimFsError::OptimisticLock(entity_id));
        }

        let now = Utc::now().to_rfc3339();
        tx.execute(
            "UPDATE entities SET status='active', version = version + 1, updated_at = ?3
             WHERE tenant_id = ?1 AND id = ?2",
            params![tenant_id, entity_id, now],
        )?;
        tx.execute(
            "UPDATE proposals SET status='approved', approved_by_user_id = ?3, updated_at = ?4
             WHERE tenant_id = ?1 AND id = ?2",
            params![tenant_id, proposal_id, actor.user_id, now],
        )?;
        log_event_in_tx(
            &tx,
            tenant_id,
            Some(&entity_id),
            "approved",
            &serde_json::json!({
                "proposal_id": proposal_id,
                "approved_by": actor.user_id,
                "session_id": actor.session_id,
            }),
        )?;
        tx.commit()?;
        Ok(())
    }

    /// Reject a pending proposal.  Entity status preserved (often pending → stays pending
    /// for audit; downstream may delete it).  Per SPEC §4.4.
    pub fn reject_proposal(
        &self,
        tenant_id: &str,
        proposal_id: &str,
        actor: &Actor,
        reason: Option<&str>,
    ) -> Result<()> {
        let mut conn = self.pool.get()?;
        let tx = conn.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;

        let (entity_id, status): (String, String) = tx.query_row(
            "SELECT entity_id, status FROM proposals
             WHERE tenant_id = ?1 AND id = ?2",
            params![tenant_id, proposal_id],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )?;
        if status != "pending" {
            return Err(AimFsError::BadTransition {
                from: status,
                to: "rejected".into(),
            });
        }

        let now = Utc::now().to_rfc3339();
        tx.execute(
            "UPDATE proposals SET status='rejected', approved_by_user_id = ?3,
             blocked_reason = ?4, updated_at = ?5
             WHERE tenant_id = ?1 AND id = ?2",
            params![tenant_id, proposal_id, actor.user_id, reason, now],
        )?;
        log_event_in_tx(
            &tx,
            tenant_id,
            Some(&entity_id),
            "rejected",
            &serde_json::json!({
                "proposal_id": proposal_id,
                "rejected_by": actor.user_id,
                "reason": reason,
            }),
        )?;
        tx.commit()?;
        Ok(())
    }

    pub fn list_pending(&self, tenant_id: &str, limit: i64) -> Result<Vec<Proposal>> {
        let conn = self.pool.get()?;
        let mut stmt = conn.prepare(
            "SELECT id,tenant_id,entity_id,proposal_type,status,proposed_data,
                    rationale,proposed_by_user_id,approved_by_user_id,blocked_reason,
                    version_at_proposal,created_at,updated_at
             FROM proposals
             WHERE tenant_id = ?1 AND status = 'pending'
             ORDER BY created_at DESC
             LIMIT ?2",
        )?;
        let rows = stmt
            .query_map(params![tenant_id, limit], |r| {
                Ok(Proposal {
                    id: r.get(0)?,
                    tenant_id: r.get(1)?,
                    entity_id: r.get(2)?,
                    proposal_type: parse_proposal_type(&r.get::<_, String>(3)?),
                    status: parse_proposal_status(&r.get::<_, String>(4)?),
                    proposed_data: r.get(5)?,
                    rationale: r.get(6)?,
                    proposed_by_user_id: r.get(7)?,
                    approved_by_user_id: r.get(8)?,
                    blocked_reason: r.get(9)?,
                    version_at_proposal: r.get(10)?,
                    created_at: r.get(11)?,
                    updated_at: r.get(12)?,
                })
            })?
            .collect::<std::result::Result<Vec<_>, _>>()?;
        Ok(rows)
    }
}

fn parse_proposal_type(s: &str) -> ProposalType {
    match s {
        "update" => ProposalType::Update,
        "revert" => ProposalType::Revert,
        "delete" => ProposalType::Delete,
        _ => ProposalType::Create,
    }
}
fn parse_proposal_status(s: &str) -> ProposalStatus {
    match s {
        "approved" => ProposalStatus::Approved,
        "rejected" => ProposalStatus::Rejected,
        "blocked" => ProposalStatus::Blocked,
        _ => ProposalStatus::Pending,
    }
}

fn should_auto_approve(new: &NewEntity, policy: &ApprovalPolicy) -> bool {
    let schema = new.schema.split('_').next().unwrap_or("");
    if policy
        .require_approval_for
        .iter()
        .any(|s| s.as_str() == schema)
    {
        return false;
    }
    match new.source {
        Source::UserCommand => policy.auto_approve_user_commands,
        Source::System => policy.auto_approve_service_events,
        Source::UserMessage => new
            .confidence
            .map(|c| c >= policy.auto_approve_observational_with_confidence_above)
            .unwrap_or(false),
    }
}

fn lookup_idempotency(
    tx: &rusqlite::Transaction,
    tenant_id: &str,
    key: &str,
) -> Result<Option<(String, Option<String>)>> {
    let row = tx
        .query_row(
            "SELECT status, result FROM idempotency
             WHERE tenant_id = ?1 AND key = ?2",
            params![tenant_id, key],
            |r| Ok((r.get::<_, String>(0)?, r.get::<_, Option<String>>(1)?)),
        )
        .optional()?;
    Ok(row)
}

fn insert_idempotency_processing(
    tx: &rusqlite::Transaction,
    tenant_id: &str,
    key: &str,
) -> Result<()> {
    tx.execute(
        "INSERT INTO idempotency (key, status, tenant_id, created_at)
         VALUES (?1, 'processing', ?2, ?3)",
        params![key, tenant_id, Utc::now().to_rfc3339()],
    )?;
    Ok(())
}
fn mark_idempotency_done(tx: &rusqlite::Transaction, key: &str, result: &str) -> Result<()> {
    tx.execute(
        "UPDATE idempotency SET status='done', result = ?2 WHERE key = ?1",
        params![key, result],
    )?;
    Ok(())
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct ProposeOutcome {
    pub entity_id: String,
    pub proposal_id: String,
    pub auto_approved: bool,
    pub entity_status: EntityStatus,
    /// Existing active entities that closely match the new title — may be
    /// duplicates. Caller decides whether to merge / supersede / proceed.
    /// Empty when no FTS5 hit crosses [`DUP_SCORE_THRESHOLD`].
    #[serde(default)]
    pub similar_existing: Vec<SimilarHit>,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct SimilarHit {
    pub id: String,
    pub title: Option<String>,
    pub schema: String,
    pub score: i64,
    /// Suggested link type for the doctor to add explicitly:
    ///   `refines`     — score ≥ 4_500 (very strong overlap → likely refinement)
    ///   `references`  — 2_800 ≤ score < 4_500 (related, worth linking)
    pub suggest_link_type: String,
}
