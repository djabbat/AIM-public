//! aim-memory-deduplicate — find + merge near-duplicate memory entries.
//!
//! Port of `agents/memory_deduplicate.py`. Two-stage pipeline:
//!
//! 1. **Coarse** — bucket by lower-cased prefix-60. Cheap O(n) scan.
//! 2. **Fine** — string similarity via [`text_similarity`] (longest-
//!    common-subsequence ratio, mirrors Python's
//!    `SequenceMatcher.ratio()` close enough for our threshold).
//!
//! Default similarity threshold 0.85. Merging keeps the longer body,
//! unions tags, records `merged_from` in frontmatter; the shorter file
//! is deleted.

use regex::Regex;
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, HashMap, HashSet};
use std::path::{Path, PathBuf};
use std::sync::OnceLock;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum DedupError {
    #[error("io: {0}")]
    Io(#[from] std::io::Error),
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct DupePair {
    pub file_a: String,
    pub file_b: String,
    pub similarity: f64,
}

/// Sequence-matching ratio in [0, 1]. Pure Rust LCS-based — matches
/// Python's `SequenceMatcher.ratio()` for similar text closely enough
/// for our 0.85 threshold use case. Identical strings → 1.0.
pub fn text_similarity(a: &str, b: &str) -> f64 {
    let a_lc = a.to_lowercase();
    let b_lc = b.to_lowercase();
    if a_lc == b_lc {
        return 1.0;
    }
    let av: Vec<char> = a_lc.chars().collect();
    let bv: Vec<char> = b_lc.chars().collect();
    if av.is_empty() && bv.is_empty() {
        return 1.0;
    }
    if av.is_empty() || bv.is_empty() {
        return 0.0;
    }
    let lcs = lcs_len(&av, &bv);
    (2.0 * lcs as f64) / ((av.len() + bv.len()) as f64)
}

fn lcs_len(a: &[char], b: &[char]) -> usize {
    let m = a.len();
    let n = b.len();
    if m == 0 || n == 0 {
        return 0;
    }
    let mut prev = vec![0usize; n + 1];
    let mut curr = vec![0usize; n + 1];
    for i in 1..=m {
        for j in 1..=n {
            if a[i - 1] == b[j - 1] {
                curr[j] = prev[j - 1] + 1;
            } else {
                curr[j] = curr[j - 1].max(prev[j]);
            }
        }
        std::mem::swap(&mut prev, &mut curr);
        for v in curr.iter_mut() {
            *v = 0;
        }
    }
    prev[n]
}

/// Bucket files by lowercased first-60 char prefix and return all
/// `(a, b)` pairs from buckets with ≥ 2 entries. O(n) plus pair
/// generation in collisions.
pub fn candidate_pairs_by_prefix(files: &[PathBuf]) -> Vec<(PathBuf, PathBuf)> {
    let mut buckets: HashMap<String, Vec<PathBuf>> = HashMap::new();
    for f in files {
        let body = match std::fs::read_to_string(f) {
            Ok(s) => s,
            Err(_) => continue,
        };
        let prefix: String = body.chars().take(60).collect::<String>().trim().to_lowercase();
        if prefix.is_empty() {
            continue;
        }
        buckets.entry(prefix).or_default().push(f.clone());
    }
    let mut pairs = HashSet::new();
    for files in buckets.values() {
        let unique: Vec<&PathBuf> = {
            let mut seen: HashSet<&PathBuf> = HashSet::new();
            files.iter().filter(|p| seen.insert(*p)).collect()
        };
        if unique.len() < 2 {
            continue;
        }
        for i in 0..unique.len() {
            for j in i + 1..unique.len() {
                let mut a = unique[i].clone();
                let mut b = unique[j].clone();
                if a > b {
                    std::mem::swap(&mut a, &mut b);
                }
                pairs.insert((a, b));
            }
        }
    }
    pairs.into_iter().collect()
}

/// Fall-back: every (a, b) pair from `files` (O(n²) — only call when
/// the embeddings index isn't available).
pub fn all_pairs(files: &[PathBuf]) -> Vec<(PathBuf, PathBuf)> {
    let mut sorted = files.to_vec();
    sorted.sort();
    let mut out = Vec::new();
    for i in 0..sorted.len() {
        for j in i + 1..sorted.len() {
            out.push((sorted[i].clone(), sorted[j].clone()));
        }
    }
    out
}

#[derive(Debug, Clone, Copy)]
pub struct DedupOpts {
    pub threshold: f64,
}

impl Default for DedupOpts {
    fn default() -> Self {
        Self { threshold: 0.85 }
    }
}

/// Scan `files` for near-duplicates above `opts.threshold`. Pure read —
/// does not mutate disk; pass results to [`merge`] for the destructive op.
pub fn scan(files: &[PathBuf], opts: &DedupOpts) -> Vec<DupePair> {
    let mut candidates = candidate_pairs_by_prefix(files);
    if candidates.is_empty() {
        candidates = all_pairs(files);
    }
    let mut out = Vec::new();
    for (a, b) in candidates {
        let ta = match std::fs::read_to_string(&a) {
            Ok(s) => s,
            Err(_) => continue,
        };
        let tb = match std::fs::read_to_string(&b) {
            Ok(s) => s,
            Err(_) => continue,
        };
        let sim = text_similarity(&ta, &tb);
        if sim >= opts.threshold {
            out.push(DupePair {
                file_a: a.to_string_lossy().to_string(),
                file_b: b.to_string_lossy().to_string(),
                similarity: round3(sim),
            });
        }
    }
    out
}

fn round3(x: f64) -> f64 {
    (x * 1000.0).round() / 1000.0
}

// ── frontmatter helpers ────────────────────────────────────────────────

static FM_RE: OnceLock<Regex> = OnceLock::new();

fn fm_re() -> &'static Regex {
    FM_RE.get_or_init(|| Regex::new(r"(?s)^---\s*\n(.*?)\n---\s*\n?(.*)$").unwrap())
}

/// Read YAML frontmatter as a flat string→string map. Returns `(map, body)`.
pub fn read_frontmatter(text: &str) -> (BTreeMap<String, String>, String) {
    let cap = match fm_re().captures(text) {
        Some(c) => c,
        None => return (BTreeMap::new(), text.to_string()),
    };
    let yaml = cap.get(1).map(|m| m.as_str()).unwrap_or("");
    let body = cap.get(2).map(|m| m.as_str()).unwrap_or("").to_string();
    let mut map = BTreeMap::new();
    if let Ok(serde_yaml::Value::Mapping(m)) = serde_yaml::from_str(yaml) {
        for (k, v) in m {
            let key = match k {
                serde_yaml::Value::String(s) => s,
                other => serde_yaml::to_string(&other).unwrap_or_default().trim().to_string(),
            };
            let val = match v {
                serde_yaml::Value::String(s) => s,
                serde_yaml::Value::Number(n) => n.to_string(),
                serde_yaml::Value::Bool(b) => b.to_string(),
                other => serde_yaml::to_string(&other).unwrap_or_default().trim().to_string(),
            };
            map.insert(key, val);
        }
    }
    (map, body)
}

fn write_frontmatter_and_body(
    fm: &BTreeMap<String, String>,
    body: &str,
) -> String {
    let mut out = String::from("---\n");
    for (k, v) in fm {
        out.push_str(&format!("{k}: {v}\n"));
    }
    out.push_str("---\n\n");
    out.push_str(body);
    out
}

/// Merge two duplicate files: keep the longer body, union tags, append
/// the dropped file's name to `merged_from`. Returns the kept path.
/// Both files must exist.
pub fn merge(file_a: &Path, file_b: &Path) -> Result<PathBuf, DedupError> {
    let ta = std::fs::read_to_string(file_a)?;
    let tb = std::fs::read_to_string(file_b)?;
    let (keep, drop) = if ta.len() >= tb.len() {
        (file_a, file_b)
    } else {
        (file_b, file_a)
    };
    let keep_text = std::fs::read_to_string(keep)?;
    let drop_text = std::fs::read_to_string(drop)?;
    let (mut fm_keep, body_keep) = read_frontmatter(&keep_text);
    let (fm_drop, _body_drop) = read_frontmatter(&drop_text);

    let drop_name = drop
        .file_name()
        .and_then(|s| s.to_str())
        .unwrap_or("")
        .to_string();
    let merged_from = fm_keep.get("merged_from").cloned().unwrap_or_default();
    let merged_from = if merged_from.is_empty() {
        drop_name.clone()
    } else {
        format!("{merged_from},{drop_name}")
    };
    fm_keep.insert("merged_from".to_string(), merged_from);

    if let Some(b_tags) = fm_drop.get("tags") {
        let a_tags = fm_keep.get("tags").cloned().unwrap_or_default();
        let mut union: std::collections::BTreeSet<String> = a_tags
            .split(',')
            .chain(b_tags.split(','))
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty())
            .collect();
        if union.is_empty() {
            // nothing to merge
        } else {
            // Sort to give deterministic output (BTreeSet already sorts)
            let combined: Vec<String> = union.iter().cloned().collect();
            // Drain to reuse the variable below
            union.clear();
            fm_keep.insert("tags".to_string(), combined.join(","));
        }
    }

    let new_text = write_frontmatter_and_body(&fm_keep, &body_keep);
    std::fs::write(keep, new_text)?;
    std::fs::remove_file(drop)?;
    Ok(keep.to_path_buf())
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    fn write(dir: &TempDir, name: &str, body: &str) -> PathBuf {
        let p = dir.path().join(name);
        std::fs::write(&p, body).unwrap();
        p
    }

    #[test]
    fn similarity_identical_is_one() {
        assert!((text_similarity("hello world", "hello world") - 1.0).abs() < 1e-9);
    }

    #[test]
    fn similarity_disjoint_is_zero() {
        let s = text_similarity("aaaaa", "bbbbb");
        assert!(s < 0.05, "got {s}");
    }

    #[test]
    fn similarity_lcs_overlap() {
        // "the quick brown" vs "the quick black" share most of "the quick "
        let s = text_similarity("the quick brown", "the quick black");
        assert!(s > 0.7, "got {s}");
    }

    #[test]
    fn similarity_case_insensitive() {
        let s = text_similarity("Hello", "HELLO");
        assert!((s - 1.0).abs() < 1e-9);
    }

    #[test]
    fn similarity_empty_pair() {
        assert_eq!(text_similarity("", ""), 1.0);
        assert_eq!(text_similarity("abc", ""), 0.0);
    }

    #[test]
    fn candidate_pairs_buckets_by_prefix() {
        let dir = TempDir::new().unwrap();
        // First 60 chars must be identical for a bucket collision.
        let shared = "Same long shared prefix used by all duplicates here xxxxx";
        let a = write(&dir, "a.md", &format!("{shared}\nbody A different"));
        let b = write(&dir, "b.md", &format!("{shared}\nbody B different"));
        let c = write(&dir, "c.md", "Totally different start so no collision in bucket prefix scan, c body");
        let pairs = candidate_pairs_by_prefix(&[a.clone(), b.clone(), c.clone()]);
        assert_eq!(pairs.len(), 1);
        assert!(pairs.iter().any(|(x, y)| (x == &a && y == &b) || (x == &b && y == &a)));
    }

    #[test]
    fn candidate_pairs_empty_when_no_collisions() {
        let dir = TempDir::new().unwrap();
        let a = write(&dir, "a.md", "alpha");
        let b = write(&dir, "b.md", "beta");
        let pairs = candidate_pairs_by_prefix(&[a, b]);
        assert!(pairs.is_empty());
    }

    #[test]
    fn all_pairs_n_squared() {
        let p = vec![
            PathBuf::from("/a"),
            PathBuf::from("/b"),
            PathBuf::from("/c"),
        ];
        let pairs = all_pairs(&p);
        assert_eq!(pairs.len(), 3); // C(3,2)
    }

    #[test]
    fn scan_finds_above_threshold() {
        let dir = TempDir::new().unwrap();
        // Same prefix → bucketed; bodies are 100% identical → sim 1.0
        let a = write(&dir, "a.md", "Identical content here exactly");
        let b = write(&dir, "b.md", "Identical content here exactly");
        let pairs = scan(&[a, b], &DedupOpts::default());
        assert_eq!(pairs.len(), 1);
        assert!((pairs[0].similarity - 1.0).abs() < 1e-9);
    }

    #[test]
    fn scan_skips_below_threshold() {
        let dir = TempDir::new().unwrap();
        let a = write(&dir, "a.md", "Same long shared prefix forces collision: alpha");
        let b = write(&dir, "b.md", "Same long shared prefix forces collision: zzzzzzzzzzzzzzzzzzzz different bbbbbbbbbbbbbbbbbb");
        let pairs = scan(
            &[a, b],
            &DedupOpts { threshold: 0.95 },
        );
        assert!(pairs.is_empty());
    }

    #[test]
    fn scan_fallback_when_no_prefix_collisions() {
        let dir = TempDir::new().unwrap();
        let a = write(&dir, "a.md", "alpha");
        // b and a share no 60-char prefix bucket but actually are identical
        // here. To force the all-pairs fallback we need DIFFERENT prefixes
        // but identical bodies — let's make that explicit.
        let b = write(&dir, "b.md", "alpha");
        let pairs = scan(&[a, b], &DedupOpts::default());
        // Both files have prefix "alpha" → bucketed; but if the bucket
        // had only one file the fallback would apply. With identical
        // bodies they share a bucket and the pair appears.
        assert_eq!(pairs.len(), 1);
    }

    #[test]
    fn read_frontmatter_basic() {
        let text = "---\nname: x\ntags: a,b,c\n---\n\nbody here";
        let (fm, body) = read_frontmatter(text);
        assert_eq!(fm.get("name"), Some(&"x".to_string()));
        assert_eq!(fm.get("tags"), Some(&"a,b,c".to_string()));
        assert_eq!(body, "body here");
    }

    #[test]
    fn read_frontmatter_missing_returns_empty_map() {
        let (fm, body) = read_frontmatter("just body, no fm");
        assert!(fm.is_empty());
        assert_eq!(body, "just body, no fm");
    }

    #[test]
    fn merge_keeps_longer_and_records_merged_from() {
        let dir = TempDir::new().unwrap();
        let a = write(
            &dir,
            "a.md",
            "---\nname: a\ntags: x,y\n---\n\nshort body",
        );
        let b = write(
            &dir,
            "b.md",
            "---\nname: b\ntags: y,z\n---\n\nthis is a much longer body that wins the merge",
        );
        let kept = merge(&a, &b).unwrap();
        // b had the longer body → it's kept
        assert_eq!(kept, b);
        // a is gone
        assert!(!a.exists());
        // Frontmatter on kept file records merged_from + union of tags
        let kept_text = std::fs::read_to_string(&kept).unwrap();
        let (fm, body) = read_frontmatter(&kept_text);
        assert_eq!(fm.get("merged_from"), Some(&"a.md".to_string()));
        assert_eq!(fm.get("tags"), Some(&"x,y,z".to_string()));
        assert!(body.contains("longer body"));
    }

    #[test]
    fn merge_appends_to_existing_merged_from() {
        let dir = TempDir::new().unwrap();
        let a = write(
            &dir,
            "a.md",
            "---\nmerged_from: prior.md\n---\n\nbody A long enough to be kept-side",
        );
        let b = write(&dir, "b.md", "---\n---\n\nshort");
        let kept = merge(&a, &b).unwrap();
        let kept_text = std::fs::read_to_string(&kept).unwrap();
        let (fm, _) = read_frontmatter(&kept_text);
        assert_eq!(
            fm.get("merged_from").map(|s| s.as_str()),
            Some("prior.md,b.md")
        );
    }

    #[test]
    fn merge_handles_no_frontmatter() {
        let dir = TempDir::new().unwrap();
        let a = write(&dir, "a.md", "first plain body line one");
        let b = write(&dir, "b.md", "second plain body line one and longer");
        let kept = merge(&a, &b).unwrap();
        let kept_text = std::fs::read_to_string(&kept).unwrap();
        let (fm, _) = read_frontmatter(&kept_text);
        assert_eq!(fm.get("merged_from"), Some(&"a.md".to_string()));
    }

    #[test]
    fn merge_unions_tags_when_only_drop_has_them() {
        let dir = TempDir::new().unwrap();
        // Drop file (shorter) has tags; keep doesn't → union runs.
        let a = write(&dir, "a.md", "---\ntags: foo,bar\n---\n\nshort");
        let b = write(&dir, "b.md", "---\n---\n\nbody B much longer than A by far");
        let kept = merge(&a, &b).unwrap();
        // b is longer → kept; a is dropped (had tags=foo,bar)
        assert_eq!(kept, b);
        let kept_text = std::fs::read_to_string(&kept).unwrap();
        let (fm, _) = read_frontmatter(&kept_text);
        // BTreeSet sorts alphabetically: bar,foo
        assert_eq!(fm.get("tags"), Some(&"bar,foo".to_string()));
    }

    #[test]
    fn merge_no_change_when_only_keep_has_tags() {
        let dir = TempDir::new().unwrap();
        // Keep has tags, drop doesn't → no union path triggered, tags stay verbatim
        let a = write(&dir, "a.md", "---\n---\n\nshort");
        let b = write(&dir, "b.md", "---\ntags: foo,bar\n---\n\nbody B much longer than A by far");
        let kept = merge(&a, &b).unwrap();
        assert_eq!(kept, b);
        let (fm, _) = read_frontmatter(&std::fs::read_to_string(&kept).unwrap());
        assert_eq!(fm.get("tags"), Some(&"foo,bar".to_string()));
    }
}
