//! AIM onboarding — guided creation of projects / patients / self-dev
//! proposals via per-template question scripts.
//!
//! Closes the "empty scaffold + AI fills later" gap identified in
//! `~/Desktop/LongevityCommon/AIM/docs/AIM_FS/ONBOARDING.md`.
//!
//! # Quickstart
//!
//! ```no_run
//! use aim_onboarding::{Session, Template};
//! use aim_fs::{AimFs, ApprovalPolicy};
//!
//! let template = Template::from_yaml_file(std::path::Path::new("templates/project.yaml")).unwrap();
//! let fs = AimFs::open("/tmp/aim_root").unwrap();
//! let mut s = Session::new(template, "doctor-uuid");
//! // populate s.answers via cli::run() or programmatically …
//! let outcome = s.apply_to_aim_fs(&fs, "doctor-uuid", &ApprovalPolicy::default()).unwrap();
//! println!("scaffolded {}", outcome.target_dir.display());
//! ```

pub mod answer;
pub mod cli;
pub mod error;
pub mod render;
pub mod session;
pub mod template;

pub use answer::{Answer, Answers, NameValue};
pub use error::{OnboardError, Result};
pub use session::{ApplyOutcome, Session};
pub use template::{DependsOn, FileTarget, MemoryProposal, Question, QuestionType, Template};

#[cfg(test)]
mod tests {
    use super::*;
    use aim_fs::{AimFs, ApprovalPolicy};
    use std::collections::BTreeMap;

    const RESEARCH_TEMPLATE: &str = r#"
id: research_project
title: New project
questions:
  - id: slug
    prompt: Slug
    type: text
    required: true
  - id: title
    prompt: Title
    type: text
    required: true
  - id: description
    prompt: Description
    type: text
    multiline: true
  - id: parameters
    prompt: Params
    type: list
    optional: true
  - id: feedback_rules
    prompt: Rules for AI
    type: list
    optional: true
file_targets:
  - path: CONCEPT.md
    template: |
      # {{title}}

      Slug: {{slug}}

      {{description}}
  - path: PARAMETERS.md
    template: |
      # Parameters
      {% for kv in parameters %}- {{kv.name}} = {{kv.value}}
      {% endfor %}
memory_proposals:
  - schema: feedback_v1
    title_template: "Project rule: {{rule}}"
    body_template: "**Why:** onboarding\n**How to apply:** for {{slug}}\n\nRule: {{rule}}"
    tags: [onboarding, project_rule]
    scope_project_ids: ["{{slug}}"]
    iterate_over: feedback_rules
"#;

    fn user() -> String {
        uuid::Uuid::new_v4().to_string()
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

    fn populated_session(template: Template, uid: &str) -> Session {
        let mut s = Session::new(template, uid);
        s.answers.set("slug", Answer::Text("demo".into()));
        s.answers.set("title", Answer::Text("Demo Project".into()));
        s.answers
            .set("description", Answer::Text("Hello world.".into()));
        s.answers.set(
            "parameters",
            Answer::NameValueList(vec![
                NameValue {
                    name: "alpha".into(),
                    value: "0.0082".into(),
                },
                NameValue {
                    name: "beta".into(),
                    value: "0.005".into(),
                },
            ]),
        );
        s.answers.set(
            "feedback_rules",
            Answer::List(vec![
                "Self-citation ≤ 15 %".into(),
                "Verify PMID".into(),
            ]),
        );
        s
    }

    #[test]
    fn end_to_end_scaffold_and_propose() {
        let dir = tempfile::tempdir().unwrap();
        let fs = AimFs::open(dir.path()).unwrap();
        let uid = user();
        let template = Template::from_yaml_str(RESEARCH_TEMPLATE).unwrap();
        let s = populated_session(template, &uid);
        let outcome = s.apply_to_aim_fs(&fs, &uid, &pol()).unwrap();
        assert!(outcome.target_dir.join("CONCEPT.md").exists());
        let concept = std::fs::read_to_string(outcome.target_dir.join("CONCEPT.md")).unwrap();
        assert!(concept.contains("Slug: demo"));
        assert!(concept.contains("# Demo Project"));
        let params = std::fs::read_to_string(outcome.target_dir.join("PARAMETERS.md")).unwrap();
        assert!(params.contains("alpha = 0.0082"));
        assert!(params.contains("beta = 0.005"));
        // 2 feedback rules → 2 entities. Plus pending until policy allows
        // (feedback is in require_approval_for → status=pending).
        assert_eq!(outcome.entities_proposed.len(), 2);
        let pending = fs.list_pending(&uid, 100).unwrap();
        assert_eq!(pending.len(), 2);
    }

    #[test]
    fn depends_on_skips_question() {
        let mut s = Session::new(
            Template::from_yaml_str(RESEARCH_TEMPLATE).unwrap(),
            "u1",
        );
        let q = Question {
            id: "x".into(),
            prompt: "?".into(),
            kind: QuestionType::Text,
            required: false,
            optional: false,
            multiline: false,
            options: vec![],
            default: None,
            validate_regex: None,
            depends_on: vec![DependsOn {
                field: "domain".into(),
                equals: Some("software".into()),
                not_equals: None,
                in_: None,
                not_in: None,
            }],
        };
        // domain not set → should not ask
        assert!(!s.should_ask(&q));
        s.answers.set("domain", Answer::Text("software".into()));
        assert!(s.should_ask(&q));
        s.answers.set("domain", Answer::Text("biology".into()));
        assert!(!s.should_ask(&q));
    }

    #[test]
    fn render_namevalue_loop_in_template() {
        let mut vars: BTreeMap<String, Answer> = BTreeMap::new();
        vars.insert(
            "params".into(),
            Answer::NameValueList(vec![NameValue {
                name: "k".into(),
                value: "v".into(),
            }]),
        );
        let out = render::render(
            "{% for kv in params %}{{kv.name}}={{kv.value}}{% endfor %}",
            &vars,
        )
        .unwrap();
        assert_eq!(out, "k=v");
    }
}
