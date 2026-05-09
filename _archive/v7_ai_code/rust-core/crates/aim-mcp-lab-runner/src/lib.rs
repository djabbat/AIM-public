//! aim-mcp-lab-runner — config helpers for hardware-experiment MCP runners.
//!
//! Phase B (HW1, 2026-05-06). AIM does NOT drive hardware directly —
//! it sends structured tasks to an external worker (Claude Code in
//! headless mode, a custom Rust binary, or anything that speaks the
//! Model Context Protocol). This crate is the configuration layer:
//! it generates / validates the TOML config that lives at
//! `~/.aim/mcp/<name>.toml` for `agents/mcp_loader.py` to consume.
//!
//! It deliberately does NOT implement the JSON-RPC client — that lives
//! in `agents/mcp_loader.py` already. We just produce well-formed TOML.

use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum McpError {
    #[error("io: {0}")]
    Io(#[from] std::io::Error),
    #[error("invalid config: {0}")]
    Invalid(String),
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct LabRunnerConfig {
    /// Display name (`E0`, `AutomatedMicroscopy`, …)
    pub name: String,
    /// Server section.
    pub server: ServerSpec,
    /// Map of tool_id → human description. The runner is expected to
    /// implement these as MCP tools.
    pub tools: Vec<ToolSpec>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ServerSpec {
    pub command: String,
    #[serde(default)]
    pub args: Vec<String>,
    #[serde(default)]
    pub env: Vec<(String, String)>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ToolSpec {
    pub id: String,
    pub description: String,
    #[serde(default)]
    pub require_consent: bool,
}

impl LabRunnerConfig {
    /// Build a default Claude-Code-headless lab runner config for an
    /// experiment that lives at `<project_root>` (e.g.
    /// `/home/oem/Desktop/LongevityCommon/AutomatedMicroscopy`).
    pub fn claude_code_default(name: &str, project_root: &Path) -> Self {
        Self {
            name: name.to_string(),
            server: ServerSpec {
                command: "claude".into(),
                args: vec![
                    "--mcp-mode".into(),
                    "--project".into(),
                    project_root.to_string_lossy().into_owned(),
                ],
                env: Vec::new(),
            },
            tools: vec![
                ToolSpec {
                    id: "queue_imaging_run".into(),
                    description: "Schedule an imaging run with given ROI / channel / interval".into(),
                    require_consent: false,
                },
                ToolSpec {
                    id: "request_calibration".into(),
                    description: "Mark experiment for next-window calibration".into(),
                    require_consent: false,
                },
                ToolSpec {
                    id: "fire_laser".into(),
                    description: "Trigger laser pulse — biosafety gated; require_consent ON".into(),
                    require_consent: true,
                },
                ToolSpec {
                    id: "abort_run".into(),
                    description: "Halt current run and tag NDJSON with abort marker".into(),
                    require_consent: true,
                },
            ],
        }
    }

    /// Render to TOML string.
    pub fn to_toml(&self) -> String {
        let mut out = String::new();
        out.push_str(&format!("# AIM lab-runner MCP config — {}\n\n", self.name));
        out.push_str("[server]\n");
        out.push_str(&format!("command = {}\n", toml_string(&self.server.command)));
        let args_s = self
            .server
            .args
            .iter()
            .map(|a| toml_string(a))
            .collect::<Vec<_>>()
            .join(", ");
        out.push_str(&format!("args = [{}]\n", args_s));
        for (k, v) in &self.server.env {
            out.push_str(&format!("env.{} = {}\n", k, toml_string(v)));
        }
        for t in &self.tools {
            out.push_str(&format!("\n[[tools]]\n"));
            out.push_str(&format!("id = {}\n", toml_string(&t.id)));
            out.push_str(&format!(
                "description = {}\n",
                toml_string(&t.description)
            ));
            if t.require_consent {
                out.push_str("require_consent = true\n");
            }
        }
        out
    }

    /// Write config to `<dir>/<name>.toml`. Returns full path.
    pub fn write_to_dir(&self, dir: &Path) -> Result<PathBuf, McpError> {
        std::fs::create_dir_all(dir)?;
        let p = dir.join(format!("{}.toml", self.name));
        std::fs::write(&p, self.to_toml())?;
        Ok(p)
    }

    /// Default destination dir: `~/.aim/mcp/`.
    pub fn default_dir() -> PathBuf {
        let home = std::env::var("HOME")
            .map(PathBuf::from)
            .unwrap_or_else(|_| PathBuf::from("."));
        home.join(".aim").join("mcp")
    }
}

fn toml_string(s: &str) -> String {
    let escaped = s.replace('\\', r"\\").replace('"', r#"\""#);
    format!("\"{escaped}\"")
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    #[test]
    fn claude_code_default_has_4_tools() {
        let cfg = LabRunnerConfig::claude_code_default("E0", Path::new("/tmp/E0"));
        assert_eq!(cfg.name, "E0");
        assert_eq!(cfg.tools.len(), 4);
        assert!(cfg.tools.iter().any(|t| t.id == "fire_laser" && t.require_consent));
    }

    #[test]
    fn to_toml_roundtrip() {
        let cfg = LabRunnerConfig::claude_code_default(
            "AutomatedMicroscopy",
            Path::new("/home/oem/Desktop/LongevityCommon/AutomatedMicroscopy"),
        );
        let s = cfg.to_toml();
        assert!(s.contains("[server]"));
        assert!(s.contains(r#"command = "claude""#));
        assert!(s.contains("--mcp-mode"));
        assert!(s.contains("[[tools]]"));
        assert!(s.contains("require_consent = true"));
    }

    #[test]
    fn write_to_dir_creates_file() {
        let tmp = TempDir::new().unwrap();
        let cfg = LabRunnerConfig::claude_code_default("E0", Path::new("/tmp"));
        let p = cfg.write_to_dir(tmp.path()).unwrap();
        assert!(p.exists());
        let txt = std::fs::read_to_string(&p).unwrap();
        assert!(txt.contains("[server]"));
    }

    #[test]
    fn default_dir_has_aim_mcp_suffix() {
        let p = LabRunnerConfig::default_dir();
        assert!(p.ends_with(".aim/mcp"));
    }

    #[test]
    fn toml_string_escapes_quotes() {
        assert_eq!(toml_string("hello"), "\"hello\"");
        assert_eq!(toml_string("a\"b"), "\"a\\\"b\"");
        assert_eq!(toml_string("a\\b"), "\"a\\\\b\"");
    }
}
