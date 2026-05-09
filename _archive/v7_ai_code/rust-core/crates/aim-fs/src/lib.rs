//! AIM_FS — three-tier filesystem layer for AIM.
//!
//! See `~/Desktop/LongevityCommon/AIM/docs/AIM_FS/SPEC.md` for the design.
//!
//! Tier 1: user profile (AIM-curated, approval queue gates writes).
//! Tier 2: user-defined projects (scaffold from CONCEPT, 11-file core).
//! Tier 3: auto-created — patient folders, service folders, AI self-development
//!         project. All non-routine writes flow through propose/approve/reject.

pub mod browse;
pub mod db;
pub mod entity;
pub mod error;
pub mod events;
pub mod links;
pub mod proposal;
pub mod schemas;
pub mod search;
pub mod sweeper;
pub mod types;

pub use error::{AimFsError, Result};
pub use proposal::ProposeOutcome;
pub use types::*;

use std::path::{Path, PathBuf};

/// Top-level handle. Holds the SQLite pool + a reference to the data root on disk.
#[derive(Clone)]
pub struct AimFs {
    pub(crate) pool: db::DbPool,
    pub(crate) root: PathBuf,
}

impl AimFs {
    /// Open or create an AIM_FS data directory.
    /// Creates `<root>/_service/db/aim_fs.db` and applies migrations.
    pub fn open(root: impl AsRef<Path>) -> Result<Self> {
        let root = root.as_ref().to_path_buf();
        let db_path = root.join("_service").join("db").join("aim_fs.db");
        let pool = db::open_pool(&db_path)?;

        for sub in [
            "users",
            "_service",
            "_service/db",
            "_service/cas",
            "_service/disputes",
            "_service/inbox",
            "_service/tmp",
            "_service/backup",
            "_self_dev",
            "_self_dev/proposals",
            "_self_dev/proposals/pending",
            "_self_dev/proposals/approved",
            "_self_dev/proposals/rejected",
        ] {
            std::fs::create_dir_all(root.join(sub))?;
        }

        Ok(Self { pool, root })
    }

    pub fn root(&self) -> &Path {
        &self.root
    }

    /// Tier 2 helper: scaffold a new user-defined project under
    /// `users/<user_id>/projects/<slug>/` with the 11-file core.
    /// The CONCEPT body is provided by the caller; the rest is bootstrapped
    /// with placeholders so AI can fill them via propose() afterwards.
    pub fn scaffold_project(
        &self,
        user_id: &str,
        slug: &str,
        concept_body: &str,
    ) -> Result<PathBuf> {
        let dir = self
            .root
            .join("users")
            .join(user_id)
            .join("projects")
            .join(slug);
        std::fs::create_dir_all(&dir)?;
        std::fs::create_dir_all(dir.join("data"))?;
        std::fs::create_dir_all(dir.join("code"))?;
        std::fs::create_dir_all(dir.join("_meta"))?;

        let core: &[(&str, &str)] = &[
            ("CONCEPT.md", concept_body),
            ("THEORY.md", "<!-- immutable; теоретическое обоснование -->\n"),
            ("PARAMETERS.md", "# Parameters\n"),
            ("KNOWLEDGE.md", "# Knowledge / verified citations\n"),
            ("MAP.md", "# Project file map\n"),
            ("UPGRADE.md", "# Upgrade plan\n"),
            ("TODO.md", "# TODO\n"),
            (
                "README.md",
                &format!("# {slug}\n\nUser-defined project, scaffolded by AIM_FS.\n"),
            ),
            ("CLAUDE.md", "# Instructions for AI agents\n"),
            ("STATE.md", "# State\n\nstatus: draft\n"),
            ("EVIDENCE.md", "# Evidence base\n"),
        ];
        for (name, body) in core {
            std::fs::write(dir.join(name), body)?;
        }
        std::fs::write(dir.join("_meta").join("links.jsonl"), "")?;
        std::fs::write(dir.join("_meta").join("events.jsonl"), "")?;
        Ok(dir)
    }

    /// Tier 3.a helper: create a patient folder skeleton for the doctor.
    /// `patient_key` should follow `<Surname>_<Name>_<YYYY_MM_DD>` per AIM
    /// memory rule.
    pub fn ensure_patient(&self, doctor_id: &str, patient_key: &str) -> Result<PathBuf> {
        let dir = self
            .root
            .join("users")
            .join(doctor_id)
            .join("patients")
            .join(patient_key);
        for sub in ["visits", "recipes", "notes", "_meta", "_inbox"] {
            std::fs::create_dir_all(dir.join(sub))?;
        }
        let anamnesis = dir.join("ANAMNESIS.md");
        if !anamnesis.exists() {
            std::fs::write(&anamnesis, "# Анамнез\n")?;
        }
        Ok(dir)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn tmp() -> tempfile::TempDir {
        tempfile::tempdir().unwrap()
    }

    fn pol() -> ApprovalPolicy {
        ApprovalPolicy {
            auto_approve_user_commands: true,
            auto_approve_observational_with_confidence_above: 0.95,
            auto_approve_service_events: true,
            require_approval_for: vec![
                "feedback".into(),
                "proposal".into(),
                "recipe".into(),
                "diagnosis".into(),
            ],
            max_inactivity_days: 30,
        }
    }

    fn user() -> String {
        uuid::Uuid::new_v4().to_string()
    }

    fn new_entity(user_id: &str, schema: &str, src: Source, conf: Option<f64>) -> NewEntity {
        // Body and tags chosen to satisfy `feedback_v1` schema constraints
        // (which check for tags and a `Why:` / `How to apply:` hint); other
        // schemas don't care.
        NewEntity {
            schema: schema.into(),
            schema_version: 1,
            title: Some("test".into()),
            description: Some("d".into()),
            body: Some("**Why:** test body\n**How to apply:** in tests".into()),
            source: src,
            user_id: user_id.into(),
            session_id: None,
            llm_model: None,
            confidence: conf,
            requires_verification: false,
            scope_global: false,
            scope_user_ids: vec![user_id.into()],
            scope_project_ids: None,
            scope_patient_ids: vec![],
            tags: vec!["test".into()],
            decay_ttl_days: None,
            decay_on_expire: None,
            initial_links: vec![],
        }
    }

    #[test]
    fn open_creates_layout() {
        let t = tmp();
        let fs = AimFs::open(t.path()).unwrap();
        assert!(fs.root().join("_service/db/aim_fs.db").exists());
        assert!(fs.root().join("_self_dev/proposals/pending").is_dir());
    }

    #[test]
    fn user_command_auto_approves() {
        let t = tmp();
        let fs = AimFs::open(t.path()).unwrap();
        let u = user();
        let out = fs
            .propose(
                &u,
                new_entity(&u, "fact_v1", Source::UserCommand, None),
                Some("explicit user save"),
                None,
                &pol(),
            )
            .unwrap();
        assert!(out.auto_approved);
        assert_eq!(out.entity_status, EntityStatus::Active);
    }

    #[test]
    fn feedback_requires_approval_even_from_user_command() {
        let t = tmp();
        let fs = AimFs::open(t.path()).unwrap();
        let u = user();
        let out = fs
            .propose(
                &u,
                new_entity(&u, "feedback_v1", Source::UserCommand, None),
                None,
                None,
                &pol(),
            )
            .unwrap();
        assert!(!out.auto_approved);
        assert_eq!(out.entity_status, EntityStatus::Pending);
        let pending = fs.list_pending(&u, 10).unwrap();
        assert_eq!(pending.len(), 1);
    }

    #[test]
    fn approve_then_reject_blocked() {
        let t = tmp();
        let fs = AimFs::open(t.path()).unwrap();
        let u = user();
        let out = fs
            .propose(
                &u,
                new_entity(&u, "feedback_v1", Source::System, Some(0.5)),
                None,
                None,
                &pol(),
            )
            .unwrap();
        let actor = Actor {
            user_id: u.clone(),
            session_id: None,
        };
        fs.approve_proposal(&u, &out.proposal_id, &actor).unwrap();
        let err = fs
            .reject_proposal(&u, &out.proposal_id, &actor, Some("late"))
            .unwrap_err();
        match err {
            AimFsError::BadTransition { from, to } => {
                assert_eq!(from, "approved");
                assert_eq!(to, "rejected");
            }
            other => panic!("expected BadTransition, got {other}"),
        }
    }

    #[test]
    fn idempotency_replay_returns_same_outcome() {
        let t = tmp();
        let fs = AimFs::open(t.path()).unwrap();
        let u = user();
        let key = "test-key-1";
        let out1 = fs
            .propose(
                &u,
                new_entity(&u, "fact_v1", Source::UserCommand, None),
                None,
                Some(key),
                &pol(),
            )
            .unwrap();
        let out2 = fs
            .propose(
                &u,
                new_entity(&u, "fact_v1", Source::UserCommand, None),
                None,
                Some(key),
                &pol(),
            )
            .unwrap();
        assert_eq!(out1.entity_id, out2.entity_id);
        assert_eq!(out1.proposal_id, out2.proposal_id);
    }

    #[test]
    fn scaffold_project_creates_11_file_core() {
        let t = tmp();
        let fs = AimFs::open(t.path()).unwrap();
        let u = user();
        let dir = fs.scaffold_project(&u, "demo_project", "# Demo\n").unwrap();
        for f in [
            "CONCEPT.md",
            "THEORY.md",
            "PARAMETERS.md",
            "KNOWLEDGE.md",
            "MAP.md",
            "UPGRADE.md",
            "TODO.md",
            "README.md",
            "CLAUDE.md",
            "STATE.md",
            "EVIDENCE.md",
        ] {
            assert!(dir.join(f).exists(), "missing {f}");
        }
        assert!(dir.join("_meta/events.jsonl").exists());
    }

    #[test]
    fn supersedes_marks_old_entity_superseded() {
        let t = tmp();
        let fs = AimFs::open(t.path()).unwrap();
        let u = user();
        // Create the original active entity.
        let first = fs
            .propose(
                &u,
                new_entity(&u, "fact_v1", Source::UserCommand, None),
                None,
                None,
                &pol(),
            )
            .unwrap();
        assert_eq!(first.entity_status, EntityStatus::Active);
        // Create a new entity that supersedes it.
        let mut new = new_entity(&u, "fact_v1", Source::UserCommand, None);
        new.initial_links = vec![InitialLink {
            target_id: first.entity_id.clone(),
            link_type: LinkType::Supersedes,
        }];
        let second = fs.propose(&u, new, None, None, &pol()).unwrap();
        assert_eq!(second.entity_status, EntityStatus::Active);
        // Original should now be superseded.
        let original = fs.get_entity(&u, &first.entity_id).unwrap();
        assert_eq!(original.status, EntityStatus::Superseded);
    }

    #[test]
    fn contradicts_active_entity_marks_both_disputed() {
        let t = tmp();
        let fs = AimFs::open(t.path()).unwrap();
        let u = user();
        let first = fs
            .propose(
                &u,
                new_entity(&u, "fact_v1", Source::UserCommand, None),
                None,
                None,
                &pol(),
            )
            .unwrap();
        let mut new = new_entity(&u, "fact_v1", Source::UserCommand, None);
        new.initial_links = vec![InitialLink {
            target_id: first.entity_id.clone(),
            link_type: LinkType::Contradicts,
        }];
        let second = fs.propose(&u, new, None, None, &pol()).unwrap();
        assert_eq!(second.entity_status, EntityStatus::Disputed);
        let original = fs.get_entity(&u, &first.entity_id).unwrap();
        assert_eq!(original.status, EntityStatus::Disputed);
    }

    #[test]
    fn list_projects_returns_scaffolded_dirs() {
        let t = tmp();
        let fs = AimFs::open(t.path()).unwrap();
        let u = user();
        fs.scaffold_project(&u, "alpha", "# Alpha\n\nFirst description.\n").unwrap();
        fs.scaffold_project(&u, "beta", "# Beta project\n\nAnother one.\n").unwrap();
        let list = fs.list_projects(&u).unwrap();
        assert_eq!(list.len(), 2);
        assert_eq!(list[0].slug, "alpha");
        assert_eq!(list[1].slug, "beta");
        assert_eq!(list[0].title.as_deref(), Some("Alpha"));
    }

    #[test]
    fn list_patients_reads_identity_toml() {
        let t = tmp();
        let fs = AimFs::open(t.path()).unwrap();
        let u = user();
        let dir = fs.ensure_patient(&u, "Beridze_Keti_2026_03_12").unwrap();
        std::fs::write(
            dir.join("identity.toml"),
            "surname = \"Beridze\"\nname = \"Keti\"\ndob = \"2026_03_12\"\nphone = \"+995 555 000\"\n",
        )
        .unwrap();
        let list = fs.list_patients(&u).unwrap();
        assert_eq!(list.len(), 1);
        assert_eq!(list[0].surname.as_deref(), Some("Beridze"));
        assert_eq!(list[0].dob.as_deref(), Some("2026_03_12"));
    }

    #[test]
    fn search_finds_active_entity_by_title_substring() {
        let t = tmp();
        let fs = AimFs::open(t.path()).unwrap();
        let u = user();
        let mut new = new_entity(&u, "fact_v1", Source::UserCommand, None);
        new.title = Some("DeepSeek routing rule".into());
        new.body = Some(
            "**Why:** route through DeepSeek\n**How to apply:** in llm.py".into(),
        );
        fs.propose(&u, new, None, None, &pol()).unwrap();
        let hits = fs
            .search(&u, "DeepSeek", &search::SearchScope::default(), 10)
            .unwrap();
        assert_eq!(hits.len(), 1);
        assert!(hits[0].title.as_deref().unwrap().contains("DeepSeek"));
        // FTS5 BM25 score may be small for short corpora; just ensure some
        // signal that the title matched (bm25 score > 0 after our flip, OR
        // fallback LIKE ran and produced positive score).
    }

    #[test]
    fn search_respects_project_scope() {
        let t = tmp();
        let fs = AimFs::open(t.path()).unwrap();
        let u = user();
        let mut a = new_entity(&u, "fact_v1", Source::UserCommand, None);
        a.title = Some("Telomere shortening".into());
        a.scope_project_ids = Some(vec!["telomere".into()]);
        fs.propose(&u, a, None, None, &pol()).unwrap();
        let mut b = new_entity(&u, "fact_v1", Source::UserCommand, None);
        b.title = Some("Telomere coupling".into());
        b.scope_project_ids = Some(vec!["mcoa".into()]);
        fs.propose(&u, b, None, None, &pol()).unwrap();
        let scope = search::SearchScope {
            project_id: Some("mcoa".into()),
            ..Default::default()
        };
        let hits = fs.search(&u, "Telomere", &scope, 10).unwrap();
        assert_eq!(hits.len(), 1);
        assert!(hits[0].title.as_deref().unwrap().contains("coupling"));
    }

    #[test]
    fn add_link_requires_existing_endpoints() {
        let t = tmp();
        let fs = AimFs::open(t.path()).unwrap();
        let u = user();
        let a = fs
            .propose(&u, new_entity(&u, "fact_v1", Source::UserCommand, None), None, None, &pol())
            .unwrap();
        let err = fs.add_link(&u, &a.entity_id, "no_such_id", LinkType::Refines).unwrap_err();
        match err {
            AimFsError::NotFound(_) => {}
            other => panic!("expected NotFound, got {other}"),
        }
    }

    #[test]
    fn cascade_decay_marks_dependents_stale() {
        let t = tmp();
        let fs = AimFs::open(t.path()).unwrap();
        let u = user();
        // Create A (with TTL already expired) and B which depends_on A.
        let mut a = new_entity(&u, "fact_v1", Source::UserCommand, None);
        a.title = Some("A — anchor fact".into());
        a.decay_ttl_days = Some(-1);
        a.decay_on_expire = Some("deprecate".into());
        let a_out = fs.propose(&u, a, None, None, &pol()).unwrap();

        let mut b = new_entity(&u, "fact_v1", Source::UserCommand, None);
        b.title = Some("B — derived fact".into());
        b.initial_links = vec![InitialLink {
            target_id: a_out.entity_id.clone(),
            link_type: LinkType::DependsOn,
        }];
        let b_out = fs.propose(&u, b, None, None, &pol()).unwrap();

        // Sweep: A becomes deprecated (TTL passed); B should cascade to stale.
        let n = sweeper::sweep_once(&fs.pool).unwrap();
        assert!(n >= 2, "expected ≥2 status changes, got {n}");
        let a = fs.get_entity(&u, &a_out.entity_id).unwrap();
        let b = fs.get_entity(&u, &b_out.entity_id).unwrap();
        assert_eq!(a.status, EntityStatus::Deprecated);
        assert_eq!(b.status, EntityStatus::Stale);
    }

    #[test]
    fn sweeper_expires_active_with_past_decay() {
        let t = tmp();
        let fs = AimFs::open(t.path()).unwrap();
        let u = user();
        let mut new = new_entity(&u, "fact_v1", Source::UserCommand, None);
        new.decay_ttl_days = Some(-1); // already expired
        new.decay_on_expire = Some("deprecate".into());
        let _out = fs.propose(&u, new, None, None, &pol()).unwrap();
        let n = sweeper::sweep_once(&fs.pool).unwrap();
        assert!(n >= 1);
    }
}
