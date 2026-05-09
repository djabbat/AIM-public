//! aim-profile — multi-tenant profile isolation.
//!
//! Port of `agents/profile.py`. A profile is a named bundle of:
//! - memory dir         `<root>/<name>/memory/`
//! - LangGraph state DB `<root>/<name>/aim_graph_state.db`
//! - LanceDB index      `<root>/<name>/memory_index/`
//! - Per-profile env    `<root>/<name>/profile.env`
//!
//! When `AIM_PROFILE` is set, the canonical paths used by other modules
//! redirect via env-var overrides (`AIM_MEMORY_DIR` etc.). Default
//! `<root>` = `~/.claude/profiles/`.
//!
//! ## Public API
//! - [`Profile`] — handle to a single profile
//! - [`Registry::list_profiles`] — sorted profile listing with metadata
//! - [`Registry::get_active`] / [`Registry::set_active`] — current
//!   pointer file (`current.txt`)
//! - [`Profile::create`] / [`Profile::delete`] / [`Profile::activate_into`]

use chrono::Utc;
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum ProfileError {
    #[error("source profile not found: {0:?}")]
    SourceNotFound(String),
    #[error("cannot delete the default profile")]
    DeletingDefault,
    #[error("io: {0}")]
    Io(#[from] std::io::Error),
    #[error("json: {0}")]
    Json(#[from] serde_json::Error),
}

pub const DEFAULT_PROFILE: &str = "default";

/// Default env-var → subdir map: `AIM_MEMORY_DIR=<root>/<profile>/memory`,
/// etc. Other modules read these at import time so activation is most
/// effective when set BEFORE module imports.
pub fn env_overrides() -> &'static [(&'static str, &'static str)] {
    &[
        ("AIM_MEMORY_DIR", "memory"),
        ("AIM_INDEX_DIR", "memory_index"),
        ("AIM_VERSIONS_DIR", "memory_versions"),
        ("AIM_GRAPH_STATE_DB", "aim_graph_state.db"),
        ("AIM_JOBS_DB", "aim_jobs.db"),
        ("AIM_LLM_CACHE_DB", "llm_cache.db"),
    ]
}

/// Default root: `~/.claude/profiles/`.
pub fn default_profiles_dir() -> PathBuf {
    let home = std::env::var("HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("."));
    home.join(".claude").join("profiles")
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct Metadata {
    pub name: String,
    pub created_at: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub copy_from: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ProfileInfo {
    pub name: String,
    pub active: bool,
    pub created: String,
    pub memory_md_count: u32,
}

#[derive(Debug, Clone)]
pub struct Profile {
    pub name: String,
    pub dir: PathBuf,
}

impl Profile {
    pub fn new(root: &Path, name: impl Into<String>) -> Self {
        let name = name.into();
        Self {
            dir: root.join(&name),
            name,
        }
    }

    pub fn memory_dir(&self) -> PathBuf {
        self.dir.join("memory")
    }
    pub fn index_dir(&self) -> PathBuf {
        self.dir.join("memory_index")
    }
    pub fn versions_dir(&self) -> PathBuf {
        self.dir.join("memory_versions")
    }
    pub fn state_db(&self) -> PathBuf {
        self.dir.join("aim_graph_state.db")
    }
    pub fn jobs_db(&self) -> PathBuf {
        self.dir.join("aim_jobs.db")
    }
    pub fn llm_cache_db(&self) -> PathBuf {
        self.dir.join("llm_cache.db")
    }
    pub fn env_file(&self) -> PathBuf {
        self.dir.join("profile.env")
    }
    pub fn metadata_file(&self) -> PathBuf {
        self.dir.join("metadata.json")
    }

    pub fn exists(&self) -> bool {
        self.dir.is_dir()
    }

    /// Create the profile dir layout. If `copy_from` is set, copies the
    /// source profile's `memory/` and `profile.env`. Always writes
    /// `metadata.json` with the timestamp.
    pub fn create(&self, copy_from: Option<&Profile>) -> Result<(), ProfileError> {
        if let Some(src) = copy_from {
            if !src.exists() {
                return Err(ProfileError::SourceNotFound(src.name.clone()));
            }
        }
        std::fs::create_dir_all(&self.dir)?;
        for sub in ["memory", "memory_index", "memory_versions"] {
            std::fs::create_dir_all(self.dir.join(sub))?;
        }
        std::fs::create_dir_all(self.memory_dir().join("user_memories"))?;

        if let Some(src) = copy_from {
            if src.memory_dir().exists() {
                copy_dir_recursive(&src.memory_dir(), &self.memory_dir())?;
            }
            if src.env_file().exists() {
                std::fs::copy(src.env_file(), self.env_file())?;
            }
        }

        let metadata = Metadata {
            name: self.name.clone(),
            created_at: Utc::now().format("%Y-%m-%dT%H:%M:%S").to_string(),
            copy_from: copy_from.map(|p| p.name.clone()),
        };
        std::fs::write(self.metadata_file(), serde_json::to_string_pretty(&metadata)?)?;
        Ok(())
    }

    /// Read the profile's metadata.json (None if missing or malformed).
    pub fn metadata(&self) -> Option<Metadata> {
        let f = self.metadata_file();
        if !f.exists() {
            return None;
        }
        let raw = std::fs::read_to_string(&f).ok()?;
        serde_json::from_str(&raw).ok()
    }

    /// Count `*.md` files in the profile's memory dir.
    pub fn memory_md_count(&self) -> u32 {
        let d = self.memory_dir();
        if !d.exists() {
            return 0;
        }
        std::fs::read_dir(&d)
            .ok()
            .into_iter()
            .flatten()
            .filter_map(|e| e.ok())
            .filter(|e| e.path().extension().and_then(|s| s.to_str()) == Some("md"))
            .count() as u32
    }

    /// Build the env-var map this profile would set if activated.
    /// Mirrors Python's [`activate`] without mutating the process env.
    /// Includes `AIM_PROFILE=<name>` plus the path-redirect map.
    pub fn env_map(&self) -> BTreeMap<String, String> {
        let mut map: BTreeMap<String, String> = BTreeMap::new();
        map.insert("AIM_PROFILE".into(), self.name.clone());
        for (var, sub) in env_overrides() {
            map.insert(var.to_string(), self.dir.join(sub).to_string_lossy().to_string());
        }
        // Layer profile.env on top
        if let Ok(body) = std::fs::read_to_string(self.env_file()) {
            for line in body.lines() {
                let line = line.trim();
                if line.is_empty() || line.starts_with('#') {
                    continue;
                }
                if let Some(idx) = line.find('=') {
                    let k = line[..idx].trim().to_string();
                    let v = line[idx + 1..]
                        .trim()
                        .trim_matches(|c: char| c == '"' || c == '\'')
                        .to_string();
                    if !k.is_empty() {
                        map.insert(k, v);
                    }
                }
            }
        }
        map
    }

    /// Apply the env_map to a target HashMap (test seam — host wires
    /// `std::env::set_var` for production activation).
    pub fn activate_into(&self, target: &mut BTreeMap<String, String>) -> Result<(), ProfileError> {
        if !self.exists() {
            self.create(None)?;
        }
        for (k, v) in self.env_map() {
            target.insert(k, v);
        }
        Ok(())
    }

    /// Apply env_map directly to the process environment. Fast path —
    /// production callers should prefer `activate_into` for testability.
    pub fn activate_process(&self) -> Result<(), ProfileError> {
        if !self.exists() {
            self.create(None)?;
        }
        for (k, v) in self.env_map() {
            std::env::set_var(k, v);
        }
        Ok(())
    }
}

fn copy_dir_recursive(src: &Path, dst: &Path) -> std::io::Result<()> {
    std::fs::create_dir_all(dst)?;
    for entry in std::fs::read_dir(src)? {
        let entry = entry?;
        let from = entry.path();
        let to = dst.join(entry.file_name());
        if entry.file_type()?.is_dir() {
            copy_dir_recursive(&from, &to)?;
        } else {
            std::fs::copy(&from, &to)?;
        }
    }
    Ok(())
}

// ── registry ────────────────────────────────────────────────────────────

pub struct Registry {
    pub root: PathBuf,
}

impl Registry {
    pub fn new(root: impl Into<PathBuf>) -> Self {
        Self { root: root.into() }
    }

    pub fn from_default() -> Self {
        Self::new(default_profiles_dir())
    }

    pub fn active_file(&self) -> PathBuf {
        self.root.join("current.txt")
    }

    pub fn get_active(&self) -> String {
        if let Ok(s) = std::fs::read_to_string(self.active_file()) {
            let s = s.trim();
            if !s.is_empty() {
                return s.to_string();
            }
        }
        std::env::var("AIM_PROFILE")
            .ok()
            .filter(|s| !s.trim().is_empty())
            .unwrap_or_else(|| DEFAULT_PROFILE.into())
    }

    pub fn set_active(&self, name: &str) -> Result<(), ProfileError> {
        std::fs::create_dir_all(&self.root)?;
        std::fs::write(self.active_file(), name)?;
        Ok(())
    }

    pub fn profile(&self, name: &str) -> Profile {
        Profile::new(&self.root, name)
    }

    /// Switch to (creating if necessary) and activate the named profile.
    pub fn use_profile(&self, name: &str) -> Result<Profile, ProfileError> {
        let p = self.profile(name);
        if !p.exists() {
            p.create(None)?;
        }
        self.set_active(name)?;
        Ok(p)
    }

    /// Sorted list of profiles with metadata. `active` is true for the
    /// current `current.txt` entry.
    pub fn list_profiles(&self) -> Vec<ProfileInfo> {
        std::fs::create_dir_all(&self.root).ok();
        let active = self.get_active();
        let mut out: Vec<ProfileInfo> = std::fs::read_dir(&self.root)
            .ok()
            .into_iter()
            .flatten()
            .filter_map(|e| e.ok())
            .filter(|e| e.path().is_dir())
            .map(|e| {
                let name = e.file_name().to_string_lossy().to_string();
                let p = self.profile(&name);
                let created = p.metadata().map(|m| m.created_at).unwrap_or_default();
                ProfileInfo {
                    active: name == active,
                    memory_md_count: p.memory_md_count(),
                    name,
                    created,
                }
            })
            .collect();
        out.sort_by(|a, b| a.name.cmp(&b.name));
        out
    }

    pub fn delete(&self, name: &str) -> Result<(), ProfileError> {
        if name == DEFAULT_PROFILE {
            return Err(ProfileError::DeletingDefault);
        }
        let p = self.profile(name);
        if !p.exists() {
            return Ok(());
        }
        std::fs::remove_dir_all(&p.dir)?;
        if self.get_active() == name {
            self.set_active(DEFAULT_PROFILE)?;
        }
        Ok(())
    }

    /// Auto-activate from `AIM_PROFILE` env (mirrors Python). Returns
    /// the activated profile, or None when the var is unset / equals
    /// "default".
    pub fn auto_activate_from_env(&self) -> Result<Option<Profile>, ProfileError> {
        let Ok(name) = std::env::var("AIM_PROFILE") else {
            return Ok(None);
        };
        let name = name.trim();
        if name.is_empty() || name == DEFAULT_PROFILE {
            return Ok(None);
        }
        let p = self.profile(name);
        if !p.exists() {
            p.create(None)?;
        }
        p.activate_process()?;
        Ok(Some(p))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    fn registry() -> (TempDir, Registry) {
        let dir = TempDir::new().unwrap();
        let r = Registry::new(dir.path().join("profiles"));
        (dir, r)
    }

    #[test]
    fn create_lays_out_subdirs() {
        let (_d, r) = registry();
        let p = r.profile("research");
        p.create(None).unwrap();
        assert!(p.memory_dir().is_dir());
        assert!(p.index_dir().is_dir());
        assert!(p.versions_dir().is_dir());
        assert!(p.memory_dir().join("user_memories").is_dir());
        assert!(p.metadata_file().exists());
        let meta = p.metadata().unwrap();
        assert_eq!(meta.name, "research");
        assert!(!meta.created_at.is_empty());
        assert!(meta.copy_from.is_none());
    }

    #[test]
    fn create_with_copy_from_clones_memory() {
        let (_d, r) = registry();
        let src = r.profile("default");
        src.create(None).unwrap();
        std::fs::write(src.memory_dir().join("MEMORY.md"), "# index").unwrap();
        std::fs::write(src.env_file(), "FOO=bar\n").unwrap();

        let dst = r.profile("research");
        dst.create(Some(&src)).unwrap();
        assert!(dst.memory_dir().join("MEMORY.md").exists());
        let body = std::fs::read_to_string(dst.memory_dir().join("MEMORY.md")).unwrap();
        assert_eq!(body, "# index");
        // env_file copied
        assert!(dst.env_file().exists());
        // metadata records copy_from
        assert_eq!(dst.metadata().unwrap().copy_from.as_deref(), Some("default"));
    }

    #[test]
    fn create_with_missing_source_errors() {
        let (_d, r) = registry();
        let src = r.profile("ghost");
        let dst = r.profile("research");
        let err = dst.create(Some(&src)).unwrap_err();
        assert!(matches!(err, ProfileError::SourceNotFound(_)));
    }

    #[test]
    fn delete_default_refused() {
        let (_d, r) = registry();
        r.profile(DEFAULT_PROFILE).create(None).unwrap();
        let err = r.delete(DEFAULT_PROFILE).unwrap_err();
        assert!(matches!(err, ProfileError::DeletingDefault));
    }

    #[test]
    fn delete_nonexistent_is_noop() {
        let (_d, r) = registry();
        r.delete("ghost").unwrap(); // does not error
    }

    #[test]
    fn delete_resets_active_pointer() {
        let (_d, r) = registry();
        let target = r.profile("doomed");
        target.create(None).unwrap();
        r.set_active("doomed").unwrap();
        assert_eq!(r.get_active(), "doomed");
        r.delete("doomed").unwrap();
        assert_eq!(r.get_active(), DEFAULT_PROFILE);
        assert!(!target.dir.exists());
    }

    #[test]
    fn use_profile_creates_and_activates() {
        let (_d, r) = registry();
        let p = r.use_profile("research").unwrap();
        assert!(p.exists());
        assert_eq!(r.get_active(), "research");
    }

    #[test]
    fn list_profiles_marks_active_and_counts() {
        let (_d, r) = registry();
        let a = r.profile("alpha");
        a.create(None).unwrap();
        std::fs::write(a.memory_dir().join("a.md"), "x").unwrap();
        std::fs::write(a.memory_dir().join("b.md"), "x").unwrap();
        let b = r.profile("beta");
        b.create(None).unwrap();
        r.set_active("alpha").unwrap();

        let list = r.list_profiles();
        assert_eq!(list.len(), 2);
        let alpha = list.iter().find(|p| p.name == "alpha").unwrap();
        assert!(alpha.active);
        assert_eq!(alpha.memory_md_count, 2);
        let beta = list.iter().find(|p| p.name == "beta").unwrap();
        assert!(!beta.active);
        assert_eq!(beta.memory_md_count, 0);
    }

    #[test]
    fn list_profiles_sorted() {
        let (_d, r) = registry();
        for name in ["zeta", "alpha", "beta"] {
            r.profile(name).create(None).unwrap();
        }
        let list = r.list_profiles();
        let names: Vec<&str> = list.iter().map(|p| p.name.as_str()).collect();
        assert_eq!(names, vec!["alpha", "beta", "zeta"]);
    }

    #[test]
    fn env_map_includes_all_overrides() {
        let (_d, r) = registry();
        let p = r.profile("research");
        p.create(None).unwrap();
        let env = p.env_map();
        assert_eq!(env.get("AIM_PROFILE"), Some(&"research".to_string()));
        assert!(env.get("AIM_MEMORY_DIR").unwrap().contains("research/memory"));
        assert!(env.get("AIM_INDEX_DIR").unwrap().contains("memory_index"));
        assert!(env.get("AIM_VERSIONS_DIR").unwrap().contains("memory_versions"));
        assert!(env.get("AIM_GRAPH_STATE_DB").unwrap().ends_with("aim_graph_state.db"));
    }

    #[test]
    fn env_map_layers_profile_env_overrides() {
        let (_d, r) = registry();
        let p = r.profile("research");
        p.create(None).unwrap();
        std::fs::write(p.env_file(), "DEEPSEEK_API_KEY=key123\nAIM_MEMORY_DIR=/custom/path\n").unwrap();
        let env = p.env_map();
        // profile.env takes precedence — overrides our default AIM_MEMORY_DIR
        assert_eq!(env.get("AIM_MEMORY_DIR"), Some(&"/custom/path".to_string()));
        assert_eq!(env.get("DEEPSEEK_API_KEY"), Some(&"key123".to_string()));
    }

    #[test]
    fn env_map_strips_quotes_in_profile_env() {
        let (_d, r) = registry();
        let p = r.profile("research");
        p.create(None).unwrap();
        std::fs::write(p.env_file(), "FOO=\"quoted-value\"\nBAR='single-quoted'\n").unwrap();
        let env = p.env_map();
        assert_eq!(env.get("FOO"), Some(&"quoted-value".to_string()));
        assert_eq!(env.get("BAR"), Some(&"single-quoted".to_string()));
    }

    #[test]
    fn activate_into_populates_target_map() {
        let (_d, r) = registry();
        let p = r.profile("research");
        let mut target: BTreeMap<String, String> = BTreeMap::new();
        p.activate_into(&mut target).unwrap();
        // create() ran (profile didn't exist) → it now exists
        assert!(p.exists());
        assert_eq!(target.get("AIM_PROFILE"), Some(&"research".to_string()));
    }

    #[test]
    fn get_active_falls_back_to_default_when_pointer_empty() {
        let (_d, r) = registry();
        std::fs::create_dir_all(&r.root).unwrap();
        std::fs::write(r.active_file(), "").unwrap();
        std::env::remove_var("AIM_PROFILE");
        assert_eq!(r.get_active(), DEFAULT_PROFILE);
    }

    #[test]
    fn metadata_round_trip() {
        let (_d, r) = registry();
        let p = r.profile("research");
        p.create(None).unwrap();
        let meta = p.metadata().unwrap();
        let raw = serde_json::to_string(&meta).unwrap();
        let back: Metadata = serde_json::from_str(&raw).unwrap();
        assert_eq!(back, meta);
    }

    #[test]
    fn memory_md_count_counts_only_markdown() {
        let (_d, r) = registry();
        let p = r.profile("x");
        p.create(None).unwrap();
        std::fs::write(p.memory_dir().join("a.md"), "x").unwrap();
        std::fs::write(p.memory_dir().join("b.md"), "x").unwrap();
        std::fs::write(p.memory_dir().join("c.txt"), "x").unwrap();
        assert_eq!(p.memory_md_count(), 2);
    }
}
