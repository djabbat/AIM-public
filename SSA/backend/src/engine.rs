use crate::types::*;
use std::collections::HashMap;

pub fn load_ranges(path: &str) -> anyhow::Result<RangesFile> {
    let raw = std::fs::read_to_string(path)?;
    Ok(serde_json::from_str(&raw)?)
}

pub fn load_patterns(path: &str) -> anyhow::Result<PatternsFile> {
    let raw = std::fs::read_to_string(path)?;
    Ok(serde_json::from_str(&raw)?)
}

fn pick_range<'a>(p: &'a ParameterDef, sex: &str, age: &str) -> Option<&'a ParameterRange> {
    p.ranges.iter().find(|r| (r.sex == sex || r.sex == "any") && r.age == age)
        .or_else(|| p.ranges.iter().find(|r| r.sex == "any"))
        .or_else(|| p.ranges.first())
}

pub fn classify(value: f64, r: &ParameterRange) -> Zone {
    if value < r.l2_max { Zone::L2 }
    else if value < r.l0.0 { Zone::L1 }
    else if value <= r.l0.1 { Zone::L0 }
    else if value <= r.h2_min { Zone::H1 }
    else { Zone::H2 }
}

fn compute_derived(values: &HashMap<String,f64>, expr: &str) -> Option<f64> {
    match expr {
        "NEUT_abs/LYMPH_abs" => {
            let n = values.get("NEUT_abs")?;
            let l = values.get("LYMPH_abs")?;
            if *l == 0.0 { None } else { Some(n / l) }
        }
        "PLT/LYMPH_abs" => {
            let p = values.get("PLT")?;
            let l = values.get("LYMPH_abs")?;
            if *l == 0.0 { None } else { Some(p / l) }
        }
        "PLT*NEUT_abs/LYMPH_abs" => {
            let p = values.get("PLT")?;
            let n = values.get("NEUT_abs")?;
            let l = values.get("LYMPH_abs")?;
            if *l == 0.0 { None } else { Some(p * n / l) }
        }
        "RDW/PLT" => {
            let r = values.get("RDW")?;
            let p = values.get("PLT")?;
            if *p == 0.0 { None } else { Some(r / p) }
        }
        _ => None,
    }
}

pub fn digitize(input: &CbcInput, refs: &RangesFile) -> DigitizeResponse {
    let mut digitized = Vec::new();
    let mut missing = Vec::new();
    let mut all_values = input.values.clone();

    for p in &refs.parameters {
        if let Some(expr) = &p.derived {
            if !all_values.contains_key(&p.id) {
                if let Some(v) = compute_derived(&all_values, expr) {
                    all_values.insert(p.id.clone(), v);
                }
            }
        }
        let range = match pick_range(p, &input.sex, &input.age) {
            Some(r) => r,
            None => { missing.push(format!("{}: no range for sex={} age={}", p.id, input.sex, input.age)); continue; }
        };
        let value = match all_values.get(&p.id) {
            Some(v) => *v,
            None => { missing.push(p.id.clone()); continue; }
        };
        let zone = classify(value, range);
        digitized.push(DigitizedValue {
            param: p.id.clone(),
            value,
            unit: p.unit.clone(),
            zone,
            reference_range: (range.l0.0, range.l0.1),
        });
    }

    DigitizeResponse {
        sex: input.sex.clone(),
        age: input.age.clone(),
        digitized,
        missing_params: missing,
    }
}

pub fn match_patterns(digi: &[DigitizedValue], patterns: &[Pattern]) -> Vec<MatchedPattern> {
    let zone_map: HashMap<&str, Zone> = digi.iter().map(|d| (d.param.as_str(), d.zone)).collect();
    let mut out = Vec::new();
    for p in patterns {
        let MatchExpr::And { and } = &p.match_expr;
        let mut all_ok = true;
        let mut conds_matched = 0usize;
        for c in and {
            match zone_map.get(c.param.as_str()) {
                Some(z) if c.zone.contains(z) => { conds_matched += 1; }
                Some(_) => { all_ok = false; break; }
                None => { all_ok = false; break; }
            }
        }
        if all_ok && conds_matched == and.len() {
            out.push(MatchedPattern {
                id: p.id.clone(),
                label: p.label.clone(),
                severity: p.severity.clone(),
                differentials: p.differentials.clone(),
                matched_conditions: conds_matched,
            });
        }
    }
    out.sort_by(|a, b| {
        let rank = |s: &str| match s { "red" => 0, "amber" => 1, _ => 2 };
        rank(&a.severity).cmp(&rank(&b.severity))
            .then(b.matched_conditions.cmp(&a.matched_conditions))
    });
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn refs() -> RangesFile {
        let raw = json!({
            "version":"test",
            "parameters":[
                {"id":"WBC","unit":"10^9/L","ranges":[{"sex":"any","age":">=18","L2":2.0,"L1":4.0,"L0":[4.0,11.0],"H1":11.0,"H2":30.0}]},
                {"id":"HGB","unit":"g/L","ranges":[{"sex":"male","age":">=18","L2":80,"L1":135,"L0":[135,175],"H1":175,"H2":210}]},
                {"id":"PLT","unit":"10^9/L","ranges":[{"sex":"any","age":">=18","L2":20,"L1":150,"L0":[150,400],"H1":400,"H2":1000}]}
            ]
        });
        serde_json::from_value(raw).unwrap()
    }

    fn pancytopenia_pattern() -> PatternsFile {
        let raw = json!({
            "version":"test",
            "patterns":[{
                "id":"PANCYTOPENIA","label":"Панцитопения","severity":"red",
                "match":{"AND":[
                    {"param":"WBC","zone":["L1","L2"]},
                    {"param":"HGB","zone":["L1","L2"]},
                    {"param":"PLT","zone":["L1","L2"]}
                ]},
                "differentials":["aplastic_anemia","MDS"]
            }]
        });
        serde_json::from_value(raw).unwrap()
    }

    #[test]
    fn classify_zones() {
        let r = refs(); let p = &r.parameters[0]; let rg = &p.ranges[0];
        assert_eq!(classify(1.5, rg), Zone::L2);
        assert_eq!(classify(3.0, rg), Zone::L1);
        assert_eq!(classify(7.0, rg), Zone::L0);
        assert_eq!(classify(15.0, rg), Zone::H1);
        assert_eq!(classify(45.0, rg), Zone::H2);
    }

    #[test]
    fn digitize_pancytopenia() {
        let r = refs();
        let mut v = HashMap::new();
        v.insert("WBC".to_string(), 1.5);
        v.insert("HGB".to_string(), 70.0);
        v.insert("PLT".to_string(), 30.0);
        let input = CbcInput { values: v, sex: "male".into(), age: ">=18".into() };
        let d = digitize(&input, &r);
        assert_eq!(d.digitized.len(), 3);
        assert!(d.digitized.iter().all(|x| matches!(x.zone, Zone::L1 | Zone::L2)));
    }

    #[test]
    fn match_pancytopenia() {
        let r = refs();
        let pf = pancytopenia_pattern();
        let mut v = HashMap::new();
        v.insert("WBC".to_string(), 1.5);
        v.insert("HGB".to_string(), 70.0);
        v.insert("PLT".to_string(), 30.0);
        let input = CbcInput { values: v, sex:"male".into(), age:">=18".into() };
        let d = digitize(&input, &r);
        let m = match_patterns(&d.digitized, &pf.patterns);
        assert_eq!(m.len(), 1);
        assert_eq!(m[0].id, "PANCYTOPENIA");
        assert_eq!(m[0].severity, "red");
    }

    #[test]
    fn no_match_normal_cbc() {
        let r = refs();
        let pf = pancytopenia_pattern();
        let mut v = HashMap::new();
        v.insert("WBC".to_string(), 7.0);
        v.insert("HGB".to_string(), 150.0);
        v.insert("PLT".to_string(), 250.0);
        let input = CbcInput { values: v, sex:"male".into(), age:">=18".into() };
        let d = digitize(&input, &r);
        let m = match_patterns(&d.digitized, &pf.patterns);
        assert!(m.is_empty());
    }
}
