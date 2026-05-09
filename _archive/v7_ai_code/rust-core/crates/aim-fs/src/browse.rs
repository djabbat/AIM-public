//! High-level navigation helpers — list projects and patients for the UI
//! without touching the SQLite layer.  Parses just enough of the on-disk
//! files to build a summary card per item.

use crate::error::Result;
use crate::AimFs;
use rusqlite::Connection;
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};

fn count_one(conn: &Connection, sql: &str, tenant: &str) -> Result<u32> {
    let n: i64 = conn.query_row(sql, rusqlite::params![tenant], |r| r.get(0))?;
    Ok(n as u32)
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ProjectSummary {
    pub slug: String,
    pub path: String,
    pub title: Option<String>,
    pub description: Option<String>,
    pub status: Option<String>,
    pub created_at: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PatientSummary {
    pub key: String,
    pub path: String,
    pub surname: Option<String>,
    pub name: Option<String>,
    pub dob: Option<String>,
    pub phone: Option<String>,
    /// First line of the most recent visit's intake.md, if present.
    pub last_visit_complaint: Option<String>,
}

/// Full entity record with linked references — for detail UI.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EntityDetail {
    pub id: String,
    pub schema: String,
    pub schema_version: i64,
    pub status: String,
    pub title: Option<String>,
    pub description: Option<String>,
    pub body: Option<String>,
    pub source: String,
    pub user_id: String,
    pub session_id: Option<String>,
    pub llm_model: Option<String>,
    pub confidence: Option<f64>,
    pub tags: Vec<String>,
    pub scope_global: bool,
    pub scope_user_ids: Vec<String>,
    pub scope_project_ids: Option<Vec<String>>,
    pub scope_patient_ids: Vec<String>,
    pub decay_ttl_days: Option<i64>,
    pub decay_expires_at: Option<String>,
    pub version: i64,
    pub created_at: String,
    pub updated_at: String,
    pub outgoing_links: Vec<LinkRow>,
    pub incoming_links: Vec<LinkRow>,
    pub events: Vec<ActivityEvent>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LinkRow {
    pub other_id: String,
    pub other_title: Option<String>,
    pub link_type: String,
    pub created_at: String,
}

impl AimFs {
    pub fn entity_detail(&self, tenant_id: &str, id: &str) -> Result<EntityDetail> {
        let conn = self.pool.get()?;
        let cols = "id,schema,schema_version,status,title,description,body,source,\
                    user_id,session_id,llm_model,confidence,tags,scope_global,\
                    scope_user_ids,scope_project_ids,scope_patient_ids,\
                    decay_ttl_days,decay_expires_at,version,created_at,updated_at";
        let row = conn.query_row(
            &format!(
                "SELECT {cols} FROM entities WHERE tenant_id = ?1 AND id = ?2"
            ),
            rusqlite::params![tenant_id, id],
            |r| {
                Ok(EntityDetail {
                    id: r.get(0)?,
                    schema: r.get(1)?,
                    schema_version: r.get(2)?,
                    status: r.get(3)?,
                    title: r.get(4)?,
                    description: r.get(5)?,
                    body: r.get(6)?,
                    source: r.get(7)?,
                    user_id: r.get(8)?,
                    session_id: r.get(9)?,
                    llm_model: r.get(10)?,
                    confidence: r.get(11)?,
                    tags: r
                        .get::<_, Option<String>>(12)?
                        .as_deref()
                        .map(|s| serde_json::from_str(s).unwrap_or_default())
                        .unwrap_or_default(),
                    scope_global: r.get::<_, i64>(13)? != 0,
                    scope_user_ids: r
                        .get::<_, Option<String>>(14)?
                        .as_deref()
                        .map(|s| serde_json::from_str(s).unwrap_or_default())
                        .unwrap_or_default(),
                    scope_project_ids: r
                        .get::<_, Option<String>>(15)?
                        .as_deref()
                        .map(|s| serde_json::from_str(s).unwrap_or_default()),
                    scope_patient_ids: r
                        .get::<_, Option<String>>(16)?
                        .as_deref()
                        .map(|s| serde_json::from_str(s).unwrap_or_default())
                        .unwrap_or_default(),
                    decay_ttl_days: r.get(17)?,
                    decay_expires_at: r.get(18)?,
                    version: r.get(19)?,
                    created_at: r.get(20)?,
                    updated_at: r.get(21)?,
                    outgoing_links: vec![],
                    incoming_links: vec![],
                    events: vec![],
                })
            },
        )?;
        let mut detail = row;

        // Outgoing links.
        let mut s = conn.prepare(
            "SELECT l.target_id, e.title, l.link_type, l.created_at \
             FROM links l LEFT JOIN entities e ON e.id = l.target_id \
             WHERE l.tenant_id = ?1 AND l.source_id = ?2",
        )?;
        detail.outgoing_links = s
            .query_map(rusqlite::params![tenant_id, id], |r| {
                Ok(LinkRow {
                    other_id: r.get(0)?,
                    other_title: r.get(1)?,
                    link_type: r.get(2)?,
                    created_at: r.get(3)?,
                })
            })?
            .collect::<std::result::Result<Vec<_>, _>>()?;

        // Incoming links.
        let mut s = conn.prepare(
            "SELECT l.source_id, e.title, l.link_type, l.created_at \
             FROM links l LEFT JOIN entities e ON e.id = l.source_id \
             WHERE l.tenant_id = ?1 AND l.target_id = ?2",
        )?;
        detail.incoming_links = s
            .query_map(rusqlite::params![tenant_id, id], |r| {
                Ok(LinkRow {
                    other_id: r.get(0)?,
                    other_title: r.get(1)?,
                    link_type: r.get(2)?,
                    created_at: r.get(3)?,
                })
            })?
            .collect::<std::result::Result<Vec<_>, _>>()?;

        // Events.
        let mut s = conn.prepare(
            "SELECT event_type, entity_id, created_at FROM events \
             WHERE tenant_id = ?1 AND entity_id = ?2 \
             ORDER BY created_at DESC LIMIT 30",
        )?;
        detail.events = s
            .query_map(rusqlite::params![tenant_id, id], |r| {
                Ok(ActivityEvent {
                    event_type: r.get(0)?,
                    entity_id: r.get(1)?,
                    created_at: r.get(2)?,
                })
            })?
            .collect::<std::result::Result<Vec<_>, _>>()?;

        Ok(detail)
    }
}

/// Recent events — chronological audit feed.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AuditEvent {
    pub id: String,
    pub event_type: String,
    pub entity_id: Option<String>,
    pub entity_title: Option<String>,
    pub entity_schema: Option<String>,
    pub payload: Option<String>,
    pub created_at: String,
}

impl AimFs {
    pub fn list_events(
        &self,
        tenant_id: &str,
        limit: i64,
    ) -> Result<Vec<AuditEvent>> {
        let conn = self.pool.get()?;
        let mut stmt = conn.prepare(
            "SELECT ev.id, ev.event_type, ev.entity_id, e.title, e.schema, ev.payload, ev.created_at \
             FROM events ev \
             LEFT JOIN entities e ON e.id = ev.entity_id \
             WHERE ev.tenant_id = ?1 OR ev.tenant_id = '_system' \
             ORDER BY ev.created_at DESC LIMIT ?2",
        )?;
        let rows = stmt
            .query_map(rusqlite::params![tenant_id, limit], |r| {
                Ok(AuditEvent {
                    id: r.get(0)?,
                    event_type: r.get(1)?,
                    entity_id: r.get(2)?,
                    entity_title: r.get(3)?,
                    entity_schema: r.get(4)?,
                    payload: r.get(5)?,
                    created_at: r.get(6)?,
                })
            })?
            .collect::<std::result::Result<Vec<_>, _>>()?;
        Ok(rows)
    }
}

/// Stats / analytics — entity creation rate per week + top scopes / sources.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Stats {
    pub tenant_id: String,
    pub total_entities: u32,
    pub by_schema: Vec<(String, u32)>,
    pub by_status: Vec<(String, u32)>,
    pub by_source: Vec<(String, u32)>,
    pub by_scope: Vec<(String, u32)>,
    /// (week_iso, total_created) bucketed last 12 weeks.
    pub creation_per_week: Vec<(String, u32)>,
    pub events_total: u32,
    pub avg_approval_latency_ms: Option<f64>,
}

impl AimFs {
    pub fn stats(&self, tenant_id: &str) -> Result<Stats> {
        let conn = self.pool.get()?;

        let total_entities: u32 = conn.query_row(
            "SELECT COUNT(*) FROM entities WHERE tenant_id = ?1",
            rusqlite::params![tenant_id],
            |r| r.get::<_, i64>(0).map(|n| n as u32),
        )?;
        let events_total: u32 = conn
            .query_row(
                "SELECT COUNT(*) FROM events WHERE tenant_id = ?1",
                rusqlite::params![tenant_id],
                |r| r.get::<_, i64>(0).map(|n| n as u32),
            )
            .unwrap_or(0);

        fn group_count(
            conn: &Connection,
            sql: &str,
            tenant: &str,
        ) -> Result<Vec<(String, u32)>> {
            let mut s = conn.prepare(sql)?;
            let rows = s
                .query_map(rusqlite::params![tenant], |r| {
                    Ok((r.get::<_, String>(0)?, r.get::<_, i64>(1)? as u32))
                })?
                .collect::<std::result::Result<Vec<_>, _>>()?;
            Ok(rows)
        }

        let by_schema = group_count(
            &conn,
            "SELECT schema, COUNT(*) FROM entities WHERE tenant_id=?1 \
             GROUP BY schema ORDER BY 2 DESC",
            tenant_id,
        )?;
        let by_status = group_count(
            &conn,
            "SELECT status, COUNT(*) FROM entities WHERE tenant_id=?1 \
             GROUP BY status ORDER BY 2 DESC",
            tenant_id,
        )?;
        let by_source = group_count(
            &conn,
            "SELECT source, COUNT(*) FROM entities WHERE tenant_id=?1 \
             GROUP BY source ORDER BY 2 DESC",
            tenant_id,
        )?;
        let by_scope = group_count(
            &conn,
            "SELECT scope_project_ids, COUNT(*) FROM entities \
             WHERE tenant_id=?1 AND scope_project_ids IS NOT NULL \
             GROUP BY scope_project_ids ORDER BY 2 DESC LIMIT 25",
            tenant_id,
        )?;

        // Creation per ISO-week (last 12 weeks).
        let creation_per_week = group_count(
            &conn,
            "SELECT strftime('%Y-W%W', created_at) AS w, COUNT(*) \
             FROM entities WHERE tenant_id=?1 \
             GROUP BY w ORDER BY w DESC LIMIT 12",
            tenant_id,
        )?;

        // Approval latency: AVG(approve_time - propose_time) for proposals.
        let avg_approval_latency_ms: Option<f64> = conn
            .query_row(
                "SELECT AVG((julianday(updated_at) - julianday(created_at)) * 86400000.0) \
                 FROM proposals WHERE tenant_id=?1 AND status='approved'",
                rusqlite::params![tenant_id],
                |r| r.get::<_, Option<f64>>(0),
            )
            .unwrap_or(None);

        Ok(Stats {
            tenant_id: tenant_id.to_string(),
            total_entities,
            by_schema,
            by_status,
            by_source,
            by_scope,
            creation_per_week,
            events_total,
            avg_approval_latency_ms,
        })
    }
}

/// Per-tenant aggregated user profile — derived view, not stored.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ProfileView {
    pub tenant_id: String,
    pub identity_facts: Vec<ProfileEntry>,
    pub preferences: Vec<ProfileEntry>,
    pub feedback_rules: Vec<ProfileEntry>,
    pub recent_decisions: Vec<ProfileEntry>,
    pub contacts: Vec<ProfileEntry>,
    pub counts: ProfileCounts,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ProfileCounts {
    pub user_facts: u32,
    pub feedback_rules: u32,
    pub projects: u32,
    pub patients: u32,
    pub contacts: u32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ProfileEntry {
    pub id: String,
    pub title: Option<String>,
    pub description: Option<String>,
    pub schema: String,
    pub status: String,
    pub tags: Vec<String>,
    pub scope_project_ids: Option<Vec<String>>,
    pub created_at: String,
    pub snippet: Option<String>,
}

/// Per-project aggregated activity — derived view from entities + events.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ProjectActivity {
    pub slug: String,
    pub summary: ProjectSummary,
    pub entries: Vec<ProfileEntry>,
    pub recent_events: Vec<ActivityEvent>,
    pub counts: ProjectCounts,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ProjectCounts {
    pub feedback_rules: u32,
    pub project_state: u32,
    pub audits: u32,
    pub references: u32,
    pub other: u32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ActivityEvent {
    pub event_type: String,
    pub entity_id: Option<String>,
    pub created_at: String,
}

impl AimFs {
    pub fn profile_view(&self, tenant_id: &str) -> Result<ProfileView> {
        let conn = self.pool.get()?;
        let collect = |sql: &str, args: &[&dyn rusqlite::ToSql]| -> Result<Vec<ProfileEntry>> {
            let mut stmt = conn.prepare(sql)?;
            let rows = stmt
                .query_map(args, |r| {
                    Ok(ProfileEntry {
                        id: r.get(0)?,
                        title: r.get(1)?,
                        description: r.get(2)?,
                        schema: r.get(3)?,
                        status: r.get(4)?,
                        tags: r
                            .get::<_, Option<String>>(5)?
                            .as_deref()
                            .map(|s| serde_json::from_str(s).unwrap_or_default())
                            .unwrap_or_default(),
                        scope_project_ids: r
                            .get::<_, Option<String>>(6)?
                            .as_deref()
                            .map(|s| serde_json::from_str(s).unwrap_or_default()),
                        created_at: r.get(7)?,
                        snippet: r.get::<_, Option<String>>(8)?.map(|b| {
                            let s = b.replace('\n', " ");
                            s.chars().take(200).collect()
                        }),
                    })
                })?
                .collect::<std::result::Result<Vec<_>, _>>()?;
            Ok(rows)
        };
        let cols =
            "id,title,description,schema,status,tags,scope_project_ids,created_at,body";

        let identity_facts = collect(
            &format!(
                "SELECT {cols} FROM entities WHERE tenant_id = ?1 \
                 AND schema IN ('user_fact_v1','user_v1','user_directive_v1') \
                 AND status = 'active' ORDER BY created_at DESC LIMIT 30"
            ),
            &[&tenant_id],
        )?;
        let preferences = collect(
            &format!(
                "SELECT {cols} FROM entities WHERE tenant_id = ?1 \
                 AND schema = 'feedback_v1' AND status = 'active' \
                 AND (tags LIKE '%language%' OR tags LIKE '%style%' \
                      OR title LIKE '%preference%' OR title LIKE '%language%') \
                 ORDER BY created_at DESC LIMIT 15"
            ),
            &[&tenant_id],
        )?;
        let feedback_rules = collect(
            &format!(
                "SELECT {cols} FROM entities WHERE tenant_id = ?1 \
                 AND schema = 'feedback_v1' AND status = 'active' \
                 ORDER BY created_at DESC LIMIT 30"
            ),
            &[&tenant_id],
        )?;
        let recent_decisions = collect(
            &format!(
                "SELECT {cols} FROM entities WHERE tenant_id = ?1 \
                 AND schema IN ('project_state_v1','fact_v1','audit_v1') \
                 AND status = 'active' ORDER BY created_at DESC LIMIT 20"
            ),
            &[&tenant_id],
        )?;
        let contacts = collect(
            &format!(
                "SELECT {cols} FROM entities WHERE tenant_id = ?1 \
                 AND schema = 'contact_v1' AND status = 'active' \
                 ORDER BY created_at DESC LIMIT 30"
            ),
            &[&tenant_id],
        )?;

        let counts = ProfileCounts {
            user_facts: count_one(
                &conn,
                "SELECT COUNT(*) FROM entities WHERE tenant_id=?1 AND schema IN ('user_fact_v1','user_v1','user_directive_v1') AND status='active'",
                tenant_id,
            )?,
            feedback_rules: count_one(
                &conn,
                "SELECT COUNT(*) FROM entities WHERE tenant_id=?1 AND schema='feedback_v1' AND status='active'",
                tenant_id,
            )?,
            projects: self
                .list_projects(tenant_id)
                .map(|v| v.len() as u32)
                .unwrap_or(0),
            patients: self
                .list_patients(tenant_id)
                .map(|v| v.len() as u32)
                .unwrap_or(0),
            contacts: count_one(
                &conn,
                "SELECT COUNT(*) FROM entities WHERE tenant_id=?1 AND schema='contact_v1' AND status='active'",
                tenant_id,
            )?,
        };

        Ok(ProfileView {
            tenant_id: tenant_id.to_string(),
            identity_facts,
            preferences,
            feedback_rules,
            recent_decisions,
            contacts,
            counts,
        })
    }

    pub fn project_activity(
        &self,
        tenant_id: &str,
        slug: &str,
    ) -> Result<ProjectActivity> {
        let conn = self.pool.get()?;
        let summary = self
            .list_projects(tenant_id)?
            .into_iter()
            .find(|p| p.slug == slug)
            .unwrap_or(ProjectSummary {
                slug: slug.to_string(),
                path: String::new(),
                title: None,
                description: None,
                status: None,
                created_at: None,
            });

        let scope_pat = format!("%\"{}\"%", slug);
        let mut stmt = conn.prepare(
            "SELECT id,title,description,schema,status,tags,scope_project_ids,created_at,body \
             FROM entities WHERE tenant_id = ?1 \
               AND scope_project_ids LIKE ?2 AND status IN ('active','disputed','superseded') \
             ORDER BY created_at DESC LIMIT 100",
        )?;
        let entries: Vec<ProfileEntry> = stmt
            .query_map(rusqlite::params![tenant_id, scope_pat], |r| {
                Ok(ProfileEntry {
                    id: r.get(0)?,
                    title: r.get(1)?,
                    description: r.get(2)?,
                    schema: r.get(3)?,
                    status: r.get(4)?,
                    tags: r
                        .get::<_, Option<String>>(5)?
                        .as_deref()
                        .map(|s| serde_json::from_str(s).unwrap_or_default())
                        .unwrap_or_default(),
                    scope_project_ids: r
                        .get::<_, Option<String>>(6)?
                        .as_deref()
                        .map(|s| serde_json::from_str(s).unwrap_or_default()),
                    created_at: r.get(7)?,
                    snippet: r.get::<_, Option<String>>(8)?.map(|b| {
                        let s = b.replace('\n', " ");
                        s.chars().take(200).collect()
                    }),
                })
            })?
            .collect::<std::result::Result<Vec<_>, _>>()?;

        let mut counts = ProjectCounts {
            feedback_rules: 0,
            project_state: 0,
            audits: 0,
            references: 0,
            other: 0,
        };
        for e in &entries {
            match e.schema.as_str() {
                "feedback_v1" => counts.feedback_rules += 1,
                "project_state_v1" => counts.project_state += 1,
                "audit_v1" => counts.audits += 1,
                "reference_v1" => counts.references += 1,
                _ => counts.other += 1,
            }
        }

        let mut stmt2 = conn.prepare(
            "SELECT event_type, entity_id, created_at FROM events \
             WHERE tenant_id = ?1 AND entity_id IN \
                (SELECT id FROM entities WHERE tenant_id=?1 AND scope_project_ids LIKE ?2) \
             ORDER BY created_at DESC LIMIT 50",
        )?;
        let recent_events = stmt2
            .query_map(rusqlite::params![tenant_id, scope_pat], |r| {
                Ok(ActivityEvent {
                    event_type: r.get(0)?,
                    entity_id: r.get(1)?,
                    created_at: r.get(2)?,
                })
            })?
            .collect::<std::result::Result<Vec<_>, _>>()?;

        Ok(ProjectActivity {
            slug: slug.to_string(),
            summary,
            entries,
            recent_events,
            counts,
        })
    }

    pub fn list_projects(&self, user_id: &str) -> Result<Vec<ProjectSummary>> {
        let dir = self.root().join("users").join(user_id).join("projects");
        if !dir.is_dir() {
            return Ok(vec![]);
        }
        let mut out = vec![];
        for entry in std::fs::read_dir(&dir)? {
            let entry = entry?;
            if !entry.file_type()?.is_dir() {
                continue;
            }
            let p = entry.path();
            let slug = p
                .file_name()
                .map(|s| s.to_string_lossy().to_string())
                .unwrap_or_default();
            if slug.starts_with('_') {
                continue;
            }
            out.push(read_project_summary(&p, slug));
        }
        out.sort_by(|a, b| a.slug.cmp(&b.slug));
        Ok(out)
    }

    pub fn list_patients(&self, doctor_id: &str) -> Result<Vec<PatientSummary>> {
        let dir = self.root().join("users").join(doctor_id).join("patients");
        if !dir.is_dir() {
            return Ok(vec![]);
        }
        let mut out = vec![];
        for entry in std::fs::read_dir(&dir)? {
            let entry = entry?;
            if !entry.file_type()?.is_dir() {
                continue;
            }
            let p = entry.path();
            let key = p
                .file_name()
                .map(|s| s.to_string_lossy().to_string())
                .unwrap_or_default();
            if key.starts_with('_') {
                continue;
            }
            out.push(read_patient_summary(&p, key));
        }
        out.sort_by(|a, b| a.key.cmp(&b.key));
        Ok(out)
    }
}

fn read_project_summary(dir: &Path, slug: String) -> ProjectSummary {
    let title = read_title(&dir.join("CONCEPT.md"))
        .or_else(|| read_title(&dir.join("README.md")));
    let description = read_first_paragraph(&dir.join("README.md"))
        .or_else(|| read_first_paragraph(&dir.join("CONCEPT.md")));
    let (status, created_at) = read_state_md(&dir.join("STATE.md"));
    ProjectSummary {
        slug,
        path: dir.display().to_string(),
        title,
        description,
        status,
        created_at,
    }
}

fn read_patient_summary(dir: &Path, key: String) -> PatientSummary {
    let mut sum = PatientSummary {
        key: key.clone(),
        path: dir.display().to_string(),
        surname: None,
        name: None,
        dob: None,
        phone: None,
        last_visit_complaint: None,
    };

    if let Ok(s) = std::fs::read_to_string(dir.join("identity.toml")) {
        for line in s.lines() {
            if let Some((k, v)) = line.split_once('=') {
                let k = k.trim();
                let v = v.trim().trim_matches('"').to_string();
                match k {
                    "surname" => sum.surname = Some(v),
                    "name" => sum.name = Some(v),
                    "dob" => sum.dob = Some(v),
                    "phone" => sum.phone = Some(v),
                    _ => {}
                }
            }
        }
    }
    // Fall back: parse <Surname>_<Name>_<YYYY_MM_DD> from folder name.
    if sum.surname.is_none() {
        let parts: Vec<&str> = key.split('_').collect();
        if parts.len() >= 5 {
            sum.surname = Some(parts[0].to_string());
            sum.name = Some(parts[1].to_string());
            sum.dob = Some(parts[2..5].join("_"));
        } else if parts.len() == 3 {
            // Surname_Name_DOB — DOB came in as one token, unusual.
            sum.surname = Some(parts[0].to_string());
            sum.name = Some(parts[1].to_string());
            sum.dob = Some(parts[2].to_string());
        }
    }

    // Latest visit — pick the highest-named directory under visits/.
    let visits_dir = dir.join("visits");
    if visits_dir.is_dir() {
        let mut visits: Vec<PathBuf> = std::fs::read_dir(&visits_dir)
            .ok()
            .into_iter()
            .flatten()
            .filter_map(|e| e.ok())
            .map(|e| e.path())
            .filter(|p| p.is_dir())
            .collect();
        visits.sort();
        if let Some(latest) = visits.last() {
            for cand in ["intake.md", "_first_intake.md"] {
                if let Ok(s) = std::fs::read_to_string(latest.join(cand)) {
                    if let Some(p) = first_non_heading_paragraph(&s) {
                        sum.last_visit_complaint = Some(p);
                        break;
                    }
                }
            }
        }
        // patient.yaml writes _first_intake.md DIRECTLY in visits/ (not a subdir),
        // so try that too:
        for cand in ["_first_intake.md", "intake.md"] {
            let p = visits_dir.join(cand);
            if p.is_file() {
                if let Ok(s) = std::fs::read_to_string(&p) {
                    if let Some(p) = first_non_heading_paragraph(&s) {
                        sum.last_visit_complaint
                            .get_or_insert(p);
                    }
                }
            }
        }
    }

    sum
}

fn read_title(path: &Path) -> Option<String> {
    let s = std::fs::read_to_string(path).ok()?;
    for line in s.lines() {
        let trimmed = line.trim_start_matches(|c: char| c == '#' || c.is_whitespace());
        if !trimmed.is_empty() && line.starts_with('#') {
            return Some(trimmed.to_string());
        }
    }
    None
}

fn read_first_paragraph(path: &Path) -> Option<String> {
    let s = std::fs::read_to_string(path).ok()?;
    first_non_heading_paragraph(&s)
}

fn first_non_heading_paragraph(s: &str) -> Option<String> {
    let mut buf = String::new();
    for line in s.lines() {
        if line.starts_with('#') || line.trim().is_empty() {
            if !buf.is_empty() {
                return Some(buf.trim().to_string());
            }
            continue;
        }
        if !buf.is_empty() {
            buf.push(' ');
        }
        buf.push_str(line.trim());
    }
    if buf.is_empty() {
        None
    } else {
        Some(buf.trim().to_string())
    }
}

fn read_state_md(path: &Path) -> (Option<String>, Option<String>) {
    let s = match std::fs::read_to_string(path) {
        Ok(s) => s,
        Err(_) => return (None, None),
    };
    let mut status = None;
    let mut created_at = None;
    for line in s.lines() {
        if let Some(rest) = line.strip_prefix("status:") {
            status = Some(rest.trim().to_string());
        } else if let Some(rest) = line.strip_prefix("created_at:") {
            created_at = Some(rest.trim().to_string());
        }
    }
    (status, created_at)
}
