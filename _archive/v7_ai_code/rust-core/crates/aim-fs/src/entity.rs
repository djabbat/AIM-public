use crate::error::Result;
use crate::types::*;
use crate::AimFs;
use chrono::{Duration, Utc};
use rusqlite::{params, Transaction};
use sha2::{Digest, Sha256};
use ulid::Ulid;

pub(crate) fn create_entity_in_tx(
    tx: &Transaction,
    tenant_id: &str,
    new: &NewEntity,
    initial_status: EntityStatus,
) -> Result<String> {
    let id = Ulid::new().to_string();
    let now = Utc::now().to_rfc3339();
    let expires_at = new
        .decay_ttl_days
        .map(|d| (Utc::now() + Duration::days(d)).to_rfc3339());

    tx.execute(
        "INSERT INTO entities (
            id, tenant_id, schema, schema_version, title, description, body,
            status, confidence, source, user_id, session_id, llm_model,
            requires_verification, scope_global, scope_user_ids, scope_project_ids,
            scope_patient_ids, tags, decay_ttl_days, decay_expires_at, decay_on_expire,
            version, created_at, updated_at
         ) VALUES (
            ?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14,?15,?16,?17,?18,?19,?20,?21,?22,1,?23,?24
         )",
        params![
            id,
            tenant_id,
            new.schema,
            new.schema_version,
            new.title,
            new.description,
            new.body,
            initial_status.as_str(),
            new.confidence,
            new.source.as_str(),
            new.user_id,
            new.session_id,
            new.llm_model,
            new.requires_verification as i64,
            new.scope_global as i64,
            serde_json::to_string(&new.scope_user_ids)?,
            new.scope_project_ids
                .as_ref()
                .map(|v| serde_json::to_string(v))
                .transpose()?,
            serde_json::to_string(&new.scope_patient_ids)?,
            serde_json::to_string(&new.tags)?,
            new.decay_ttl_days,
            expires_at,
            new.decay_on_expire.as_deref().unwrap_or("keep"),
            now,
            now,
        ],
    )?;

    // Initial version row
    let body_hash = body_hash(&new.body);
    tx.execute(
        "INSERT INTO versions (id, entity_id, data, hash, created_at, tenant_id)
         VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
        params![
            Ulid::new().to_string(),
            id,
            new.body,
            body_hash,
            now,
            tenant_id
        ],
    )?;

    crate::events::log_event_in_tx(tx, tenant_id, Some(&id), "created", &serde_json::json!({}))?;
    Ok(id)
}

pub(crate) fn body_hash(body: &Option<String>) -> String {
    let mut h = Sha256::new();
    h.update(body.as_deref().unwrap_or("").as_bytes());
    format!("sha256:{}", hex::encode(h.finalize()))
}

impl AimFs {
    pub fn get_entity(&self, tenant_id: &str, id: &str) -> Result<Entity> {
        let conn = self.pool.get()?;
        let mut stmt = conn.prepare(
            "SELECT id,tenant_id,schema,schema_version,title,description,body,
                    status,confidence,source,user_id,session_id,llm_model,
                    requires_verification,scope_global,scope_user_ids,scope_project_ids,
                    scope_patient_ids,tags,decay_ttl_days,decay_expires_at,decay_on_expire,
                    version,created_at,updated_at
             FROM entities WHERE tenant_id = ?1 AND id = ?2",
        )?;
        let row = stmt.query_row(params![tenant_id, id], |r| {
            Ok((
                r.get::<_, String>(0)?,
                r.get::<_, String>(1)?,
                r.get::<_, String>(2)?,
                r.get::<_, i64>(3)?,
                r.get::<_, Option<String>>(4)?,
                r.get::<_, Option<String>>(5)?,
                r.get::<_, Option<String>>(6)?,
                r.get::<_, String>(7)?,
                r.get::<_, Option<f64>>(8)?,
                r.get::<_, String>(9)?,
                r.get::<_, String>(10)?,
                r.get::<_, Option<String>>(11)?,
                r.get::<_, Option<String>>(12)?,
                r.get::<_, i64>(13)?,
                r.get::<_, i64>(14)?,
                r.get::<_, Option<String>>(15)?,
                r.get::<_, Option<String>>(16)?,
                r.get::<_, Option<String>>(17)?,
                r.get::<_, Option<String>>(18)?,
                r.get::<_, Option<i64>>(19)?,
                r.get::<_, Option<String>>(20)?,
                r.get::<_, String>(21)?,
                r.get::<_, i64>(22)?,
                r.get::<_, String>(23)?,
                r.get::<_, String>(24)?,
            ))
        })?;
        let (
            id,
            tenant_id,
            schema,
            schema_version,
            title,
            description,
            body,
            status,
            confidence,
            source,
            user_id,
            session_id,
            llm_model,
            req_v,
            sg,
            sui,
            spi,
            spt,
            tags,
            ttl,
            exp,
            on_exp,
            ver,
            cat,
            uat,
        ) = row;
        Ok(Entity {
            id,
            tenant_id,
            schema,
            schema_version,
            title,
            description,
            body,
            status: EntityStatus::from_str(&status).unwrap_or(EntityStatus::Pending),
            confidence,
            source,
            user_id,
            session_id,
            llm_model,
            requires_verification: req_v != 0,
            scope_global: sg != 0,
            scope_user_ids: sui
                .as_deref()
                .map(serde_json::from_str)
                .transpose()
                .unwrap_or(None)
                .unwrap_or_default(),
            scope_project_ids: spi
                .as_deref()
                .map(serde_json::from_str)
                .transpose()
                .unwrap_or(None),
            scope_patient_ids: spt
                .as_deref()
                .map(serde_json::from_str)
                .transpose()
                .unwrap_or(None)
                .unwrap_or_default(),
            tags: tags
                .as_deref()
                .map(serde_json::from_str)
                .transpose()
                .unwrap_or(None)
                .unwrap_or_default(),
            decay_ttl_days: ttl,
            decay_expires_at: exp,
            decay_on_expire: on_exp,
            version: ver,
            created_at: cat,
            updated_at: uat,
        })
    }
}

