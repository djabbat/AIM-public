//! Search layer for AIM_FS (SPEC §5.2).
//!
//! MVP: SQL `LIKE` over `entities.title` and `entities.body`, scoped by
//! `tenant_id` and optionally by entity status / schema / project / patient.
//! FTS5 / hybrid embeddings — Phase 2.

use crate::error::Result;
use crate::AimFs;
use rusqlite::params;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct SearchScope {
    /// Restrict to entities whose `schema = …`.
    pub schema: Option<String>,
    /// Restrict to entities whose `status = …` (default: active).
    pub status: Option<String>,
    /// Restrict to entities whose JSON `scope_project_ids` contains this id.
    pub project_id: Option<String>,
    /// Restrict to entities whose JSON `scope_patient_ids` contains this id.
    pub patient_id: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Hit {
    pub id: String,
    pub schema: String,
    pub status: String,
    pub title: Option<String>,
    pub description: Option<String>,
    /// First 200 chars of the body, for preview.
    pub snippet: Option<String>,
    pub created_at: String,
    /// Crude rank: number of times the query appears in title+body.
    pub score: i64,
}

impl AimFs {
    /// Hybrid full-text search.
    ///
    /// Strategy (Phase 2 — closes SPEC §5.2 L4 gap vs Claude memory):
    ///   1. Try FTS5 query on `entities_fts` virtual table; rank by `bm25()`.
    ///   2. Fall back to SQL LIKE if the query string is empty or fails to
    ///      tokenise (FTS5 is strict about quotes and operators).
    ///   3. Apply scope filters (status / schema / project_id / patient_id)
    ///      as a JOIN to `entities`.
    pub fn search(
        &self,
        tenant_id: &str,
        query: &str,
        scope: &SearchScope,
        limit: i64,
    ) -> Result<Vec<Hit>> {
        let trimmed = query.trim();
        if trimmed.is_empty() {
            return Ok(vec![]);
        }
        // FTS5 chokes on raw `:`, `?`, etc. Try-then-fallback.
        match self.search_fts5(tenant_id, trimmed, scope, limit) {
            Ok(v) if !v.is_empty() => Ok(v),
            Ok(_empty) => self.search_like(tenant_id, trimmed, scope, limit),
            Err(_e) => self.search_like(tenant_id, trimmed, scope, limit),
        }
    }

    fn search_fts5(
        &self,
        tenant_id: &str,
        query: &str,
        scope: &SearchScope,
        limit: i64,
    ) -> Result<Vec<Hit>> {
        let conn = self.pool.get()?;
        let mut sql = String::from(
            "SELECT e.id, e.schema, e.status, e.title, e.description, e.body, e.created_at, \
                    bm25(entities_fts) AS rank \
             FROM entities e \
             JOIN entities_fts f ON f.id = e.id \
             WHERE entities_fts MATCH ?2 AND e.tenant_id = ?1",
        );
        let mut bind: Vec<Box<dyn rusqlite::ToSql>> =
            vec![Box::new(tenant_id.to_string()), Box::new(prepare_fts_query(query))];

        let status = scope.status.as_deref().unwrap_or("active");
        sql.push_str(" AND e.status = ?");
        sql.push_str(&(bind.len() + 1).to_string());
        bind.push(Box::new(status.to_string()));
        if let Some(s) = &scope.schema {
            sql.push_str(" AND e.schema = ?");
            sql.push_str(&(bind.len() + 1).to_string());
            bind.push(Box::new(s.clone()));
        }
        if let Some(p) = &scope.project_id {
            sql.push_str(" AND e.scope_project_ids LIKE ?");
            sql.push_str(&(bind.len() + 1).to_string());
            bind.push(Box::new(format!("%\"{}\"%", p)));
        }
        if let Some(p) = &scope.patient_id {
            sql.push_str(" AND e.scope_patient_ids LIKE ?");
            sql.push_str(&(bind.len() + 1).to_string());
            bind.push(Box::new(format!("%\"{}\"%", p)));
        }
        // bm25() is more negative = better; flip for sorting.
        sql.push_str(" ORDER BY rank ASC LIMIT ?");
        sql.push_str(&(bind.len() + 1).to_string());
        bind.push(Box::new(limit));

        let mut stmt = conn.prepare(&sql)?;
        let bind_refs: Vec<&dyn rusqlite::ToSql> = bind.iter().map(|b| b.as_ref()).collect();
        let rows = stmt
            .query_map(&bind_refs[..], |r| {
                Ok((
                    r.get::<_, String>(0)?,
                    r.get::<_, String>(1)?,
                    r.get::<_, String>(2)?,
                    r.get::<_, Option<String>>(3)?,
                    r.get::<_, Option<String>>(4)?,
                    r.get::<_, Option<String>>(5)?,
                    r.get::<_, String>(6)?,
                    r.get::<_, f64>(7)?,
                ))
            })?
            .collect::<std::result::Result<Vec<_>, _>>()?;

        let mut hits = Vec::with_capacity(rows.len());
        for (id, schema, status, title, description, body, created_at, rank) in rows {
            let snippet = body.as_ref().map(|b| {
                let s = b.replace('\n', " ");
                if s.chars().count() > 200 {
                    s.chars().take(200).collect::<String>() + "…"
                } else {
                    s
                }
            });
            // Map BM25 ranking to a positive integer score (higher = better)
            // for caller convenience. -rank * 1000, clamped to i64 range.
            let score = (-rank * 1000.0).round() as i64;
            hits.push(Hit {
                id,
                schema,
                status,
                title,
                description,
                snippet,
                created_at,
                score,
            });
        }
        Ok(hits)
    }

    /// Legacy LIKE search — used as a fallback when FTS5 returns 0 hits or
    /// errors (FTS5 grammar is strict about punctuation; LIKE always works).
    fn search_like(
        &self,
        tenant_id: &str,
        query: &str,
        scope: &SearchScope,
        limit: i64,
    ) -> Result<Vec<Hit>> {
        let conn = self.pool.get()?;
        let q_like = format!("%{}%", query);
        let mut sql = String::from(
            "SELECT id, schema, status, title, description, body, created_at \
             FROM entities \
             WHERE tenant_id = ?1 \
               AND (title LIKE ?2 OR body LIKE ?2 OR description LIKE ?2)",
        );
        let mut bind: Vec<Box<dyn rusqlite::ToSql>> =
            vec![Box::new(tenant_id.to_string()), Box::new(q_like.clone())];

        let status = scope.status.as_deref().unwrap_or("active");
        sql.push_str(" AND status = ?");
        sql.push_str(&(bind.len() + 1).to_string());
        bind.push(Box::new(status.to_string()));

        if let Some(s) = &scope.schema {
            sql.push_str(" AND schema = ?");
            sql.push_str(&(bind.len() + 1).to_string());
            bind.push(Box::new(s.clone()));
        }
        if let Some(p) = &scope.project_id {
            sql.push_str(" AND scope_project_ids LIKE ?");
            sql.push_str(&(bind.len() + 1).to_string());
            bind.push(Box::new(format!("%\"{}\"%", p)));
        }
        if let Some(p) = &scope.patient_id {
            sql.push_str(" AND scope_patient_ids LIKE ?");
            sql.push_str(&(bind.len() + 1).to_string());
            bind.push(Box::new(format!("%\"{}\"%", p)));
        }
        sql.push_str(" ORDER BY created_at DESC LIMIT ?");
        sql.push_str(&(bind.len() + 1).to_string());
        bind.push(Box::new(limit));

        let mut stmt = conn.prepare(&sql)?;
        let bind_refs: Vec<&dyn rusqlite::ToSql> = bind.iter().map(|b| b.as_ref()).collect();
        let rows = stmt
            .query_map(&bind_refs[..], |r| {
                Ok((
                    r.get::<_, String>(0)?,
                    r.get::<_, String>(1)?,
                    r.get::<_, String>(2)?,
                    r.get::<_, Option<String>>(3)?,
                    r.get::<_, Option<String>>(4)?,
                    r.get::<_, Option<String>>(5)?,
                    r.get::<_, String>(6)?,
                ))
            })?
            .collect::<std::result::Result<Vec<_>, _>>()?;

        let needle = query.to_lowercase();
        let mut hits = Vec::with_capacity(rows.len());
        for (id, schema, status, title, description, body, created_at) in rows {
            let body_str = body.as_deref().unwrap_or("");
            let title_str = title.as_deref().unwrap_or("");
            let desc_str = description.as_deref().unwrap_or("");
            let score = (count_occurrences(&title_str.to_lowercase(), &needle) as i64) * 3
                + count_occurrences(&body_str.to_lowercase(), &needle) as i64
                + count_occurrences(&desc_str.to_lowercase(), &needle) as i64;
            let snippet = body.map(|b| {
                let s = b.replace('\n', " ");
                if s.chars().count() > 200 {
                    s.chars().take(200).collect::<String>() + "…"
                } else {
                    s
                }
            });
            hits.push(Hit {
                id,
                schema,
                status,
                title,
                description,
                snippet,
                created_at,
                score,
            });
        }
        hits.sort_by(|a, b| b.score.cmp(&a.score));
        Ok(hits)
    }
}

/// Quote each query term + insert FTS5 `OR` between them.  We pick OR over
/// the default AND because:
///   * the query strings come from the doctor's free-form input (chat box)
///     so multi-token AND would too often miss obvious hits;
///   * BM25 ranking is robust to noise — common-word hits get low scores
///     and fall below the caller's threshold;
///   * we use this same primitive for the `propose()` similarity check
///     (where catching partial-match dupes is the whole point).
///
/// Quoting protects from accidental punctuation (`:`, `*`, …) breaking the
/// FTS5 parse.
fn prepare_fts_query(s: &str) -> String {
    let toks: Vec<String> = s
        .split_whitespace()
        .filter_map(|tok| {
            let t: String = tok
                .chars()
                .filter(|c| c.is_alphanumeric() || *c == '-' || *c == '_')
                .collect();
            if t.is_empty() {
                None
            } else {
                Some(format!("\"{}\"", t))
            }
        })
        .collect();
    toks.join(" OR ")
}

fn count_occurrences(haystack: &str, needle: &str) -> usize {
    if needle.is_empty() {
        return 0;
    }
    let mut n = 0;
    let mut start = 0;
    while let Some(pos) = haystack[start..].find(needle) {
        n += 1;
        start += pos + needle.len();
    }
    n
}
