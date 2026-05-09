//! aim-embed-daemon — embedding service core (cache + dispatch).
//!
//! Port of `agents/embed_daemon.py`. The Python version owns the whole
//! Unix-socket lifecycle plus a sentence-transformers model; here we
//! split out the deterministic, testable pieces:
//!
//! * an [`Embedder`] trait (so tests can stub the model),
//! * an MD5-keyed LRU cache (so repeated texts skip re-encoding),
//! * a `handle_request` that dispatches `ping` / `stats` / `texts`
//!   payloads exactly like the Python `_handle_request`.
//!
//! Length-prefixed framing (`encode_frame` / `decode_frame`) is also
//! provided so a binary can implement the wire protocol without a
//! third-party dep.

use std::collections::{HashMap, VecDeque};

use parking_lot::Mutex;
use serde::{Deserialize, Serialize};
use thiserror::Error;

// ── embedder trait ────────────────────────────────────────────────────────

pub trait Embedder: Send + Sync {
    fn encode(&self, texts: &[String]) -> Result<Vec<Vec<f32>>, String>;
    fn dim(&self) -> usize;
}

/// Deterministic test/dev embedder: hashes each character into a fixed
/// dim. No model, no network — purely for unit tests and offline mode.
pub struct StubEmbedder {
    pub dim: usize,
}

impl StubEmbedder {
    pub fn new(dim: usize) -> Self {
        Self { dim }
    }
}

impl Embedder for StubEmbedder {
    fn encode(&self, texts: &[String]) -> Result<Vec<Vec<f32>>, String> {
        let mut out = Vec::with_capacity(texts.len());
        for t in texts {
            let mut v = vec![0.0_f32; self.dim];
            for (i, b) in t.bytes().enumerate() {
                v[i % self.dim] += (b as f32) / 256.0;
            }
            out.push(v);
        }
        Ok(out)
    }
    fn dim(&self) -> usize {
        self.dim
    }
}

// ── MD5 (small, self-contained) ───────────────────────────────────────────
//
// Python uses md5 for cache keys. Pulling in a crate just for that is
// overkill; here is a minimal, RFC-1321-compliant implementation. Keys
// are 32-char lowercase hex.

pub fn md5_hex(input: &[u8]) -> String {
    let digest = md5_compute(input);
    let mut s = String::with_capacity(32);
    for b in digest.iter() {
        s.push_str(&format!("{:02x}", b));
    }
    s
}

fn md5_compute(input: &[u8]) -> [u8; 16] {
    const S: [u32; 64] = [
        7, 12, 17, 22, 7, 12, 17, 22, 7, 12, 17, 22, 7, 12, 17, 22, 5, 9, 14, 20, 5, 9, 14, 20, 5,
        9, 14, 20, 5, 9, 14, 20, 4, 11, 16, 23, 4, 11, 16, 23, 4, 11, 16, 23, 4, 11, 16, 23, 6, 10,
        15, 21, 6, 10, 15, 21, 6, 10, 15, 21, 6, 10, 15, 21,
    ];
    const K: [u32; 64] = [
        0xd76aa478, 0xe8c7b756, 0x242070db, 0xc1bdceee, 0xf57c0faf, 0x4787c62a, 0xa8304613,
        0xfd469501, 0x698098d8, 0x8b44f7af, 0xffff5bb1, 0x895cd7be, 0x6b901122, 0xfd987193,
        0xa679438e, 0x49b40821, 0xf61e2562, 0xc040b340, 0x265e5a51, 0xe9b6c7aa, 0xd62f105d,
        0x02441453, 0xd8a1e681, 0xe7d3fbc8, 0x21e1cde6, 0xc33707d6, 0xf4d50d87, 0x455a14ed,
        0xa9e3e905, 0xfcefa3f8, 0x676f02d9, 0x8d2a4c8a, 0xfffa3942, 0x8771f681, 0x6d9d6122,
        0xfde5380c, 0xa4beea44, 0x4bdecfa9, 0xf6bb4b60, 0xbebfbc70, 0x289b7ec6, 0xeaa127fa,
        0xd4ef3085, 0x04881d05, 0xd9d4d039, 0xe6db99e5, 0x1fa27cf8, 0xc4ac5665, 0xf4292244,
        0x432aff97, 0xab9423a7, 0xfc93a039, 0x655b59c3, 0x8f0ccc92, 0xffeff47d, 0x85845dd1,
        0x6fa87e4f, 0xfe2ce6e0, 0xa3014314, 0x4e0811a1, 0xf7537e82, 0xbd3af235, 0x2ad7d2bb,
        0xeb86d391,
    ];

    let mut a0: u32 = 0x67452301;
    let mut b0: u32 = 0xefcdab89;
    let mut c0: u32 = 0x98badcfe;
    let mut d0: u32 = 0x10325476;

    let mut padded = input.to_vec();
    let bit_len = (input.len() as u64).wrapping_mul(8);
    padded.push(0x80);
    while padded.len() % 64 != 56 {
        padded.push(0);
    }
    padded.extend_from_slice(&bit_len.to_le_bytes());

    for chunk in padded.chunks(64) {
        let mut m = [0u32; 16];
        for (i, w) in chunk.chunks(4).enumerate() {
            m[i] = u32::from_le_bytes([w[0], w[1], w[2], w[3]]);
        }
        let (mut a, mut b, mut c, mut d) = (a0, b0, c0, d0);
        for i in 0..64 {
            let (f, g) = match i {
                0..=15 => ((b & c) | (!b & d), i),
                16..=31 => ((d & b) | (!d & c), (5 * i + 1) % 16),
                32..=47 => (b ^ c ^ d, (3 * i + 5) % 16),
                _ => (c ^ (b | !d), (7 * i) % 16),
            };
            let temp = d;
            d = c;
            c = b;
            b = b.wrapping_add(
                a.wrapping_add(f)
                    .wrapping_add(K[i])
                    .wrapping_add(m[g])
                    .rotate_left(S[i]),
            );
            a = temp;
        }
        a0 = a0.wrapping_add(a);
        b0 = b0.wrapping_add(b);
        c0 = c0.wrapping_add(c);
        d0 = d0.wrapping_add(d);
    }

    let mut out = [0u8; 16];
    out[0..4].copy_from_slice(&a0.to_le_bytes());
    out[4..8].copy_from_slice(&b0.to_le_bytes());
    out[8..12].copy_from_slice(&c0.to_le_bytes());
    out[12..16].copy_from_slice(&d0.to_le_bytes());
    out
}

// ── cache ─────────────────────────────────────────────────────────────────

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct CacheConfig {
    pub max_size: usize,
}

impl Default for CacheConfig {
    fn default() -> Self {
        Self { max_size: 512 }
    }
}

struct CacheInner {
    /// Front = LRU, back = MRU.
    order: VecDeque<String>,
    map: HashMap<String, Vec<f32>>,
    hits: u64,
    misses: u64,
}

pub struct EmbedCache {
    cfg: CacheConfig,
    inner: Mutex<CacheInner>,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct CacheStats {
    pub size: usize,
    pub hits: u64,
    pub misses: u64,
    pub ratio: f32,
}

impl EmbedCache {
    pub fn new(cfg: CacheConfig) -> Self {
        Self {
            cfg,
            inner: Mutex::new(CacheInner {
                order: VecDeque::new(),
                map: HashMap::new(),
                hits: 0,
                misses: 0,
            }),
        }
    }

    pub fn key(text: &str) -> String {
        md5_hex(text.as_bytes())
    }

    pub fn get(&self, text: &str) -> Option<Vec<f32>> {
        let key = Self::key(text);
        let mut g = self.inner.lock();
        if g.map.contains_key(&key) {
            g.hits += 1;
            // bump to MRU
            if let Some(pos) = g.order.iter().position(|k| k == &key) {
                let k = g.order.remove(pos).expect("pos valid");
                g.order.push_back(k);
            }
            g.map.get(&key).cloned()
        } else {
            g.misses += 1;
            None
        }
    }

    pub fn put(&self, text: &str, vec: Vec<f32>) {
        let key = Self::key(text);
        let mut g = self.inner.lock();
        if let Some(pos) = g.order.iter().position(|k| k == &key) {
            g.order.remove(pos);
        }
        g.order.push_back(key.clone());
        g.map.insert(key, vec);
        let max = self.cfg.max_size.max(1);
        while g.order.len() > max {
            if let Some(oldest) = g.order.pop_front() {
                g.map.remove(&oldest);
            }
        }
    }

    pub fn stats(&self) -> CacheStats {
        let g = self.inner.lock();
        let total = g.hits + g.misses;
        let ratio = if total > 0 {
            ((g.hits as f64 / total as f64) * 1000.0).round() as f32 / 10.0
        } else {
            0.0
        };
        CacheStats {
            size: g.order.len(),
            hits: g.hits,
            misses: g.misses,
            ratio,
        }
    }

    pub fn len(&self) -> usize {
        self.inner.lock().order.len()
    }
    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }
}

// ── request dispatch ──────────────────────────────────────────────────────

#[derive(Debug, Error)]
pub enum DispatchError {
    #[error("invalid JSON: {0}")]
    BadJson(String),
}

pub fn handle_request(
    raw: &[u8],
    embedder: &dyn Embedder,
    cache: &EmbedCache,
    model_name: &str,
) -> Vec<u8> {
    let payload: serde_json::Value = match serde_json::from_slice(raw) {
        Ok(v) => v,
        Err(e) => {
            return serde_json::to_vec(&serde_json::json!({
                "ok": false, "error": format!("invalid JSON: {}", e),
            }))
            .unwrap();
        }
    };

    if payload.get("ping").is_some() {
        let s = cache.stats();
        return serde_json::to_vec(&serde_json::json!({
            "ok": true, "pong": true, "model": model_name,
            "cache_size": s.size, "cache_hits": s.hits,
            "cache_misses": s.misses, "cache_ratio": s.ratio,
        }))
        .unwrap();
    }
    if payload.get("stats").is_some() {
        let s = cache.stats();
        return serde_json::to_vec(&serde_json::json!({
            "ok": true,
            "cache_size": s.size, "cache_hits": s.hits,
            "cache_misses": s.misses, "cache_ratio": s.ratio,
        }))
        .unwrap();
    }

    let texts = match payload.get("texts").and_then(|v| v.as_array()) {
        Some(arr) => arr
            .iter()
            .filter_map(|v| v.as_str().map(|s| s.to_string()))
            .collect::<Vec<_>>(),
        None => {
            return serde_json::to_vec(&serde_json::json!({
                "ok": false, "error": "missing 'texts' (list of strings)",
            }))
            .unwrap();
        }
    };
    if texts.is_empty() {
        return serde_json::to_vec(&serde_json::json!({"ok": true, "vectors": []})).unwrap();
    }

    let mut out: Vec<Option<Vec<f32>>> = vec![None; texts.len()];
    let mut miss_idx: Vec<usize> = Vec::new();
    let mut miss_text: Vec<String> = Vec::new();
    for (i, t) in texts.iter().enumerate() {
        if let Some(v) = cache.get(t) {
            out[i] = Some(v);
        } else {
            miss_idx.push(i);
            miss_text.push(t.clone());
        }
    }
    if !miss_text.is_empty() {
        match embedder.encode(&miss_text) {
            Ok(vecs) => {
                for ((i, t), v) in miss_idx.iter().zip(miss_text.iter()).zip(vecs.into_iter()) {
                    cache.put(t, v.clone());
                    out[*i] = Some(v);
                }
            }
            Err(e) => {
                return serde_json::to_vec(&serde_json::json!({
                    "ok": false, "error": format!("embed failed: {}", e),
                }))
                .unwrap();
            }
        }
    }
    let vectors: Vec<Vec<f32>> = out.into_iter().map(|v| v.unwrap_or_default()).collect();
    serde_json::to_vec(&serde_json::json!({"ok": true, "vectors": vectors})).unwrap()
}

// ── wire framing ──────────────────────────────────────────────────────────

pub fn encode_frame(body: &[u8]) -> Vec<u8> {
    let mut out = Vec::with_capacity(4 + body.len());
    out.extend_from_slice(&(body.len() as u32).to_be_bytes());
    out.extend_from_slice(body);
    out
}

pub fn decode_frame(buf: &[u8]) -> Option<&[u8]> {
    if buf.len() < 4 {
        return None;
    }
    let n = u32::from_be_bytes([buf[0], buf[1], buf[2], buf[3]]) as usize;
    if buf.len() < 4 + n {
        return None;
    }
    Some(&buf[4..4 + n])
}

#[cfg(test)]
mod tests {
    use super::*;

    // ── md5 ────────────────────────────────────────────────────────────────

    #[test]
    fn md5_known_vectors() {
        // RFC 1321 / Wikipedia test vectors
        assert_eq!(md5_hex(b""), "d41d8cd98f00b204e9800998ecf8427e");
        assert_eq!(md5_hex(b"a"), "0cc175b9c0f1b6a831c399e269772661");
        assert_eq!(md5_hex(b"abc"), "900150983cd24fb0d6963f7d28e17f72");
        assert_eq!(
            md5_hex(b"The quick brown fox jumps over the lazy dog"),
            "9e107d9d372bb6826bd81d3542a419d6"
        );
    }

    #[test]
    fn md5_long_input_block_boundary() {
        // 56-byte input forces an extra block of padding
        let s = "a".repeat(56);
        let h = md5_hex(s.as_bytes());
        assert_eq!(h.len(), 32);
    }

    // ── stub embedder ─────────────────────────────────────────────────────

    #[test]
    fn stub_embedder_dimensions() {
        let e = StubEmbedder::new(8);
        let v = e.encode(&["hello".into()]).unwrap();
        assert_eq!(v.len(), 1);
        assert_eq!(v[0].len(), 8);
        assert_eq!(e.dim(), 8);
    }

    // ── cache ─────────────────────────────────────────────────────────────

    #[test]
    fn cache_put_and_get_round_trip() {
        let c = EmbedCache::new(CacheConfig::default());
        c.put("hello", vec![1.0, 2.0, 3.0]);
        let v = c.get("hello").unwrap();
        assert_eq!(v, vec![1.0, 2.0, 3.0]);
        let s = c.stats();
        assert_eq!(s.hits, 1);
        assert_eq!(s.misses, 0);
        assert_eq!(s.size, 1);
    }

    #[test]
    fn cache_miss_increments_misses() {
        let c = EmbedCache::new(CacheConfig::default());
        assert!(c.get("nope").is_none());
        assert_eq!(c.stats().misses, 1);
    }

    #[test]
    fn cache_lru_evicts_oldest() {
        let c = EmbedCache::new(CacheConfig { max_size: 2 });
        c.put("a", vec![1.0]);
        c.put("b", vec![2.0]);
        c.put("c", vec![3.0]);
        assert_eq!(c.len(), 2);
        assert!(c.get("a").is_none());
        assert!(c.get("b").is_some());
        assert!(c.get("c").is_some());
    }

    #[test]
    fn cache_get_promotes_to_mru() {
        let c = EmbedCache::new(CacheConfig { max_size: 2 });
        c.put("a", vec![1.0]);
        c.put("b", vec![2.0]);
        c.get("a"); // promote a
        c.put("c", vec![3.0]); // evicts b
        assert!(c.get("a").is_some());
        assert!(c.get("b").is_none());
    }

    #[test]
    fn cache_put_replaces_existing() {
        let c = EmbedCache::new(CacheConfig::default());
        c.put("k", vec![1.0]);
        c.put("k", vec![9.0]);
        assert_eq!(c.len(), 1);
        assert_eq!(c.get("k").unwrap(), vec![9.0]);
    }

    // ── handle_request ────────────────────────────────────────────────────

    #[test]
    fn request_ping_includes_model() {
        let e = StubEmbedder::new(4);
        let c = EmbedCache::new(CacheConfig::default());
        let resp = handle_request(br#"{"ping":true}"#, &e, &c, "miniLM-stub");
        let v: serde_json::Value = serde_json::from_slice(&resp).unwrap();
        assert_eq!(v["ok"], serde_json::Value::Bool(true));
        assert_eq!(v["pong"], serde_json::Value::Bool(true));
        assert_eq!(v["model"], "miniLM-stub");
    }

    #[test]
    fn request_stats_returns_cache_metrics() {
        let e = StubEmbedder::new(4);
        let c = EmbedCache::new(CacheConfig::default());
        c.put("x", vec![0.0; 4]);
        c.get("x");
        let resp = handle_request(br#"{"stats":true}"#, &e, &c, "m");
        let v: serde_json::Value = serde_json::from_slice(&resp).unwrap();
        assert_eq!(v["cache_size"], 1);
        assert_eq!(v["cache_hits"], 1);
    }

    #[test]
    fn request_invalid_json() {
        let e = StubEmbedder::new(4);
        let c = EmbedCache::new(CacheConfig::default());
        let resp = handle_request(b"not json", &e, &c, "m");
        let v: serde_json::Value = serde_json::from_slice(&resp).unwrap();
        assert_eq!(v["ok"], serde_json::Value::Bool(false));
        assert!(v["error"].as_str().unwrap().contains("invalid JSON"));
    }

    #[test]
    fn request_missing_texts_field() {
        let e = StubEmbedder::new(4);
        let c = EmbedCache::new(CacheConfig::default());
        let resp = handle_request(br#"{"foo":1}"#, &e, &c, "m");
        let v: serde_json::Value = serde_json::from_slice(&resp).unwrap();
        assert_eq!(v["ok"], serde_json::Value::Bool(false));
    }

    #[test]
    fn request_empty_texts_returns_empty_vectors() {
        let e = StubEmbedder::new(4);
        let c = EmbedCache::new(CacheConfig::default());
        let resp = handle_request(br#"{"texts":[]}"#, &e, &c, "m");
        let v: serde_json::Value = serde_json::from_slice(&resp).unwrap();
        assert_eq!(v["ok"], serde_json::Value::Bool(true));
        assert_eq!(v["vectors"].as_array().unwrap().len(), 0);
    }

    #[test]
    fn request_encodes_misses_and_hits_cache() {
        let e = StubEmbedder::new(4);
        let c = EmbedCache::new(CacheConfig::default());
        let resp1 = handle_request(br#"{"texts":["alpha","beta"]}"#, &e, &c, "m");
        let v1: serde_json::Value = serde_json::from_slice(&resp1).unwrap();
        assert_eq!(v1["vectors"].as_array().unwrap().len(), 2);
        let s1 = c.stats();
        assert_eq!(s1.size, 2);
        // Second call: both should hit the cache; result identical.
        let resp2 = handle_request(br#"{"texts":["alpha","beta"]}"#, &e, &c, "m");
        let v2: serde_json::Value = serde_json::from_slice(&resp2).unwrap();
        assert_eq!(v1["vectors"], v2["vectors"]);
        let s2 = c.stats();
        assert_eq!(s2.hits, 2);
    }

    #[test]
    fn request_partial_cache_hit() {
        let e = StubEmbedder::new(4);
        let c = EmbedCache::new(CacheConfig::default());
        let _ = handle_request(br#"{"texts":["alpha"]}"#, &e, &c, "m");
        let resp = handle_request(br#"{"texts":["alpha","beta"]}"#, &e, &c, "m");
        let v: serde_json::Value = serde_json::from_slice(&resp).unwrap();
        assert_eq!(v["vectors"].as_array().unwrap().len(), 2);
        let s = c.stats();
        // alpha hit twice, beta missed once; first call also missed once.
        assert_eq!(s.hits, 1);
    }

    #[test]
    fn request_embedder_failure_propagates() {
        struct BoomEmbedder;
        impl Embedder for BoomEmbedder {
            fn encode(&self, _: &[String]) -> Result<Vec<Vec<f32>>, String> {
                Err("model offline".into())
            }
            fn dim(&self) -> usize {
                4
            }
        }
        let c = EmbedCache::new(CacheConfig::default());
        let resp = handle_request(br#"{"texts":["x"]}"#, &BoomEmbedder, &c, "m");
        let v: serde_json::Value = serde_json::from_slice(&resp).unwrap();
        assert_eq!(v["ok"], serde_json::Value::Bool(false));
        assert!(v["error"].as_str().unwrap().contains("model offline"));
    }

    // ── framing ───────────────────────────────────────────────────────────

    #[test]
    fn frame_round_trip() {
        let body = br#"{"hello":1}"#;
        let wire = encode_frame(body);
        assert_eq!(wire.len(), body.len() + 4);
        let decoded = decode_frame(&wire).unwrap();
        assert_eq!(decoded, body);
    }

    #[test]
    fn frame_short_buffer_returns_none() {
        assert!(decode_frame(&[0, 0, 0]).is_none());
        assert!(decode_frame(&[0, 0, 0, 5, 1, 2]).is_none()); // length 5 but only 2 bytes follow
    }
}
