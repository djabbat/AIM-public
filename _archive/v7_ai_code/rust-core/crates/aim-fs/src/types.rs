use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum EntityStatus {
    Pending,
    Active,
    Superseded,
    Rejected,
    Deprecated,
    Expired,
    Disputed,
    /// Cascaded decay — entity is still nominally `active` but a dependency
    /// expired/deprecated, so the agent should treat it with suspicion until
    /// a fresh review (Phase 2 SPEC §7).
    Stale,
}

impl EntityStatus {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Pending => "pending",
            Self::Active => "active",
            Self::Superseded => "superseded",
            Self::Rejected => "rejected",
            Self::Deprecated => "deprecated",
            Self::Expired => "expired",
            Self::Disputed => "disputed",
            Self::Stale => "stale",
        }
    }
    pub fn from_str(s: &str) -> Option<Self> {
        Some(match s {
            "pending" => Self::Pending,
            "active" => Self::Active,
            "superseded" => Self::Superseded,
            "rejected" => Self::Rejected,
            "deprecated" => Self::Deprecated,
            "expired" => Self::Expired,
            "disputed" => Self::Disputed,
            "stale" => Self::Stale,
            _ => return None,
        })
    }
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Source {
    UserMessage,
    UserCommand,
    System,
}

impl Source {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::UserMessage => "user_message",
            Self::UserCommand => "user_command",
            Self::System => "system",
        }
    }
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum ProposalStatus {
    Pending,
    Approved,
    Rejected,
    Blocked,
}

impl ProposalStatus {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Pending => "pending",
            Self::Approved => "approved",
            Self::Rejected => "rejected",
            Self::Blocked => "blocked",
        }
    }
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum ProposalType {
    Create,
    Update,
    Revert,
    Delete,
}

impl ProposalType {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Create => "create",
            Self::Update => "update",
            Self::Revert => "revert",
            Self::Delete => "delete",
        }
    }
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum LinkType {
    DependsOn,
    Refines,
    Supersedes,
    Contradicts,
    References,
    ProducedBy,
}

impl LinkType {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::DependsOn => "depends_on",
            Self::Refines => "refines",
            Self::Supersedes => "supersedes",
            Self::Contradicts => "contradicts",
            Self::References => "references",
            Self::ProducedBy => "produced_by",
        }
    }
}

/// New-entity payload from caller.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NewEntity {
    pub schema: String,
    pub schema_version: i64,
    pub title: Option<String>,
    pub description: Option<String>,
    pub body: Option<String>,
    pub source: Source,
    pub user_id: String,
    pub session_id: Option<String>,
    pub llm_model: Option<String>,
    pub confidence: Option<f64>,
    pub requires_verification: bool,
    pub scope_global: bool,
    pub scope_user_ids: Vec<String>,
    pub scope_project_ids: Option<Vec<String>>,
    pub scope_patient_ids: Vec<String>,
    pub tags: Vec<String>,
    pub decay_ttl_days: Option<i64>,
    pub decay_on_expire: Option<String>,
    /// Optional initial outgoing links — created in the same transaction as
    /// the entity itself.  If any `contradicts` link points to an active
    /// entity, the new entity is created with `status = disputed` instead
    /// of the normal `pending`/`active` (SPEC §6 + §8).
    #[serde(default)]
    pub initial_links: Vec<InitialLink>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct InitialLink {
    pub target_id: String,
    pub link_type: LinkType,
}

/// Entity row read from SQLite.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Entity {
    pub id: String,
    pub tenant_id: String,
    pub schema: String,
    pub schema_version: i64,
    pub title: Option<String>,
    pub description: Option<String>,
    pub body: Option<String>,
    pub status: EntityStatus,
    pub confidence: Option<f64>,
    pub source: String,
    pub user_id: String,
    pub session_id: Option<String>,
    pub llm_model: Option<String>,
    pub requires_verification: bool,
    pub scope_global: bool,
    pub scope_user_ids: Vec<String>,
    pub scope_project_ids: Option<Vec<String>>,
    pub scope_patient_ids: Vec<String>,
    pub tags: Vec<String>,
    pub decay_ttl_days: Option<i64>,
    pub decay_expires_at: Option<String>,
    pub decay_on_expire: String,
    pub version: i64,
    pub created_at: String,
    pub updated_at: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Proposal {
    pub id: String,
    pub tenant_id: String,
    pub entity_id: String,
    pub proposal_type: ProposalType,
    pub status: ProposalStatus,
    pub proposed_data: Option<String>,
    pub rationale: Option<String>,
    pub proposed_by_user_id: Option<String>,
    pub approved_by_user_id: Option<String>,
    pub blocked_reason: Option<String>,
    pub version_at_proposal: i64,
    pub created_at: String,
    pub updated_at: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Actor {
    pub user_id: String,
    pub session_id: Option<String>,
}

/// Auto-approve preferences (per-user, loaded from preferences.md).
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct ApprovalPolicy {
    #[serde(default)]
    pub auto_approve_user_commands: bool,
    #[serde(default)]
    pub auto_approve_observational_with_confidence_above: f64, // 0..1
    #[serde(default)]
    pub auto_approve_service_events: bool,
    #[serde(default)]
    pub require_approval_for: Vec<String>,
    #[serde(default = "default_max_inactivity")]
    pub max_inactivity_days: i64,
}

fn default_max_inactivity() -> i64 {
    30
}
