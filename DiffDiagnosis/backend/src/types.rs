use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use uuid::Uuid;

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum ProbabilityClass {
    RedFlag,
    Common,
    Rare,
}

impl ProbabilityClass {
    pub fn base_score(self) -> f64 {
        match self {
            Self::RedFlag => 0.30,
            Self::Common  => 0.50,
            Self::Rare    => 0.10,
        }
    }
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum SystemSchool {
    Vinogradov,
    Taylor,
    Synthesis,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Branch {
    pub answer: String,
    pub next: Option<String>,
    pub conclusion: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Node {
    pub id: String,
    pub question: String,
    pub branches: Vec<Branch>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DifferentialDef {
    pub name: String,
    pub probability_class: ProbabilityClass,
    pub keywords: Vec<String>,
    #[serde(default)]
    pub evidence_for: Vec<String>,
    #[serde(default)]
    pub evidence_against: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Algorithm {
    pub id: String,
    pub source: String,
    pub system: SystemSchool,
    pub presenting_complaint: String,
    #[serde(default)]
    pub keywords: Vec<String>,
    #[serde(default)]
    pub nodes: Vec<Node>,
    pub differentials: Vec<DifferentialDef>,
    #[serde(default)]
    pub red_flags: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Case {
    pub id: Uuid,
    pub free_text: String,
    #[serde(default)]
    pub structured: HashMap<String, serde_json::Value>,
    pub created_at: DateTime<Utc>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct CaseInput {
    pub free_text: String,
    #[serde(default)]
    pub structured: HashMap<String, serde_json::Value>,
}

impl CaseInput {
    pub fn into_case(self) -> Case {
        Case {
            id: Uuid::new_v4(),
            free_text: self.free_text,
            structured: self.structured,
            created_at: Utc::now(),
        }
    }
}

#[derive(Debug, Clone, Serialize)]
pub struct Differential {
    pub name: String,
    pub probability: f64,
    pub probability_class: ProbabilityClass,
    pub source_algorithm: String,
    pub source_school: SystemSchool,
    pub evidence_for: Vec<String>,
    pub evidence_against: Vec<String>,
    pub red_flag: bool,
}

#[derive(Debug, Clone, Serialize)]
pub struct DiffResponse {
    pub case_id: Uuid,
    pub algorithms_matched: Vec<String>,
    pub differentials: Vec<Differential>,
    pub red_flags: Vec<String>,
}
