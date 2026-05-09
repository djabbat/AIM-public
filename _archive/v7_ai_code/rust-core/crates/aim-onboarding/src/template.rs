use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Template {
    pub id: String,
    pub title: String,
    #[serde(default = "default_version")]
    pub version: u32,
    #[serde(default)]
    pub intent: String,
    pub questions: Vec<Question>,
    #[serde(default)]
    pub file_targets: Vec<FileTarget>,
    #[serde(default)]
    pub memory_proposals: Vec<MemoryProposal>,
    /// Optional sub-tree under aim_root in which to drop file_targets.
    /// Defaults to `users/<tenant>/projects/<slug>/` for projects.
    #[serde(default)]
    pub target_dir_template: Option<String>,
}

fn default_version() -> u32 {
    1
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum QuestionType {
    Text,
    Choice,
    MultiChoice,
    List,
    Number,
    Bool,
    Date,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Question {
    pub id: String,
    pub prompt: String,
    #[serde(rename = "type")]
    pub kind: QuestionType,
    #[serde(default)]
    pub required: bool,
    #[serde(default)]
    pub optional: bool,
    #[serde(default)]
    pub multiline: bool,
    #[serde(default)]
    pub options: Vec<String>,
    /// Default value rendered as a string (interpreted per `kind`).
    #[serde(default)]
    pub default: Option<String>,
    /// Regex (Rust `regex` crate syntax) the answer string must match.
    #[serde(default)]
    pub validate_regex: Option<String>,
    /// Conditional inclusion. Question is shown only if all `depends_on` rules pass.
    #[serde(default)]
    pub depends_on: Vec<DependsOn>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DependsOn {
    pub field: String,
    /// Equals — value matches.
    #[serde(default)]
    pub equals: Option<String>,
    /// Not equals.
    #[serde(default)]
    pub not_equals: Option<String>,
    /// Value is in this list.
    #[serde(default)]
    pub in_: Option<Vec<String>>,
    /// Value is NOT in this list (used for `not_in` in YAML).
    #[serde(default, rename = "not_in")]
    pub not_in: Option<Vec<String>>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FileTarget {
    pub path: String,
    pub template: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MemoryProposal {
    pub schema: String,
    pub title_template: String,
    pub body_template: String,
    #[serde(default)]
    pub tags: Vec<String>,
    #[serde(default)]
    pub scope_project_ids: Vec<String>,
    #[serde(default)]
    pub scope_patient_ids: Vec<String>,
    /// If set, the proposal is generated once per element in the named answer
    /// list (e.g. `feedback_rules`).  Each iteration substitutes
    /// `{{this_index}}` and the question id (`{{rule}}` etc.) with the
    /// current value.
    #[serde(default)]
    pub iterate_over: Option<String>,
    /// Optional decay (TTL days).
    #[serde(default)]
    pub decay_ttl_days: Option<i64>,
}

impl Template {
    pub fn from_yaml_str(s: &str) -> Result<Self, serde_yaml::Error> {
        serde_yaml::from_str(s)
    }

    pub fn from_yaml_file(path: &std::path::Path) -> std::io::Result<Self> {
        let s = std::fs::read_to_string(path)?;
        serde_yaml::from_str(&s).map_err(|e| std::io::Error::new(std::io::ErrorKind::InvalidData, e))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const SAMPLE: &str = r#"
id: t1
title: Test
questions:
  - id: slug
    prompt: Slug
    type: text
    required: true
  - id: domain
    prompt: Domain
    type: choice
    options: [biology, software]
"#;

    #[test]
    fn loads_minimal_template() {
        let t = Template::from_yaml_str(SAMPLE).unwrap();
        assert_eq!(t.id, "t1");
        assert_eq!(t.questions.len(), 2);
        assert!(t.questions[0].required);
        assert_eq!(t.questions[1].kind, QuestionType::Choice);
    }
}
