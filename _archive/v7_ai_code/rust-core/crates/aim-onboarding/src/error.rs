use thiserror::Error;

#[derive(Debug, Error)]
pub enum OnboardError {
    #[error("io: {0}")]
    Io(#[from] std::io::Error),
    #[error("yaml: {0}")]
    Yaml(#[from] serde_yaml::Error),
    #[error("regex: {0}")]
    Regex(#[from] regex::Error),
    #[error("validation: {0}")]
    Validation(String),
    #[error("required answer missing for question `{0}`")]
    MissingRequired(String),
    #[error("unknown question id `{0}` referenced in placeholder/depends_on")]
    UnknownQuestion(String),
    #[error("aim-fs: {0}")]
    AimFs(#[from] aim_fs::AimFsError),
    #[error("template error: {0}")]
    Template(String),
    #[error("other: {0}")]
    Other(String),
}

pub type Result<T> = std::result::Result<T, OnboardError>;
