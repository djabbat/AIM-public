//! SQLite-backed vector store with in-memory cosine search.
//!
//! Optimisations applied:
//!   - In-memory cache of (id, text, metadata, vector). Loaded once at start
//!     and refreshed on every upsert. Cosine search runs over the cache and
//!     does not touch SQLite — search latency is constant w.r.t. disk I/O.
//!   - Vectors stored as little-endian f32 blobs.
//!
//! For >100k entries swap for sqlite-vec or hnsw_rs.

use parking_lot::RwLock;
use rusqlite::{params, Connection};
use serde_json::Value;

pub type Hit = (String, f32, String, Option<Value>);

#[derive(Clone)]
struct Entry {
    id: String,
    text: String,
    md: Option<String>,
    vec: Vec<f32>,
}

pub struct Store {
    conn: parking_lot::Mutex<Connection>,
    cache: RwLock<Vec<Entry>>,
}

impl Store {
    pub fn open(path: &str) -> anyhow::Result<Self> {
        let conn = Connection::open(path)?;
        conn.execute_batch(
            "CREATE TABLE IF NOT EXISTS docs (
                id        TEXT PRIMARY KEY,
                text      TEXT NOT NULL,
                metadata  TEXT,
                vector    BLOB NOT NULL,
                dim       INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
             );",
        )?;
        let cache = Self::load_cache(&conn)?;
        tracing::info!(entries = cache.len(), "rag store loaded");
        Ok(Self {
            conn: parking_lot::Mutex::new(conn),
            cache: RwLock::new(cache),
        })
    }

    fn load_cache(conn: &Connection) -> anyhow::Result<Vec<Entry>> {
        let mut stmt = conn.prepare("SELECT id, text, metadata, vector FROM docs")?;
        let rows = stmt.query_map([], |r| {
            let id: String = r.get(0)?;
            let text: String = r.get(1)?;
            let md: Option<String> = r.get(2)?;
            let bytes: Vec<u8> = r.get(3)?;
            Ok(Entry { id, text, md, vec: bytes_to_vec(&bytes) })
        })?;
        rows.collect::<Result<Vec<_>, _>>().map_err(Into::into)
    }

    pub fn upsert(&self, id: &str, text: &str, vector: &[f32], metadata: Option<&Value>) -> anyhow::Result<()> {
        let bytes = vec_to_bytes(vector);
        let md = metadata.map(|m| m.to_string());
        let now = chrono::Utc::now().timestamp();

        {
            let conn = self.conn.lock();
            conn.execute(
                "INSERT INTO docs (id, text, metadata, vector, dim, updated_at)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6)
                 ON CONFLICT(id) DO UPDATE SET
                    text = excluded.text,
                    metadata = excluded.metadata,
                    vector = excluded.vector,
                    dim = excluded.dim,
                    updated_at = excluded.updated_at",
                params![id, text, md, bytes, vector.len() as i64, now],
            )?;
        }

        // Update cache: replace if id present, else push.
        let entry = Entry { id: id.into(), text: text.into(), md, vec: vector.to_vec() };
        let mut cache = self.cache.write();
        if let Some(pos) = cache.iter().position(|e| e.id == id) {
            cache[pos] = entry;
        } else {
            cache.push(entry);
        }
        Ok(())
    }

    pub fn search(&self, query: &[f32], k: usize) -> anyhow::Result<Vec<Hit>> {
        let cache = self.cache.read();
        let qn = norm(query);
        let mut scored: Vec<Hit> = Vec::with_capacity(cache.len());
        for e in cache.iter() {
            if e.vec.len() != query.len() { continue; }
            let s = cosine(query, &e.vec, qn);
            let md = e.md.as_ref().and_then(|s| serde_json::from_str(s).ok());
            scored.push((e.id.clone(), s, e.text.clone(), md));
        }
        scored.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
        scored.truncate(k);
        Ok(scored)
    }
}

fn vec_to_bytes(v: &[f32]) -> Vec<u8> {
    let mut out = Vec::with_capacity(v.len() * 4);
    for x in v {
        out.extend_from_slice(&x.to_le_bytes());
    }
    out
}

fn bytes_to_vec(b: &[u8]) -> Vec<f32> {
    b.chunks_exact(4)
        .map(|c| f32::from_le_bytes([c[0], c[1], c[2], c[3]]))
        .collect()
}

fn norm(v: &[f32]) -> f32 {
    v.iter().map(|x| x * x).sum::<f32>().sqrt().max(1e-9)
}

fn cosine(a: &[f32], b: &[f32], a_norm: f32) -> f32 {
    let bn = norm(b);
    let dot: f32 = a.iter().zip(b).map(|(x, y)| x * y).sum();
    dot / (a_norm * bn)
}
