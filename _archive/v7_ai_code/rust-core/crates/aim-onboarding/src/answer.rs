use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(untagged)]
pub enum Answer {
    Text(String),
    List(Vec<String>),
    Bool(bool),
    Number(f64),
    NameValueList(Vec<NameValue>),
    /// Used internally when an optional question was skipped.
    Empty,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NameValue {
    pub name: String,
    pub value: String,
}

impl Answer {
    pub fn as_text(&self) -> Option<&str> {
        if let Answer::Text(s) = self {
            Some(s.as_str())
        } else {
            None
        }
    }

    pub fn is_truthy(&self) -> bool {
        match self {
            Answer::Bool(b) => *b,
            Answer::Text(s) => !s.trim().is_empty(),
            Answer::List(v) => !v.is_empty(),
            Answer::NameValueList(v) => !v.is_empty(),
            Answer::Number(n) => *n != 0.0,
            Answer::Empty => false,
        }
    }

    pub fn flat_string(&self) -> String {
        match self {
            Answer::Text(s) => s.clone(),
            Answer::Bool(b) => b.to_string(),
            Answer::Number(n) => n.to_string(),
            Answer::List(v) => v.join(", "),
            Answer::NameValueList(kvs) => kvs
                .iter()
                .map(|kv| format!("{}={}", kv.name, kv.value))
                .collect::<Vec<_>>()
                .join(", "),
            Answer::Empty => String::new(),
        }
    }
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct Answers {
    pub map: BTreeMap<String, Answer>,
}

impl Answers {
    pub fn new() -> Self {
        Self::default()
    }
    pub fn set(&mut self, k: impl Into<String>, v: Answer) {
        self.map.insert(k.into(), v);
    }
    pub fn get(&self, k: &str) -> Option<&Answer> {
        self.map.get(k)
    }
}
