use serde::{Deserialize, Serialize};
use std::collections::HashMap;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "UPPERCASE")]
pub enum Zone { L2, L1, L0, H1, H2 }

impl Zone {
    pub fn as_str(self) -> &'static str {
        match self { Zone::L2=>"L2",Zone::L1=>"L1",Zone::L0=>"L0",Zone::H1=>"H1",Zone::H2=>"H2" }
    }
}

#[derive(Debug, Clone, Deserialize)]
pub struct ParameterRange {
    pub sex: String,
    pub age: String,
    #[serde(rename="L2")] pub l2_max: f64,
    #[serde(rename="L1")] pub l1_min: f64,
    #[serde(rename="L0")] pub l0: (f64,f64),
    #[serde(rename="H1")] pub h1_min: f64,
    #[serde(rename="H2")] pub h2_min: f64,
}

#[derive(Debug, Clone, Deserialize)]
pub struct ParameterDef {
    pub id: String,
    pub unit: String,
    #[serde(default)]
    pub derived: Option<String>,
    pub ranges: Vec<ParameterRange>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct RangesFile {
    pub version: String,
    pub parameters: Vec<ParameterDef>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct Condition {
    pub param: String,
    pub zone: Vec<Zone>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(untagged)]
pub enum MatchExpr {
    And { #[serde(rename="AND")] and: Vec<Condition> },
}

#[derive(Debug, Clone, Deserialize)]
pub struct Pattern {
    pub id: String,
    pub label: String,
    pub severity: String,
    #[serde(rename="match")]
    pub match_expr: MatchExpr,
    pub differentials: Vec<String>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct PatternsFile {
    pub version: String,
    pub patterns: Vec<Pattern>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct CbcInput {
    pub values: HashMap<String, f64>,
    #[serde(default = "default_sex")]
    pub sex: String,
    #[serde(default = "default_age")]
    pub age: String,
}

fn default_sex() -> String { "any".into() }
fn default_age() -> String { ">=18".into() }

#[derive(Debug, Clone, Serialize)]
pub struct DigitizedValue {
    pub param: String,
    pub value: f64,
    pub unit: String,
    pub zone: Zone,
    pub reference_range: (f64, f64),
}

#[derive(Debug, Clone, Serialize)]
pub struct DigitizeResponse {
    pub sex: String,
    pub age: String,
    pub digitized: Vec<DigitizedValue>,
    pub missing_params: Vec<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct MatchedPattern {
    pub id: String,
    pub label: String,
    pub severity: String,
    pub differentials: Vec<String>,
    pub matched_conditions: usize,
}

#[derive(Debug, Clone, Serialize)]
pub struct SyndromesResponse {
    pub digitized: Vec<DigitizedValue>,
    pub patterns: Vec<MatchedPattern>,
    pub red_count: usize,
    pub amber_count: usize,
    pub green_count: usize,
}
