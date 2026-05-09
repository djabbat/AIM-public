//! aim-project-graph — project dependency graph (RT1).
//!
//! Port of `agents/project_graph.py`. Builds a directed graph of
//! inter-project dependencies from explicit `depends_on:` fields and
//! discovered references in milestone blockers, goals, and stakeholder
//! notes.
//!
//! Renders to Graphviz DOT, Mermaid, and adjacency dict; detects cycles.

use std::collections::{BTreeMap, BTreeSet};

use once_cell::sync::Lazy;
use regex::Regex;
use serde::{Deserialize, Serialize};

// ── data ────────────────────────────────────────────────────────────────────

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EdgeKind {
    Explicit,
    Blocker,
    Goal,
    Note,
}

impl EdgeKind {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Explicit => "explicit",
            Self::Blocker => "blocker",
            Self::Goal => "goal",
            Self::Note => "note",
        }
    }
    pub fn priority(&self) -> u8 {
        match self {
            Self::Explicit => 0,
            Self::Blocker => 1,
            Self::Goal => 2,
            Self::Note => 3,
        }
    }
    pub fn dot_style(&self) -> &'static str {
        match self {
            Self::Explicit => "solid",
            Self::Blocker => "bold",
            Self::Goal => "dashed",
            Self::Note => "dotted",
        }
    }
    pub fn mermaid_arrow(&self) -> &'static str {
        match self {
            Self::Explicit => "-->",
            Self::Blocker => "==>",
            Self::Goal => "-.->",
            Self::Note => "-..->",
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Edge {
    pub src: String,
    pub dst: String,
    pub kind: EdgeKind,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct Graph {
    pub projects: Vec<String>,
    pub edges: Vec<Edge>,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct Milestone {
    pub blockers: Vec<String>,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct Stakeholder {
    pub notes: String,
}

/// Raw project metadata used to build the graph. Keeps the build logic
/// independent of YAML / sqlite — production loaders construct one of
/// these per project.
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct ProjectMeta {
    pub name: String,
    pub depends_on: Vec<String>,
    pub goals: Vec<String>,
    pub milestones: Vec<Milestone>,
    pub stakeholders: Vec<Stakeholder>,
}

// ── reference detection ─────────────────────────────────────────────────────

static WORD_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"\b([A-Z][A-Za-z0-9_-]{1,30})\b").expect("word regex"));

pub fn detect_refs(text: &str, known: &BTreeSet<String>) -> Vec<String> {
    if text.is_empty() {
        return Vec::new();
    }
    let mut seen: Vec<String> = Vec::new();
    let mut seen_set: BTreeSet<String> = BTreeSet::new();
    for cap in WORD_RE.captures_iter(text) {
        if let Some(m) = cap.get(1) {
            let tok = m.as_str().to_string();
            if known.contains(&tok) && seen_set.insert(tok.clone()) {
                seen.push(tok);
            }
        }
    }
    seen
}

// ── build ───────────────────────────────────────────────────────────────────

pub fn build(projects: &[ProjectMeta]) -> Graph {
    let names: Vec<String> = projects.iter().map(|p| p.name.clone()).collect();
    let known: BTreeSet<String> = names.iter().cloned().collect();
    let mut raw: Vec<Edge> = Vec::new();

    for p in projects {
        for dep in &p.depends_on {
            if known.contains(dep) && dep != &p.name {
                raw.push(Edge {
                    src: p.name.clone(),
                    dst: dep.clone(),
                    kind: EdgeKind::Explicit,
                });
            }
        }
        for g in &p.goals {
            for r in detect_refs(g, &known) {
                if r != p.name {
                    raw.push(Edge {
                        src: p.name.clone(),
                        dst: r,
                        kind: EdgeKind::Goal,
                    });
                }
            }
        }
        for m in &p.milestones {
            for b in &m.blockers {
                for r in detect_refs(b, &known) {
                    if r != p.name {
                        raw.push(Edge {
                            src: p.name.clone(),
                            dst: r,
                            kind: EdgeKind::Blocker,
                        });
                    }
                }
            }
        }
        for s in &p.stakeholders {
            for r in detect_refs(&s.notes, &known) {
                if r != p.name {
                    raw.push(Edge {
                        src: p.name.clone(),
                        dst: r,
                        kind: EdgeKind::Note,
                    });
                }
            }
        }
    }

    // De-dup: highest-priority kind per (src, dst).
    let mut best: BTreeMap<(String, String), Edge> = BTreeMap::new();
    for e in raw {
        let key = (e.src.clone(), e.dst.clone());
        match best.get(&key) {
            Some(cur) if cur.kind.priority() <= e.kind.priority() => {}
            _ => {
                best.insert(key, e);
            }
        }
    }
    Graph {
        projects: names,
        edges: best.into_values().collect(),
    }
}

// ── renderers ──────────────────────────────────────────────────────────────

pub fn dot(graph: &Graph) -> String {
    let mut lines: Vec<String> = vec![
        "digraph aim_projects {".into(),
        "  rankdir=LR;".into(),
        "  node [shape=box, style=rounded];".into(),
    ];
    for p in &graph.projects {
        lines.push(format!("  \"{}\";", p));
    }
    for e in &graph.edges {
        lines.push(format!(
            "  \"{}\" -> \"{}\" [style={}, label=\"{}\"];",
            e.src,
            e.dst,
            e.kind.dot_style(),
            e.kind.as_str()
        ));
    }
    lines.push("}".into());
    lines.join("\n")
}

pub fn mermaid(graph: &Graph) -> String {
    let mut lines: Vec<String> = vec!["```mermaid".into(), "graph TD".into()];
    for p in &graph.projects {
        lines.push(format!("  {}", p));
    }
    for e in &graph.edges {
        lines.push(format!(
            "  {} {}|{}| {}",
            e.src,
            e.kind.mermaid_arrow(),
            e.kind.as_str(),
            e.dst
        ));
    }
    lines.push("```".into());
    lines.join("\n")
}

pub fn adjacency(graph: &Graph) -> BTreeMap<String, Vec<(String, EdgeKind)>> {
    let mut out: BTreeMap<String, Vec<(String, EdgeKind)>> = BTreeMap::new();
    for p in &graph.projects {
        out.insert(p.clone(), Vec::new());
    }
    for e in &graph.edges {
        out.entry(e.src.clone())
            .or_default()
            .push((e.dst.clone(), e.kind));
    }
    out
}

// ── cycle detection ────────────────────────────────────────────────────────

/// Find every simple cycle. Returns each cycle in a canonical form
/// (rotated to start at lex-min element) so equivalent rotations dedupe.
pub fn cycles(graph: &Graph) -> Vec<Vec<String>> {
    let mut adj: BTreeMap<String, Vec<String>> = BTreeMap::new();
    for p in &graph.projects {
        adj.insert(p.clone(), Vec::new());
    }
    for e in &graph.edges {
        adj.entry(e.src.clone()).or_default().push(e.dst.clone());
    }

    let mut found: Vec<Vec<String>> = Vec::new();
    let mut seen: BTreeSet<Vec<String>> = BTreeSet::new();

    fn visit(
        node: &str,
        path: &[String],
        stack: &BTreeSet<String>,
        adj: &BTreeMap<String, Vec<String>>,
        found: &mut Vec<Vec<String>>,
        seen: &mut BTreeSet<Vec<String>>,
    ) {
        if let Some(neighbours) = adj.get(node) {
            for nxt in neighbours {
                if stack.contains(nxt) {
                    let idx = path.iter().position(|n| n == nxt).unwrap_or(path.len());
                    let loop_slice = &path[idx..];
                    let canonical = canonicalise(loop_slice);
                    if seen.insert(canonical.clone()) {
                        found.push(canonical);
                    }
                    continue;
                }
                let mut new_path = path.to_vec();
                new_path.push(nxt.clone());
                let mut new_stack = stack.clone();
                new_stack.insert(nxt.clone());
                visit(nxt, &new_path, &new_stack, adj, found, seen);
            }
        }
    }

    for p in &graph.projects {
        let mut stack = BTreeSet::new();
        stack.insert(p.clone());
        visit(p, &[p.clone()], &stack, &adj, &mut found, &mut seen);
    }
    found
}

fn canonicalise(slice: &[String]) -> Vec<String> {
    let n = slice.len();
    if n == 0 {
        return Vec::new();
    }
    let mut best_rot = 0;
    let mut best: Vec<&String> = slice.iter().collect();
    for i in 1..n {
        let candidate: Vec<&String> = slice[i..].iter().chain(slice[..i].iter()).collect();
        if candidate < best {
            best_rot = i;
            best = candidate;
        }
    }
    let mut rot: Vec<String> = slice[best_rot..].to_vec();
    rot.extend_from_slice(&slice[..best_rot]);
    rot
}

#[cfg(test)]
mod tests {
    use super::*;

    fn meta(name: &str) -> ProjectMeta {
        ProjectMeta {
            name: name.into(),
            ..Default::default()
        }
    }

    fn known(names: &[&str]) -> BTreeSet<String> {
        names.iter().map(|s| s.to_string()).collect()
    }

    // ── EdgeKind ───────────────────────────────────────────────────────────

    #[test]
    fn edge_kind_priority_explicit_lowest() {
        assert!(EdgeKind::Explicit.priority() < EdgeKind::Blocker.priority());
        assert!(EdgeKind::Blocker.priority() < EdgeKind::Goal.priority());
        assert!(EdgeKind::Goal.priority() < EdgeKind::Note.priority());
    }

    #[test]
    fn edge_kind_dot_styles_distinct() {
        let v = ["solid", "bold", "dashed", "dotted"];
        for s in v {
            let _ = s;
        }
        assert_ne!(EdgeKind::Explicit.dot_style(), EdgeKind::Goal.dot_style());
    }

    // ── detect_refs ────────────────────────────────────────────────────────

    #[test]
    fn detect_refs_finds_known_capitalised_words() {
        let k = known(&["FCLC", "MCOA", "CDATA"]);
        assert_eq!(detect_refs("blocked on FCLC and CDATA", &k), vec!["FCLC", "CDATA"]);
    }

    #[test]
    fn detect_refs_dedupes() {
        let k = known(&["FCLC"]);
        let v = detect_refs("FCLC again FCLC and FCLC", &k);
        assert_eq!(v, vec!["FCLC"]);
    }

    #[test]
    fn detect_refs_ignores_unknown_words() {
        let k = known(&["AIM"]);
        let v = detect_refs("Hello World and AIM", &k);
        assert_eq!(v, vec!["AIM"]);
    }

    #[test]
    fn detect_refs_empty_text_returns_empty() {
        let k = known(&["X"]);
        assert!(detect_refs("", &k).is_empty());
    }

    // ── build ──────────────────────────────────────────────────────────────

    #[test]
    fn build_explicit_dependency() {
        let mut a = meta("A");
        a.depends_on = vec!["B".into()];
        let projects = vec![a, meta("B")];
        let g = build(&projects);
        assert_eq!(g.edges.len(), 1);
        assert_eq!(g.edges[0].kind, EdgeKind::Explicit);
        assert_eq!(g.edges[0].src, "A");
        assert_eq!(g.edges[0].dst, "B");
    }

    #[test]
    fn build_skips_self_reference() {
        let mut a = meta("A");
        a.depends_on = vec!["A".into()];
        let g = build(&[a]);
        assert!(g.edges.is_empty());
    }

    #[test]
    fn build_skips_unknown_dependency() {
        let mut a = meta("A");
        a.depends_on = vec!["GHOST".into()];
        let g = build(&[a]);
        assert!(g.edges.is_empty());
    }

    #[test]
    fn build_records_goal_blocker_note_edges() {
        // Project names must be 2+ chars to match the WORD_RE pattern
        // (mirrors Python `\b([A-Z][A-Za-z0-9_-]{1,30})\b`)
        let mut alpha = meta("Alpha");
        alpha.goals = vec!["unblock Beta if possible".into()];
        alpha.milestones = vec![Milestone {
            blockers: vec!["depends on Gamma".into()],
        }];
        alpha.stakeholders = vec![Stakeholder {
            notes: "see Delta for context".into(),
        }];
        let projects = vec![alpha, meta("Beta"), meta("Gamma"), meta("Delta")];
        let g = build(&projects);
        let kinds: BTreeSet<EdgeKind> = g.edges.iter().map(|e| e.kind).collect();
        assert!(kinds.contains(&EdgeKind::Goal));
        assert!(kinds.contains(&EdgeKind::Blocker));
        assert!(kinds.contains(&EdgeKind::Note));
    }

    #[test]
    fn build_dedup_keeps_highest_priority_kind() {
        // explicit B and goal/blocker mention of B → explicit wins
        let mut a = meta("A");
        a.depends_on = vec!["B".into()];
        a.goals = vec!["unblock B".into()];
        a.milestones = vec![Milestone {
            blockers: vec!["wait B".into()],
        }];
        let g = build(&[a, meta("B")]);
        let edges_a_b: Vec<&Edge> = g.edges.iter().filter(|e| e.src == "A" && e.dst == "B").collect();
        assert_eq!(edges_a_b.len(), 1);
        assert_eq!(edges_a_b[0].kind, EdgeKind::Explicit);
    }

    // ── renderers ──────────────────────────────────────────────────────────

    #[test]
    fn dot_renders_nodes_and_edges() {
        let mut a = meta("A");
        a.depends_on = vec!["B".into()];
        let g = build(&[a, meta("B")]);
        let s = dot(&g);
        assert!(s.starts_with("digraph aim_projects {"));
        assert!(s.contains("\"A\""));
        assert!(s.contains("\"B\""));
        assert!(s.contains("\"A\" -> \"B\""));
        assert!(s.contains("style=solid"));
        assert!(s.contains("label=\"explicit\""));
    }

    #[test]
    fn mermaid_renders_arrows_and_labels() {
        let mut a = meta("A");
        a.depends_on = vec!["B".into()];
        let g = build(&[a, meta("B")]);
        let s = mermaid(&g);
        assert!(s.contains("graph TD"));
        assert!(s.contains("A -->|explicit| B"));
    }

    #[test]
    fn adjacency_lists_outgoing_edges_per_project() {
        let mut a = meta("A");
        a.depends_on = vec!["B".into(), "C".into()];
        let g = build(&[a, meta("B"), meta("C")]);
        let adj = adjacency(&g);
        let edges_from_a = adj["A"].clone();
        assert_eq!(edges_from_a.len(), 2);
        let dst_set: BTreeSet<String> = edges_from_a.iter().map(|(d, _)| d.clone()).collect();
        assert!(dst_set.contains("B"));
        assert!(dst_set.contains("C"));
    }

    // ── cycles ─────────────────────────────────────────────────────────────

    #[test]
    fn cycles_finds_two_node_loop() {
        let mut a = meta("A");
        a.depends_on = vec!["B".into()];
        let mut b = meta("B");
        b.depends_on = vec!["A".into()];
        let g = build(&[a, b]);
        let c = cycles(&g);
        assert_eq!(c.len(), 1);
        // canonical form starts with lex-min element ("A")
        assert_eq!(c[0][0], "A");
        assert!(c[0].contains(&"A".to_string()));
        assert!(c[0].contains(&"B".to_string()));
    }

    #[test]
    fn cycles_finds_three_node_loop() {
        let mut a = meta("A");
        a.depends_on = vec!["B".into()];
        let mut b = meta("B");
        b.depends_on = vec!["C".into()];
        let mut c = meta("C");
        c.depends_on = vec!["A".into()];
        let g = build(&[a, b, c]);
        let cs = cycles(&g);
        // Three rotations of one cycle deduplicated to 1
        assert_eq!(cs.len(), 1);
        assert_eq!(cs[0].len(), 3);
        assert_eq!(cs[0][0], "A"); // lex-min rotation
    }

    #[test]
    fn cycles_returns_empty_for_dag() {
        let mut a = meta("A");
        a.depends_on = vec!["B".into()];
        let mut b = meta("B");
        b.depends_on = vec!["C".into()];
        let g = build(&[a, b, meta("C")]);
        assert!(cycles(&g).is_empty());
    }

    #[test]
    fn cycles_canonicalisation_dedupes_rotations() {
        // construct two different starting traversals of the same loop
        let v = canonicalise(&["B".into(), "C".into(), "A".into()]);
        assert_eq!(v, vec!["A", "B", "C"]);
    }
}
