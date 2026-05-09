//! aim-graphrag — knowledge-graph layer over the semantic memory index.
//!
//! Port of `agents/graphrag.py`. Builds an undirected co-occurrence graph
//! of entities extracted from memory files; expands seeds N hops along
//! weighted edges to surface transitively-related files.
//!
//! Python relies on NetworkX; the Rust port uses a hand-rolled
//! `HashMap`-backed graph since the surface area is small (add edge,
//! weighted-neighbour lookup).

use std::collections::{BTreeMap, BTreeSet};

use once_cell::sync::Lazy;
use regex::Regex;
use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum GraphError {
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
}

// ── entity extraction ──────────────────────────────────────────────────────

static ENTITY_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(
        r"(?x)
        \b(
            [A-ZА-ЯҚӘҒҰҺ][a-zа-яёқәғұһ]{2,}
                (?:[-\s][A-ZА-ЯҚӘҒҰҺ][a-zа-яёқәғұһ]{2,}){0,3}
            |[A-ZА-Я]{3,}
        )\b
    ",
    )
    .expect("entity regex")
});

const STOPWORDS: &[&str] = &[
    "The", "This", "That", "Why", "How", "When",
    "Что", "Это", "Как", "Почему", "Если",
    "READ", "TODO", "DONE", "OPEN", "CLOSED", "TRUE", "FALSE",
];

/// Extract proper-noun + acronym entities from `text`. Mirrors Python
/// `_extract_entities`: dedupes case-insensitively, preserves first
/// occurrence's original casing, drops stopwords.
pub fn extract_entities(text: &str) -> Vec<String> {
    let mut out: Vec<String> = Vec::new();
    let mut seen: BTreeSet<String> = BTreeSet::new();
    for cap in ENTITY_RE.captures_iter(text) {
        if let Some(m) = cap.get(1) {
            let e = m.as_str().trim().to_string();
            let low = e.to_lowercase();
            if STOPWORDS.iter().any(|&s| s == e) || seen.contains(&low) {
                continue;
            }
            seen.insert(low);
            out.push(e);
        }
    }
    out
}

// ── graph ──────────────────────────────────────────────────────────────────

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct Node {
    pub files: BTreeSet<String>,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct Graph {
    pub nodes: BTreeMap<String, Node>,
    /// Directed adjacency `(src → (dst → weight))` mirrored on both sides
    /// for undirected lookups. We store both orderings so neighbour walks
    /// are cheap regardless of insertion order.
    pub adj: BTreeMap<String, BTreeMap<String, u32>>,
}

impl Graph {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn add_file(&mut self, file_name: &str, entities: &[String]) {
        if entities.len() < 2 {
            return;
        }
        for e in entities {
            self.nodes
                .entry(e.clone())
                .or_default()
                .files
                .insert(file_name.into());
        }
        for i in 0..entities.len() {
            for j in (i + 1)..entities.len() {
                self.add_edge(&entities[i], &entities[j]);
            }
        }
    }

    fn add_edge(&mut self, a: &str, b: &str) {
        if a == b {
            return;
        }
        *self
            .adj
            .entry(a.into())
            .or_default()
            .entry(b.into())
            .or_insert(0) += 1;
        *self
            .adj
            .entry(b.into())
            .or_default()
            .entry(a.into())
            .or_insert(0) += 1;
    }

    pub fn number_of_nodes(&self) -> usize {
        self.nodes.len()
    }

    /// Count distinct undirected edges (each pair counted once).
    pub fn number_of_edges(&self) -> usize {
        let mut seen: BTreeSet<(String, String)> = BTreeSet::new();
        for (a, neigh) in &self.adj {
            for b in neigh.keys() {
                let pair = if a < b {
                    (a.clone(), b.clone())
                } else {
                    (b.clone(), a.clone())
                };
                seen.insert(pair);
            }
        }
        seen.len()
    }

    /// Top-K weighted neighbours of `node` (descending by weight).
    /// Mirrors Python `sorted(g[node].items(), key=lambda kv: -kv[1].get("weight", 1))[:k]`.
    pub fn top_neighbours(&self, node: &str, k: usize) -> Vec<(String, u32)> {
        let mut entries: Vec<(String, u32)> = match self.adj.get(node) {
            Some(m) => m.iter().map(|(n, &w)| (n.clone(), w)).collect(),
            None => return Vec::new(),
        };
        entries.sort_by(|a, b| b.1.cmp(&a.1).then_with(|| a.0.cmp(&b.0)));
        entries.truncate(k);
        entries
    }

    /// Top-N nodes by degree (number of neighbours).
    pub fn top_by_degree(&self, n: usize) -> Vec<(String, usize)> {
        let mut v: Vec<(String, usize)> = self
            .adj
            .iter()
            .map(|(node, m)| (node.clone(), m.len()))
            .collect();
        v.sort_by(|a, b| b.1.cmp(&a.1).then_with(|| a.0.cmp(&b.0)));
        v.truncate(n);
        v
    }

    /// Files attached to `node` (or empty when missing).
    pub fn files_for(&self, node: &str) -> Vec<String> {
        self.nodes
            .get(node)
            .map(|n| n.files.iter().cloned().collect())
            .unwrap_or_default()
    }
}

// ── seed expansion ─────────────────────────────────────────────────────────

/// Expand `seeds` `hops` steps along weighted edges, taking up to `k`
/// best neighbours per node per hop. Returns the visited set.
pub fn expand_seeds(graph: &Graph, seeds: &[String], hops: usize, k: usize) -> BTreeSet<String> {
    let mut visited: BTreeSet<String> = seeds.iter().cloned().collect();
    let mut frontier: Vec<String> = seeds.iter().cloned().collect();
    for _ in 0..hops {
        let mut new_frontier: Vec<String> = Vec::new();
        for node in &frontier {
            for (nb, _w) in graph.top_neighbours(node, k) {
                if visited.insert(nb.clone()) {
                    new_frontier.push(nb);
                }
            }
        }
        if new_frontier.is_empty() {
            break;
        }
        frontier = new_frontier;
    }
    visited
}

/// Files reachable via graph expansion from `seeds`.
pub fn files_reachable(graph: &Graph, seeds: &[String], hops: usize, k: usize) -> BTreeSet<String> {
    let visited = expand_seeds(graph, seeds, hops, k);
    let mut files: BTreeSet<String> = BTreeSet::new();
    for node in &visited {
        if let Some(n) = graph.nodes.get(node) {
            files.extend(n.files.iter().cloned());
        }
    }
    files
}

// ── retrieval bias ─────────────────────────────────────────────────────────

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct Hit {
    pub file: String,
    pub text: String,
    pub distance: f64,
}

pub trait FlatRetriever: Send + Sync {
    fn retrieve(&self, query: &str, k: usize) -> Vec<Hit>;
}

/// Run the GraphRAG query: extract entities → seed nodes present in graph
/// → expand `hops` along weighted edges → collect file-set → retrieve
/// flat hits and prefer the ones whose `file` is in the graph-reachable
/// set. Returns `flat[..k]` when the graph has no overlap (mirrors
/// Python's "boosted or flat[:k]" fallback).
pub fn graph_query(
    graph: &Graph,
    query: &str,
    k: usize,
    hops: usize,
    flat: &dyn FlatRetriever,
) -> Vec<Hit> {
    let q_ents: Vec<String> = extract_entities(query)
        .into_iter()
        .filter(|e| graph.nodes.contains_key(e))
        .collect();
    if q_ents.is_empty() {
        return flat.retrieve(query, k);
    }
    let files = files_reachable(graph, &q_ents, hops, k);
    let mut hits = flat.retrieve(query, k * 2);
    let boosted: Vec<Hit> = hits
        .iter()
        .filter(|h| files.contains(&h.file))
        .cloned()
        .take(k)
        .collect();
    if boosted.is_empty() {
        hits.truncate(k);
        hits
    } else {
        boosted
    }
}

// ── stats ──────────────────────────────────────────────────────────────────

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct GraphStats {
    pub nodes: usize,
    pub edges: usize,
    pub top: Vec<(String, usize)>,
}

pub fn stats(graph: &Graph, top_n: usize) -> GraphStats {
    GraphStats {
        nodes: graph.number_of_nodes(),
        edges: graph.number_of_edges(),
        top: graph.top_by_degree(top_n),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn s(v: &[&str]) -> Vec<String> {
        v.iter().map(|x| x.to_string()).collect()
    }

    // ── extract_entities ───────────────────────────────────────────────────

    #[test]
    fn extract_finds_capitalised_words_and_acronyms() {
        let v = extract_entities("Geiger and Janke met at FCLC");
        assert!(v.contains(&"Geiger".to_string()));
        assert!(v.contains(&"Janke".to_string()));
        assert!(v.contains(&"FCLC".to_string()));
    }

    #[test]
    fn extract_dedupes_case_insensitive() {
        let v = extract_entities("Geiger and geiger and GEIGER");
        let n = v
            .iter()
            .filter(|e| e.to_lowercase() == "geiger")
            .count();
        assert_eq!(n, 1);
    }

    #[test]
    fn extract_skips_stopwords() {
        let v = extract_entities("The TODO list is OPEN");
        assert!(!v.contains(&"The".into()));
        assert!(!v.contains(&"TODO".into()));
        assert!(!v.contains(&"OPEN".into()));
    }

    #[test]
    fn extract_handles_cyrillic() {
        let v = extract_entities("Иванов работал с Петровым");
        assert!(v.iter().any(|e| e.starts_with("Иванов")));
    }

    // ── Graph ──────────────────────────────────────────────────────────────

    #[test]
    fn add_file_creates_nodes_and_edges() {
        let mut g = Graph::new();
        g.add_file("a.md", &s(&["FCLC", "Geiger", "Janke"]));
        assert_eq!(g.number_of_nodes(), 3);
        // 3 entities → C(3,2) = 3 edges
        assert_eq!(g.number_of_edges(), 3);
        // file recorded on every node
        for ent in ["FCLC", "Geiger", "Janke"] {
            let files = g.files_for(ent);
            assert_eq!(files, vec!["a.md".to_string()]);
        }
    }

    #[test]
    fn add_file_skips_singleton() {
        let mut g = Graph::new();
        g.add_file("a.md", &s(&["Lonely"]));
        assert!(g.nodes.is_empty());
    }

    #[test]
    fn add_file_increments_edge_weight_on_repeat() {
        let mut g = Graph::new();
        g.add_file("a.md", &s(&["A", "B"]));
        g.add_file("b.md", &s(&["A", "B"]));
        let neigh = g.top_neighbours("A", 5);
        let weight = neigh.iter().find(|(n, _)| n == "B").unwrap().1;
        assert_eq!(weight, 2);
    }

    #[test]
    fn top_neighbours_sorted_by_weight_desc() {
        let mut g = Graph::new();
        g.add_file("a.md", &s(&["A", "B"]));
        g.add_file("b.md", &s(&["A", "B"]));
        g.add_file("c.md", &s(&["A", "C"]));
        let neigh = g.top_neighbours("A", 5);
        assert_eq!(neigh[0].0, "B");
        assert_eq!(neigh[0].1, 2);
        assert_eq!(neigh[1].0, "C");
        assert_eq!(neigh[1].1, 1);
    }

    #[test]
    fn top_neighbours_caps_at_k() {
        let mut g = Graph::new();
        g.add_file("a.md", &s(&["A", "B", "C", "D", "E", "F"]));
        let neigh = g.top_neighbours("A", 3);
        assert_eq!(neigh.len(), 3);
    }

    #[test]
    fn top_neighbours_empty_for_unknown_node() {
        let g = Graph::new();
        assert!(g.top_neighbours("ghost", 5).is_empty());
    }

    #[test]
    fn top_by_degree_returns_highest_first() {
        let mut g = Graph::new();
        g.add_file("a.md", &s(&["A", "B", "C", "D"]));
        g.add_file("b.md", &s(&["A", "E"]));
        let top = g.top_by_degree(3);
        assert_eq!(top[0].0, "A");
        // A connected to {B,C,D,E} → degree 4
        assert_eq!(top[0].1, 4);
    }

    // ── expand_seeds / files_reachable ─────────────────────────────────────

    #[test]
    fn expand_seeds_zero_hops_returns_seeds() {
        let mut g = Graph::new();
        g.add_file("a.md", &s(&["A", "B"]));
        let v = expand_seeds(&g, &s(&["A"]), 0, 5);
        assert_eq!(v.len(), 1);
        assert!(v.contains("A"));
    }

    #[test]
    fn expand_seeds_one_hop_includes_neighbours() {
        let mut g = Graph::new();
        g.add_file("a.md", &s(&["A", "B"]));
        g.add_file("b.md", &s(&["B", "C"]));
        let v = expand_seeds(&g, &s(&["A"]), 1, 5);
        assert!(v.contains("A"));
        assert!(v.contains("B"));
        assert!(!v.contains("C")); // 2 hops away
    }

    #[test]
    fn expand_seeds_two_hops_traverses_chain() {
        let mut g = Graph::new();
        g.add_file("a.md", &s(&["A", "B"]));
        g.add_file("b.md", &s(&["B", "C"]));
        g.add_file("c.md", &s(&["C", "D"]));
        let v = expand_seeds(&g, &s(&["A"]), 2, 5);
        assert!(v.contains("A"));
        assert!(v.contains("B"));
        assert!(v.contains("C"));
        assert!(!v.contains("D"));
    }

    #[test]
    fn files_reachable_unions_visited_files() {
        let mut g = Graph::new();
        g.add_file("a.md", &s(&["A", "B"]));
        g.add_file("b.md", &s(&["B", "C"]));
        let f = files_reachable(&g, &s(&["A"]), 1, 5);
        assert!(f.contains("a.md"));
        assert!(f.contains("b.md"));
    }

    // ── graph_query ────────────────────────────────────────────────────────

    struct StubFlat(Vec<Hit>);
    impl FlatRetriever for StubFlat {
        fn retrieve(&self, _query: &str, k: usize) -> Vec<Hit> {
            self.0.iter().take(k).cloned().collect()
        }
    }

    #[test]
    fn graph_query_falls_back_to_flat_when_no_seeds() {
        let g = Graph::new();
        let flat = StubFlat(vec![Hit {
            file: "x.md".into(),
            text: "x".into(),
            distance: 0.5,
        }]);
        let r = graph_query(&g, "no entities here", 1, 1, &flat);
        assert_eq!(r.len(), 1);
    }

    #[test]
    fn graph_query_boosts_files_in_visited_set() {
        let mut g = Graph::new();
        g.add_file("a.md", &s(&["Geiger", "Janke"]));
        let flat = StubFlat(vec![
            Hit {
                file: "z.md".into(),
                text: "irrelevant".into(),
                distance: 0.1,
            },
            Hit {
                file: "a.md".into(),
                text: "in graph".into(),
                distance: 0.5,
            },
        ]);
        // Query mentions Geiger → seed in graph
        let r = graph_query(&g, "ask about Geiger", 1, 1, &flat);
        assert_eq!(r.len(), 1);
        assert_eq!(r[0].file, "a.md");
    }

    #[test]
    fn graph_query_falls_back_when_no_overlap() {
        let mut g = Graph::new();
        g.add_file("a.md", &s(&["Geiger", "Janke"]));
        let flat = StubFlat(vec![Hit {
            file: "elsewhere.md".into(),
            text: "no overlap".into(),
            distance: 0.5,
        }]);
        let r = graph_query(&g, "ask about Geiger", 1, 1, &flat);
        // No file overlap → returns top-k of flat
        assert_eq!(r.len(), 1);
        assert_eq!(r[0].file, "elsewhere.md");
    }

    // ── stats ──────────────────────────────────────────────────────────────

    #[test]
    fn stats_reports_node_edge_counts() {
        let mut g = Graph::new();
        g.add_file("a.md", &s(&["A", "B", "C"]));
        let s = stats(&g, 2);
        assert_eq!(s.nodes, 3);
        assert_eq!(s.edges, 3);
        assert_eq!(s.top.len(), 2);
    }
}
