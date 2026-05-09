use serde_json::Value;

/// Best-effort JSON extraction. Tries full string first, then largest balanced `{..}`.
pub fn extract_json(s: &str) -> Option<Value> {
    if let Ok(v) = serde_json::from_str::<Value>(s) { return Some(v); }
    let bytes = s.as_bytes();
    let mut depth = 0i32;
    let mut start = None;
    let mut best: Option<(usize, usize)> = None;
    for (i, &b) in bytes.iter().enumerate() {
        match b {
            b'{' => { if depth == 0 { start = Some(i); } depth += 1; }
            b'}' => {
                depth -= 1;
                if depth == 0 {
                    if let Some(st) = start {
                        let cand = (st, i + 1);
                        if best.is_none_or(|(s2, e2)| (i + 1 - st) > (e2 - s2)) { best = Some(cand); }
                    }
                }
            }
            _ => {}
        }
    }
    let (st, en) = best?;
    serde_json::from_str(&s[st..en]).ok()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn extract_json_finds_inline_object() {
        let s = "blah blah {\"diagnosis\":\"flu\",\"confidence\":0.8} trailing";
        let v = extract_json(s).expect("must parse");
        assert_eq!(v["diagnosis"], "flu");
    }

    #[test]
    fn extract_json_returns_none_on_no_object() {
        assert!(extract_json("nothing here").is_none());
    }

    #[test]
    fn extract_json_picks_longest_balanced() {
        let s = "{\"a\":1} then {\"b\":{\"nested\":42}, \"c\":[1,2,3]}";
        let v = extract_json(s).expect("must parse");
        // Longer span wins.
        assert!(v.get("b").is_some());
    }
}
