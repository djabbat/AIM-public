```rust
// src/types.rs

use serde::{Deserialize, Serialize};

/// Represents a clinical case with relevant data and differential diagnoses.
#[derive(Serialize, Deserialize, Debug, Clone, PartialEq)]
pub struct Case {
    pub id: String,
    pub description: String,
    pub symptoms: Vec<String>,
    pub findings: Vec<String>,
    pub differentials: Vec<Differential>,
}

/// A differential diagnosis with an assigned probability class.
#[derive(Serialize, Deserialize, Debug, Clone, PartialEq)]
pub struct Differential {
    pub diagnosis: String,
    pub probability: ProbabilityClass,
}

/// Probability categories used in differential diagnosis (e.g., high/medium/low).
#[derive(Serialize, Deserialize, Debug, Clone, PartialEq)]
pub enum ProbabilityClass {
    High,
    Medium,
    Low,
}

/// A clinical algorithm consisting of decision nodes and branches.
#[derive(Serialize, Deserialize, Debug, Clone, PartialEq)]
pub struct Algorithm {
    pub id: String,
    pub name: String,
    pub nodes: Vec<Node>,
    pub branches: Vec<Branch>,
    pub root_node_id: String,
}

/// A single node in the clinical algorithm (e.g., a decision point or outcome).
#[derive(Serialize, Deserialize, Debug, Clone, PartialEq)]
pub struct Node {
    pub id: String,
    pub label: String,
    pub node_type: NodeType,
    pub question: Option<String>,
    pub outcome: Option<String>,
}

/// Type of algorithm node: decision (with branches) or terminal outcome.
#[derive(Serialize, Deserialize, Debug, Clone, PartialEq)]
pub enum NodeType {
    Decision,
    Outcome,
}

/// A directed transition between two nodes, triggered by a condition.
#[derive(Serialize, Deserialize, Debug, Clone, PartialEq)]
pub struct Branch {
    pub from_node_id: String,
    pub to_node_id: String,
    pub condition: String,
}
```