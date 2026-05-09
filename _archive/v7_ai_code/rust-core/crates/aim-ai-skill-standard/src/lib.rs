//! aim-ai-skill-standard — HV4.
//!
//! Bidirectional adapter between AIM's internal skill format and the
//! agentskills.io open standard, so AIM-distilled skills can be
//! consumed by external agents (Hermes, OpenClaw, SwarmClaw) and vice
//! versa.
//!
//! Rust port of `AI/ai/skill_standard.py`. Both formats are JSON; we
//! work in [`serde_json::Value`] to avoid pre-committing to a struct
//! shape (the schemas are loose and we want to preserve unknown fields).

use serde_json::{json, Value};
use std::path::{Path, PathBuf};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum SkillError {
    #[error("missing required field: {0}")]
    MissingField(&'static str),
    #[error("io: {0}")]
    Io(#[from] std::io::Error),
    #[error("json: {0}")]
    Json(#[from] serde_json::Error),
}

/// Map AIM internal skill → agentskills.io schema.
pub fn to_agentskills(aim_skill: &Value) -> Result<Value, SkillError> {
    let skill_id = aim_skill
        .get("skill_id")
        .and_then(|v| v.as_str())
        .ok_or(SkillError::MissingField("skill_id"))?;

    let theme: Vec<String> = aim_skill
        .get("theme")
        .and_then(|v| v.as_array())
        .map(|a| {
            a.iter()
                .filter_map(|x| x.as_str().map(|s| s.to_string()))
                .collect()
        })
        .unwrap_or_default();

    let description = aim_skill
        .get("rationale")
        .and_then(|v| v.as_str())
        .map(|s| s.to_string())
        .filter(|s| !s.is_empty())
        .unwrap_or_else(|| {
            if !theme.is_empty() {
                theme.join(" ")
            } else {
                "(auto-distilled skill)".into()
            }
        });

    let instructions = aim_skill
        .get("body")
        .and_then(|v| v.as_str())
        .map(|s| s.to_string())
        .filter(|s| !s.is_empty())
        .unwrap_or_else(|| {
            format!(
                "## Trigger\n\nTheme keywords: {}\n\n## Approach\n\n{}\n",
                if theme.is_empty() {
                    "(none)".to_string()
                } else {
                    theme.join(", ")
                },
                description
            )
        });

    let version = aim_skill
        .get("version")
        .map(|v| match v {
            Value::String(s) => s.clone(),
            Value::Number(n) => n.to_string(),
            _ => "1.0.0".into(),
        })
        .unwrap_or_else(|| "1.0.0".into());

    let mut tags: Vec<String> = vec!["aim-hive".into(), "auto-distilled".into()];
    if let Some(extra) = aim_skill.get("tags").and_then(|v| v.as_array()) {
        for t in extra {
            if let Some(s) = t.as_str() {
                tags.push(s.into());
            }
        }
    }

    Ok(json!({
        "name": skill_id,
        "description": description,
        "version": version,
        "trigger_phrases": theme,
        "instructions": instructions,
        "examples": aim_skill.get("examples").cloned().unwrap_or(json!([])),
        "metadata": {
            "author": "AIM Hive Queen (auto-distilled)",
            "tags": tags,
            "source_n": aim_skill.get("source_n").cloned().unwrap_or(Value::Null),
            "eval_delta": aim_skill.get("eval_delta").cloned().unwrap_or(Value::Null),
        }
    }))
}

/// Map agentskills.io schema → AIM internal skill.
pub fn from_agentskills(external: &Value) -> Result<Value, SkillError> {
    let name = external
        .get("name")
        .and_then(|v| v.as_str())
        .ok_or(SkillError::MissingField("name"))?;

    let theme: Vec<String> = external
        .get("trigger_phrases")
        .and_then(|v| v.as_array())
        .map(|a| {
            a.iter()
                .filter_map(|x| x.as_str().map(|s| s.to_string()))
                .collect()
        })
        .unwrap_or_default();

    let mut tags: Vec<String> = external
        .get("metadata")
        .and_then(|m| m.get("tags"))
        .and_then(|v| v.as_array())
        .map(|a| {
            a.iter()
                .filter_map(|x| x.as_str().map(|s| s.to_string()))
                .collect()
        })
        .unwrap_or_default();
    tags.push("external-import".into());

    Ok(json!({
        "skill_id": name,
        "theme": theme,
        "rationale": external.get("description").cloned().unwrap_or(Value::String("".into())),
        "version": external.get("version").cloned().unwrap_or(Value::String("1.0.0".into())),
        "body": external.get("instructions").cloned().unwrap_or(Value::String("".into())),
        "examples": external.get("examples").cloned().unwrap_or(json!([])),
        "tags": tags,
    }))
}

/// AIM → agentskills → AIM. Helpful in tests and migrations.
pub fn round_trip_aim(aim_skill: &Value) -> Result<Value, SkillError> {
    let ext = to_agentskills(aim_skill)?;
    from_agentskills(&ext)
}

// ── batch dir IO ────────────────────────────────────────────────

pub fn export_dir(src: &Path, dst: &Path, overwrite: bool) -> Result<u64, SkillError> {
    if !src.exists() {
        return Ok(0);
    }
    std::fs::create_dir_all(dst)?;
    let mut n: u64 = 0;
    for entry in std::fs::read_dir(src)? {
        let entry = entry?;
        let p = entry.path();
        if p.extension().and_then(|s| s.to_str()) != Some("json") {
            continue;
        }
        let target = dst.join(
            p.file_name()
                .map(PathBuf::from)
                .unwrap_or_else(|| PathBuf::from("unknown.json")),
        );
        if target.exists() && !overwrite {
            continue;
        }
        let body = std::fs::read_to_string(&p)?;
        let aim_skill: Value = serde_json::from_str(&body)?;
        let ext = to_agentskills(&aim_skill)?;
        std::fs::write(&target, serde_json::to_string_pretty(&ext)?)?;
        n += 1;
    }
    Ok(n)
}

pub fn import_dir(src: &Path, dst: &Path, overwrite: bool) -> Result<u64, SkillError> {
    if !src.exists() {
        return Ok(0);
    }
    std::fs::create_dir_all(dst)?;
    let mut n: u64 = 0;
    for entry in std::fs::read_dir(src)? {
        let entry = entry?;
        let p = entry.path();
        if p.extension().and_then(|s| s.to_str()) != Some("json") {
            continue;
        }
        let body = std::fs::read_to_string(&p)?;
        let ext: Value = serde_json::from_str(&body)?;
        let aim_skill = from_agentskills(&ext)?;
        let id = aim_skill
            .get("skill_id")
            .and_then(|v| v.as_str())
            .unwrap_or("unknown");
        let target = dst.join(format!("{id}.json"));
        if target.exists() && !overwrite {
            continue;
        }
        std::fs::write(&target, serde_json::to_string_pretty(&aim_skill)?)?;
        n += 1;
    }
    Ok(n)
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    fn to_external_basic() {
        let aim = json!({
            "skill_id": "auto-12345",
            "theme": ["bug", "retry"],
            "rationale": "fix retry loop",
            "version": 2,
            "body": "## Trigger\n\nseen across multiple workers",
            "source_n": 3,
            "eval_delta": 0.07
        });
        let ext = to_agentskills(&aim).unwrap();
        assert_eq!(ext["name"].as_str(), Some("auto-12345"));
        assert_eq!(ext["description"].as_str(), Some("fix retry loop"));
        assert_eq!(ext["version"].as_str(), Some("2"));
        assert_eq!(
            ext["trigger_phrases"].as_array().unwrap().len(),
            2
        );
        assert!(ext["instructions"].as_str().unwrap().contains("multiple workers"));
        assert_eq!(ext["metadata"]["source_n"].as_u64(), Some(3));
    }

    #[test]
    fn to_external_synthesises_instructions_when_body_empty() {
        let aim = json!({
            "skill_id": "auto-empty",
            "theme": ["a", "b"],
            "rationale": "synthesised"
        });
        let ext = to_agentskills(&aim).unwrap();
        let inst = ext["instructions"].as_str().unwrap();
        assert!(inst.contains("Theme keywords: a, b"));
        assert!(inst.contains("synthesised"));
    }

    #[test]
    fn to_external_missing_skill_id_errors() {
        let aim = json!({"theme": []});
        let r = to_agentskills(&aim);
        assert!(matches!(r, Err(SkillError::MissingField("skill_id"))));
    }

    #[test]
    fn from_external_basic() {
        let ext = json!({
            "name": "ext-1",
            "description": "an external skill",
            "version": "0.5",
            "trigger_phrases": ["x", "y"],
            "instructions": "do this",
            "metadata": {"tags": ["from-hermes"]}
        });
        let aim = from_agentskills(&ext).unwrap();
        assert_eq!(aim["skill_id"].as_str(), Some("ext-1"));
        assert_eq!(aim["theme"].as_array().unwrap().len(), 2);
        assert_eq!(aim["rationale"].as_str(), Some("an external skill"));
        assert_eq!(aim["body"].as_str(), Some("do this"));
        let tags: Vec<&str> = aim["tags"].as_array().unwrap().iter()
            .filter_map(|v| v.as_str()).collect();
        assert!(tags.contains(&"from-hermes"));
        assert!(tags.contains(&"external-import"));
    }

    #[test]
    fn from_external_missing_name_errors() {
        let ext = json!({});
        assert!(matches!(
            from_agentskills(&ext),
            Err(SkillError::MissingField("name"))
        ));
    }

    #[test]
    fn round_trip_preserves_skill_id_and_theme() {
        let aim = json!({
            "skill_id": "rt-1",
            "theme": ["alpha", "beta"],
            "rationale": "round trip",
            "version": "1.2.3",
            "body": "ok"
        });
        let back = round_trip_aim(&aim).unwrap();
        assert_eq!(back["skill_id"], aim["skill_id"]);
        let theme_in: Vec<&str> = aim["theme"].as_array().unwrap().iter()
            .filter_map(|v| v.as_str()).collect();
        let theme_out: Vec<&str> = back["theme"].as_array().unwrap().iter()
            .filter_map(|v| v.as_str()).collect();
        assert_eq!(theme_in, theme_out);
    }

    #[test]
    fn export_dir_writes_and_skips_existing() {
        let d = tempdir().unwrap();
        let src = d.path().join("aim");
        let dst = d.path().join("ext");
        std::fs::create_dir_all(&src).unwrap();
        std::fs::write(
            src.join("a.json"),
            r#"{"skill_id":"a","theme":["x"],"rationale":"r"}"#,
        )
        .unwrap();
        let n1 = export_dir(&src, &dst, false).unwrap();
        assert_eq!(n1, 1);
        let n2 = export_dir(&src, &dst, false).unwrap();
        assert_eq!(n2, 0, "second pass without overwrite must skip");
        let n3 = export_dir(&src, &dst, true).unwrap();
        assert_eq!(n3, 1);
    }

    #[test]
    fn import_dir_round_trip() {
        let d = tempdir().unwrap();
        let src = d.path().join("ext");
        let dst = d.path().join("aim");
        std::fs::create_dir_all(&src).unwrap();
        std::fs::write(
            src.join("rocket.json"),
            r#"{"name":"rocket","trigger_phrases":["go"],"description":"d","instructions":"i"}"#,
        )
        .unwrap();
        let n = import_dir(&src, &dst, false).unwrap();
        assert_eq!(n, 1);
        assert!(dst.join("rocket.json").exists());
        let body = std::fs::read_to_string(dst.join("rocket.json")).unwrap();
        let aim: Value = serde_json::from_str(&body).unwrap();
        assert_eq!(aim["skill_id"].as_str(), Some("rocket"));
    }
}
