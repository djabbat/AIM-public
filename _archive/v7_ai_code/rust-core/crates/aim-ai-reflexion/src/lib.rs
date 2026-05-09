//! aim-ai-reflexion — S10.
//!
//! Greedy single-link clustering of reflexion notes by Jaccard token
//! overlap. The motivation: produce ONE targeted prompt patch per
//! cluster instead of N one-off corrections.
//!
//! Rust port of `AI/ai/reflexion_cluster.py`. Tokenisation rules and
//! filler word list match the predecessor.

use serde::{Deserialize, Serialize};
use std::collections::{BTreeSet, HashMap};

/// Public note + clustered theme.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Cluster {
    pub notes: Vec<String>,
    pub theme: Vec<String>,
    pub representative: String,
}

impl Cluster {
    pub fn n(&self) -> usize {
        self.notes.len()
    }
    pub fn suggestion(&self) -> String {
        if self.theme.is_empty() {
            return self.representative.chars().take(200).collect();
        }
        let terms: Vec<&str> = self.theme.iter().take(5).map(|s| s.as_str()).collect();
        format!(
            "Remember when handling {}: {}",
            terms.join(", "),
            self.representative
                .trim()
                .chars()
                .take(200)
                .collect::<String>()
        )
    }
}

const FILLERS: &[&str] = &[
    // English
    "the", "and", "for", "with", "that", "this", "from", "they", "their",
    "your", "user", "model", "agent", "must", "should", "after", "into",
    "have", "been", "would", "could", "make", "more", "very", "when",
    "what", "which", "where", "while", "doesn", "don", "didn",
    // Russian
    "когда", "если", "чтобы", "также", "может", "нужно", "очень", "будут",
    "будет", "пока", "потом", "только", "ровно", "будем", "уже", "его",
    "ему", "она", "нам", "наш", "наша", "наше",
];

fn tokens(s: &str) -> BTreeSet<String> {
    use once_cell::sync::Lazy;
    use regex::Regex;
    static RE: Lazy<Regex> =
        Lazy::new(|| Regex::new(r"[A-Za-zА-Яа-яЁё][\w\-]{3,}").unwrap());
    let fillers: BTreeSet<&'static str> = FILLERS.iter().copied().collect();
    RE.find_iter(s)
        .map(|m| m.as_str().to_lowercase())
        .filter(|t| !fillers.contains(t.as_str()))
        .collect()
}

fn jaccard(a: &BTreeSet<String>, b: &BTreeSet<String>) -> f64 {
    if a.is_empty() || b.is_empty() {
        return 0.0;
    }
    let inter = a.intersection(b).count() as f64;
    let union = a.union(b).count() as f64;
    if union <= 0.0 {
        0.0
    } else {
        inter / union
    }
}

/// Greedy single-link clustering by Jaccard token overlap.
pub fn cluster<I, S>(notes: I, threshold: f64) -> Vec<Cluster>
where
    I: IntoIterator<Item = S>,
    S: AsRef<str>,
{
    let mut items: Vec<(String, BTreeSet<String>)> = Vec::new();
    for n in notes {
        let trimmed = n.as_ref().trim().to_string();
        if trimmed.len() < 20 {
            continue;
        }
        let toks = tokens(&trimmed);
        if toks.is_empty() {
            continue;
        }
        items.push((trimmed, toks));
    }

    let mut clusters: Vec<Vec<(String, BTreeSet<String>)>> = Vec::new();
    for (note, toks) in items {
        let mut attached = false;
        'outer: for cl in clusters.iter_mut() {
            for (_, ct) in cl.iter() {
                if jaccard(&toks, ct) >= threshold {
                    cl.push((note.clone(), toks.clone()));
                    attached = true;
                    break 'outer;
                }
            }
        }
        if !attached {
            clusters.push(vec![(note, toks)]);
        }
    }

    let mut out: Vec<Cluster> = clusters
        .into_iter()
        .map(|cl| {
            let mut counter: HashMap<String, u32> = HashMap::new();
            for (_, ts) in &cl {
                for t in ts {
                    *counter.entry(t.clone()).or_insert(0) += 1;
                }
            }
            let cutoff = (cl.len() / 2).max(1) as u32;
            let mut common: Vec<(String, u32)> = counter
                .into_iter()
                .filter(|(_, c)| *c >= cutoff)
                .collect();
            common.sort_by(|a, b| b.1.cmp(&a.1).then(a.0.cmp(&b.0)));
            let theme: Vec<String> = common.into_iter().take(6).map(|(t, _)| t).collect();
            let rep = cl
                .iter()
                .map(|(n, _)| n.clone())
                .max_by_key(|s| s.len())
                .unwrap_or_default();
            let notes: Vec<String> = cl.into_iter().map(|(n, _)| n).collect();
            Cluster {
                notes,
                theme,
                representative: rep,
            }
        })
        .collect();
    out.sort_by(|a, b| b.n().cmp(&a.n()));
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn empty_input_no_clusters() {
        let cs: Vec<Cluster> = cluster(Vec::<String>::new(), 0.25);
        assert!(cs.is_empty());
    }

    #[test]
    fn short_notes_skipped() {
        let cs = cluster(["hi", "ok", "noproblem"], 0.25);
        assert!(cs.is_empty());
    }

    #[test]
    fn similar_notes_cluster_together() {
        let cs = cluster(
            [
                "diagnostic prompt missed line numbers in agents reports today",
                "another report — diagnostic prompt skipped line numbers again",
                "completely unrelated banana smoothie recipe with mango and ice",
            ],
            0.20,
        );
        // First two share many tokens (diagnostic, prompt, line, numbers,
        // report). Third is alone.
        assert_eq!(cs.len(), 2);
        assert_eq!(cs[0].n(), 2);
        assert!(cs[0].theme.iter().any(|t| t.contains("diagnostic")));
    }

    #[test]
    fn cluster_suggestion_uses_theme() {
        let cs = cluster(
            [
                "diagnostic prompt missed line numbers in agents reports today",
                "another report — diagnostic prompt skipped line numbers again",
            ],
            0.20,
        );
        let s = cs[0].suggestion();
        assert!(s.starts_with("Remember when handling"));
    }

    #[test]
    fn empty_theme_returns_first_200_of_repr() {
        // Force empty theme by giving very different but long notes
        // that still cluster on a single shared filler-rejected term.
        let n1 = "alpha beta gamma delta epsilon zeta eta theta iota kappa".to_string();
        let n2 = "lambda mu nu xi omicron pi rho sigma tau upsilon phi".to_string();
        // Force them into a cluster manually
        let c = Cluster {
            notes: vec![n1.clone(), n2.clone()],
            theme: vec![],
            representative: n2.clone(),
        };
        let s = c.suggestion();
        assert!(s.len() <= 200);
        assert!(s.starts_with("lambda"));
    }

    #[test]
    fn token_filters_out_fillers() {
        let t = tokens("The user must always remember that THIS works");
        assert!(!t.iter().any(|x| x == "the"));
        assert!(!t.iter().any(|x| x == "user"));
        assert!(!t.iter().any(|x| x == "must"));
        // "always" / "remember" / "works" pass
        assert!(t.iter().any(|x| x == "always"));
    }

    #[test]
    fn jaccard_zero_for_empty_sets() {
        let a: BTreeSet<String> = BTreeSet::new();
        let b: BTreeSet<String> = BTreeSet::new();
        assert_eq!(jaccard(&a, &b), 0.0);
    }

    #[test]
    fn jaccard_full_overlap_one() {
        let mut a = BTreeSet::new();
        a.insert("x".to_string());
        a.insert("y".to_string());
        assert_eq!(jaccard(&a, &a), 1.0);
    }
}
