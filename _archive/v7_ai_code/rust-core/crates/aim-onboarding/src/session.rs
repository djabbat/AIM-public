use crate::answer::*;
use crate::error::{OnboardError, Result};
use crate::render::render;
use crate::template::*;
use aim_fs::{AimFs, ApprovalPolicy, InitialLink, NewEntity, Source};
use chrono::Utc;
use std::collections::BTreeMap;
use std::path::Path;

/// In-memory session state during an interview.  After all questions are
/// answered, call `apply_to_aim_fs(...)` to scaffold files + propose memory
/// entries.
pub struct Session {
    pub template: Template,
    pub answers: Answers,
    /// Built-in vars injected automatically (created_at, user_id, slug from question).
    pub auto_vars: BTreeMap<String, Answer>,
}

impl Session {
    pub fn new(template: Template, user_id: &str) -> Self {
        let mut auto = BTreeMap::new();
        auto.insert(
            "created_at".to_string(),
            Answer::Text(Utc::now().to_rfc3339()),
        );
        auto.insert("user_id".to_string(), Answer::Text(user_id.to_string()));
        Self {
            template,
            answers: Answers::new(),
            auto_vars: auto,
        }
    }

    /// Should question be asked given current answers?
    pub fn should_ask(&self, q: &Question) -> bool {
        for dep in &q.depends_on {
            let val = self
                .answers
                .get(&dep.field)
                .map(|a| a.flat_string())
                .unwrap_or_default();
            if let Some(eq) = &dep.equals {
                if &val != eq {
                    return false;
                }
            }
            if let Some(ne) = &dep.not_equals {
                if &val == ne {
                    return false;
                }
            }
            if let Some(list) = &dep.in_ {
                if !list.iter().any(|x| x == &val) {
                    return false;
                }
            }
            if let Some(list) = &dep.not_in {
                if list.iter().any(|x| x == &val) {
                    return false;
                }
            }
        }
        true
    }

    /// Validate one answer against the question definition.
    pub fn validate_answer(q: &Question, a: &Answer) -> Result<()> {
        if q.required && matches!(a, Answer::Empty) {
            return Err(OnboardError::MissingRequired(q.id.clone()));
        }
        if let Some(re) = &q.validate_regex {
            if let Answer::Text(s) = a {
                let re = regex::Regex::new(re)?;
                if !re.is_match(s) {
                    return Err(OnboardError::Validation(format!(
                        "answer `{}` to `{}` does not match {re}",
                        s, q.id
                    )));
                }
            }
        }
        match q.kind {
            QuestionType::Choice => {
                if let Answer::Text(s) = a {
                    if !s.is_empty() && !q.options.iter().any(|o| o == s) {
                        return Err(OnboardError::Validation(format!(
                            "`{s}` is not in options {:?}",
                            q.options
                        )));
                    }
                }
            }
            QuestionType::Number => {
                if let Answer::Text(s) = a {
                    if !s.is_empty() {
                        s.parse::<f64>().map_err(|_| {
                            OnboardError::Validation(format!("`{s}` is not a number"))
                        })?;
                    }
                }
            }
            _ => {}
        }
        Ok(())
    }

    fn render_vars(&self) -> BTreeMap<String, Answer> {
        let mut vars = self.auto_vars.clone();
        for (k, v) in &self.answers.map {
            vars.insert(k.clone(), v.clone());
        }
        vars
    }

    /// Resolve target directory for the file_targets.
    /// Default: `users/<user>/projects/<slug>/` if a `slug` answer exists,
    /// else `users/<user>/onboarding/<template_id>-<ulid>/`.
    pub fn target_dir(&self, aim_root: &Path) -> std::path::PathBuf {
        let user = self
            .auto_vars
            .get("user_id")
            .map(|a| a.flat_string())
            .unwrap_or_else(|| "_unknown".into());

        if let Some(t) = &self.template.target_dir_template {
            let vars = self.render_vars();
            return aim_root.join(render(t, &vars).unwrap_or_default());
        }
        if let Some(slug) = self.answers.get("slug") {
            return aim_root
                .join("users")
                .join(&user)
                .join("projects")
                .join(slug.flat_string());
        }
        aim_root
            .join("users")
            .join(&user)
            .join("onboarding")
            .join(format!(
                "{}-{}",
                self.template.id,
                ulid::Ulid::new().to_string()
            ))
    }

    /// Materialise the template: write `file_targets` to disk and propose
    /// every `memory_proposals` entry through `aim-fs`.
    pub fn apply_to_aim_fs(
        &self,
        fs: &AimFs,
        tenant_id: &str,
        policy: &ApprovalPolicy,
    ) -> Result<ApplyOutcome> {
        let dir = self.target_dir(fs.root());
        std::fs::create_dir_all(&dir)?;
        std::fs::create_dir_all(dir.join("_meta"))?;

        let vars = self.render_vars();
        let mut written = Vec::new();
        for ft in &self.template.file_targets {
            // Render both the path and the body so e.g.
            // `{{created_at}}_{{slug}}.md` produces a real path.
            let rel_path = render(&ft.path, &vars)?;
            // Sanitize: replace path-unsafe chars in rendered path components.
            let rel_path = sanitize_relative_path(&rel_path);
            let body = render(&ft.template, &vars)?;
            let path = dir.join(&rel_path);
            if let Some(parent) = path.parent() {
                std::fs::create_dir_all(parent)?;
            }
            std::fs::write(&path, body)?;
            written.push(rel_path);
        }

        let mut proposed = Vec::new();
        for mp in &self.template.memory_proposals {
            for entity in materialise_memory_proposal(mp, &self.answers, &vars, tenant_id)? {
                let outcome = fs.propose(tenant_id, entity, Some("onboarding"), None, policy)?;
                proposed.push(outcome.entity_id);
            }
        }

        Ok(ApplyOutcome {
            target_dir: dir,
            files_written: written,
            entities_proposed: proposed,
        })
    }
}

#[derive(Debug, Clone)]
pub struct ApplyOutcome {
    pub target_dir: std::path::PathBuf,
    pub files_written: Vec<String>,
    pub entities_proposed: Vec<String>,
}

fn sanitize_relative_path(p: &str) -> String {
    p.split('/')
        .map(|seg| {
            seg.chars()
                .map(|c| match c {
                    '/' | '\\' | ':' | '*' | '?' | '"' | '<' | '>' | '|' | '\0' => '_',
                    c if c.is_whitespace() => '_',
                    c => c,
                })
                .collect::<String>()
        })
        .filter(|s| !s.is_empty() && s != "." && s != "..")
        .collect::<Vec<_>>()
        .join("/")
}

fn materialise_memory_proposal(
    mp: &MemoryProposal,
    answers: &Answers,
    vars: &BTreeMap<String, Answer>,
    tenant_id: &str,
) -> Result<Vec<NewEntity>> {
    let mut out = Vec::new();

    let scope_project_ids: Vec<String> = mp
        .scope_project_ids
        .iter()
        .map(|s| render(s, vars).unwrap_or_else(|_| s.clone()))
        .collect();
    let scope_patient_ids: Vec<String> = mp
        .scope_patient_ids
        .iter()
        .map(|s| render(s, vars).unwrap_or_else(|_| s.clone()))
        .collect();

    if let Some(loop_field) = &mp.iterate_over {
        let list = match answers.get(loop_field).cloned().unwrap_or(Answer::Empty) {
            Answer::List(v) => v,
            Answer::NameValueList(kvs) => kvs.into_iter().map(|kv| kv.name).collect(),
            Answer::Text(s) if !s.is_empty() => vec![s],
            _ => vec![],
        };
        for v in list {
            let mut local = vars.clone();
            // The element is exposed under the same key as the question
            // (e.g. `{{rule}}` for `feedback_rules`).
            let singular = loop_field.trim_end_matches('s').to_string();
            local.insert(singular.clone(), Answer::Text(v.clone()));
            local.insert("this".to_string(), Answer::Text(v));
            out.push(NewEntity {
                schema: mp.schema.clone(),
                schema_version: 1,
                title: Some(render(&mp.title_template, &local)?),
                description: None,
                body: Some(render(&mp.body_template, &local)?),
                source: Source::UserCommand,
                user_id: tenant_id.to_string(),
                session_id: None,
                llm_model: None,
                confidence: Some(1.0),
                requires_verification: false,
                scope_global: false,
                scope_user_ids: vec![tenant_id.to_string()],
                scope_project_ids: if scope_project_ids.is_empty() {
                    None
                } else {
                    Some(scope_project_ids.clone())
                },
                scope_patient_ids: scope_patient_ids.clone(),
                tags: mp.tags.clone(),
                decay_ttl_days: mp.decay_ttl_days,
                decay_on_expire: None,
                initial_links: Vec::<InitialLink>::new(),
            });
        }
    } else {
        out.push(NewEntity {
            schema: mp.schema.clone(),
            schema_version: 1,
            title: Some(render(&mp.title_template, vars)?),
            description: None,
            body: Some(render(&mp.body_template, vars)?),
            source: Source::UserCommand,
            user_id: tenant_id.to_string(),
            session_id: None,
            llm_model: None,
            confidence: Some(1.0),
            requires_verification: false,
            scope_global: false,
            scope_user_ids: vec![tenant_id.to_string()],
            scope_project_ids: if scope_project_ids.is_empty() {
                None
            } else {
                Some(scope_project_ids)
            },
            scope_patient_ids,
            tags: mp.tags.clone(),
            decay_ttl_days: mp.decay_ttl_days,
            decay_on_expire: None,
            initial_links: Vec::<InitialLink>::new(),
        });
    }
    Ok(out)
}
