use crate::types::*;
use std::collections::HashMap;

pub fn load_algorithms(path: &str) -> anyhow::Result<Vec<Algorithm>> {
    let raw = std::fs::read_to_string(path)?;
    let algos: Vec<Algorithm> = serde_json::from_str(&raw)?;
    Ok(algos)
}

fn case_corpus(case: &Case) -> String {
    let mut s = case.free_text.to_lowercase();
    for (k, v) in &case.structured {
        s.push(' ');
        s.push_str(&k.to_lowercase());
        s.push(':');
        s.push_str(&v.to_string().to_lowercase());
    }
    s
}

fn keyword_hits(corpus: &str, keywords: &[String]) -> Vec<String> {
    keywords
        .iter()
        .filter(|kw| corpus.contains(&kw.to_lowercase()))
        .cloned()
        .collect()
}

fn algorithm_score(case_corpus: &str, algo: &Algorithm) -> usize {
    let mut score = keyword_hits(case_corpus, &algo.keywords).len();
    if case_corpus.contains(&algo.presenting_complaint.to_lowercase()) {
        score += 2;
    }
    score
}

fn score_differential(case_corpus: &str, def: &DifferentialDef) -> (f64, Vec<String>) {
    let hits = keyword_hits(case_corpus, &def.keywords);
    let base = def.probability_class.base_score();
    let bonus = (hits.len() as f64) * 0.05;
    let against_penalty = (def.evidence_against.len() as f64) * 0.02;
    let raw = (base + bonus - against_penalty).max(0.0);
    (raw, hits)
}

pub fn rank(case: &Case, algos: &[Algorithm], top_k: usize) -> DiffResponse {
    let corpus = case_corpus(case);

    let mut scored: Vec<(usize, &Algorithm)> = algos
        .iter()
        .map(|a| (algorithm_score(&corpus, a), a))
        .filter(|(s, _)| *s > 0)
        .collect();
    scored.sort_by(|a, b| b.0.cmp(&a.0));

    let matched: Vec<String> = scored.iter().map(|(_, a)| a.id.clone()).collect();
    let mut all_red_flags: Vec<String> = Vec::new();
    let mut acc: HashMap<String, Differential> = HashMap::new();

    for (_, algo) in &scored {
        for rf in &algo.red_flags {
            if !all_red_flags.contains(rf) {
                all_red_flags.push(rf.clone());
            }
        }
        for d in &algo.differentials {
            let (raw_score, hits) = score_differential(&corpus, d);
            let entry = acc.entry(d.name.clone()).or_insert_with(|| Differential {
                name: d.name.clone(),
                probability: 0.0,
                probability_class: d.probability_class,
                source_algorithm: algo.id.clone(),
                source_school: algo.system,
                evidence_for: Vec::new(),
                evidence_against: d.evidence_against.clone(),
                red_flag: matches!(d.probability_class, ProbabilityClass::RedFlag),
            });
            entry.probability = entry.probability.max(raw_score);
            for h in hits {
                if !entry.evidence_for.contains(&h) {
                    entry.evidence_for.push(h);
                }
            }
        }
    }

    let mut diffs: Vec<Differential> = acc.into_values().collect();

    let total: f64 = diffs.iter().map(|d| d.probability).sum();
    if total > 0.0 {
        for d in &mut diffs {
            d.probability /= total;
        }
    }

    diffs.sort_by(|a, b| {
        let af = if a.red_flag { 1 } else { 0 };
        let bf = if b.red_flag { 1 } else { 0 };
        bf.cmp(&af)
            .then(b.probability.partial_cmp(&a.probability).unwrap_or(std::cmp::Ordering::Equal))
    });
    diffs.truncate(top_k);

    DiffResponse {
        case_id: case.id,
        algorithms_matched: matched,
        differentials: diffs,
        red_flags: all_red_flags,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn sample_algo() -> Algorithm {
        let raw = json!({
            "id": "vinogradov.chest_pain",
            "source": "vinogradov_01_chest_pain.md",
            "system": "vinogradov",
            "presenting_complaint": "боль в груди",
            "keywords": ["боль","грудь","грудной"],
            "nodes": [],
            "differentials": [
                {
                    "name": "Острый инфаркт миокарда",
                    "probability_class": "red_flag",
                    "keywords": ["иррадиация","потливость","нитроглицерин"],
                    "evidence_for": [],
                    "evidence_against": []
                },
                {
                    "name": "ГЭРБ",
                    "probability_class": "common",
                    "keywords": ["изжога","после еды"],
                    "evidence_for": [],
                    "evidence_against": []
                },
                {
                    "name": "Расслоение аорты",
                    "probability_class": "rare",
                    "keywords": ["разрывающая","между лопаток"],
                    "evidence_for": [],
                    "evidence_against": []
                }
            ],
            "red_flags": ["нестабильная гемодинамика","сильная боль с потоотделением"]
        });
        serde_json::from_value(raw).unwrap()
    }

    fn case(text: &str) -> Case {
        Case {
            id: uuid::Uuid::new_v4(),
            free_text: text.to_string(),
            structured: Default::default(),
            created_at: chrono::Utc::now(),
        }
    }

    #[test]
    fn matches_chest_pain_algorithm() {
        let algos = vec![sample_algo()];
        let r = rank(&case("Жалобы на боль в груди, иррадиация в левую руку, потливость"), &algos, 5);
        assert_eq!(r.algorithms_matched, vec!["vinogradov.chest_pain".to_string()]);
        assert!(!r.differentials.is_empty());
    }

    #[test]
    fn red_flag_first() {
        let algos = vec![sample_algo()];
        let r = rank(&case("Боль в груди, потливость, иррадиация"), &algos, 5);
        assert!(r.differentials[0].red_flag, "red-flag диагноз должен идти первым");
    }

    #[test]
    fn no_match_no_diff() {
        let algos = vec![sample_algo()];
        let r = rank(&case("Сыпь на руках, зуд"), &algos, 5);
        assert!(r.algorithms_matched.is_empty());
        assert!(r.differentials.is_empty());
    }
}
