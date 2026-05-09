//! Property-based tests for AIM_FS invariants.
//!
//! These complement the example-based tests in `lib.rs` by quantifying
//! over many shapes of input.  Each property is a contract from SPEC v11
//! that should hold for any input.

use aim_fs::{
    search::SearchScope, Actor, AimFs, ApprovalPolicy, EntityStatus, InitialLink, LinkType,
    NewEntity, Source,
};
use proptest::prelude::*;
use uuid::Uuid;

fn pol() -> ApprovalPolicy {
    ApprovalPolicy {
        auto_approve_user_commands: true,
        auto_approve_observational_with_confidence_above: 0.95,
        auto_approve_service_events: true,
        require_approval_for: vec!["feedback".into(), "proposal".into()],
        max_inactivity_days: 30,
    }
}

fn arb_title() -> impl Strategy<Value = String> {
    "[A-Za-z0-9_ ]{1,40}".prop_map(|s| s.trim().to_string()).prop_filter("non-empty", |s| !s.is_empty())
}

fn arb_body() -> impl Strategy<Value = String> {
    "[A-Za-z0-9 ,.\n]{0,200}".prop_map(|s| {
        format!("**Why:** {}\n**How to apply:** {}", s, s)
    })
}

fn arb_tags() -> impl Strategy<Value = Vec<String>> {
    proptest::collection::vec("[a-z]{1,8}", 1..=4)
}

fn make_entity(
    user: &str,
    schema: &str,
    src: Source,
    title: String,
    body: String,
    tags: Vec<String>,
) -> NewEntity {
    NewEntity {
        schema: schema.into(),
        schema_version: 1,
        title: Some(title),
        description: None,
        body: Some(body),
        source: src,
        user_id: user.into(),
        session_id: None,
        llm_model: None,
        confidence: Some(0.5),
        requires_verification: false,
        scope_global: false,
        scope_user_ids: vec![user.into()],
        scope_project_ids: None,
        scope_patient_ids: vec![],
        tags,
        decay_ttl_days: None,
        decay_on_expire: None,
        initial_links: vec![],
    }
}

proptest! {
    /// SPEC §10.1: idempotency replay returns the same outcome regardless of
    /// how many times the same key is submitted.
    #[test]
    fn idempotency_replay_is_deterministic(
        title in arb_title(),
        body in arb_body(),
        tags in arb_tags(),
        n_replays in 1usize..=8,
    ) {
        let dir = tempfile::tempdir().unwrap();
        let fs = AimFs::open(dir.path()).unwrap();
        let user = Uuid::new_v4().to_string();
        let key = Uuid::new_v4().to_string();

        let outcomes: Vec<_> = (0..n_replays)
            .map(|_| {
                fs.propose(
                    &user,
                    make_entity(
                        &user,
                        "fact_v1",
                        Source::UserCommand,
                        title.clone(),
                        body.clone(),
                        tags.clone(),
                    ),
                    None,
                    Some(&key),
                    &pol(),
                )
            })
            .collect();

        // All n outcomes must be Ok and have the same entity_id + proposal_id.
        let first = outcomes
            .first()
            .unwrap()
            .as_ref()
            .ok()
            .cloned()
            .unwrap();
        for o in outcomes.iter() {
            let o = o.as_ref().ok().expect("idempotency must succeed");
            prop_assert_eq!(&o.entity_id, &first.entity_id);
            prop_assert_eq!(&o.proposal_id, &first.proposal_id);
        }
    }

    /// SPEC §4.4: double-approve must fail with BadTransition.
    #[test]
    fn double_approve_fails(
        title in arb_title(),
        body in arb_body(),
        tags in arb_tags(),
    ) {
        let dir = tempfile::tempdir().unwrap();
        let fs = AimFs::open(dir.path()).unwrap();
        let user = Uuid::new_v4().to_string();
        // Use feedback_v1 — in require_approval_for, so it stays pending.
        let outcome = fs
            .propose(
                &user,
                make_entity(
                    &user,
                    "feedback_v1",
                    Source::System,
                    title,
                    body,
                    tags,
                ),
                None,
                None,
                &pol(),
            )
            .unwrap();
        prop_assert_eq!(outcome.entity_status, EntityStatus::Pending);

        let actor = Actor { user_id: user.clone(), session_id: None };
        fs.approve_proposal(&user, &outcome.proposal_id, &actor)
            .expect("first approve must succeed");
        let res = fs.approve_proposal(&user, &outcome.proposal_id, &actor);
        prop_assert!(res.is_err(), "second approve must fail (got {res:?})");
    }

    /// SPEC §6 + §8: a `contradicts` link to an active entity makes BOTH
    /// disputed atomically — no transient state where only one is.
    #[test]
    fn contradicts_disputes_both(
        title_a in arb_title(),
        title_b in arb_title(),
        body in arb_body(),
        tags in arb_tags(),
    ) {
        let dir = tempfile::tempdir().unwrap();
        let fs = AimFs::open(dir.path()).unwrap();
        let user = Uuid::new_v4().to_string();
        let a = fs
            .propose(
                &user,
                make_entity(
                    &user,
                    "fact_v1",
                    Source::UserCommand,
                    title_a,
                    body.clone(),
                    tags.clone(),
                ),
                None,
                None,
                &pol(),
            )
            .unwrap();
        let mut b_entity = make_entity(
            &user,
            "fact_v1",
            Source::UserCommand,
            title_b,
            body,
            tags,
        );
        b_entity.initial_links = vec![InitialLink {
            target_id: a.entity_id.clone(),
            link_type: LinkType::Contradicts,
        }];
        let b = fs.propose(&user, b_entity, None, None, &pol()).unwrap();

        prop_assert_eq!(b.entity_status, EntityStatus::Disputed);
        let a_now = fs.get_entity(&user, &a.entity_id).unwrap();
        prop_assert_eq!(a_now.status, EntityStatus::Disputed);
    }

    /// SPEC §7: sweeper does NOT touch active entities without a TTL.
    #[test]
    fn sweeper_preserves_no_ttl_actives(
        title in arb_title(),
        body in arb_body(),
        tags in arb_tags(),
    ) {
        let dir = tempfile::tempdir().unwrap();
        let fs = AimFs::open(dir.path()).unwrap();
        let user = Uuid::new_v4().to_string();
        let mut entity = make_entity(
            &user,
            "fact_v1",
            Source::UserCommand,
            title,
            body,
            tags,
        );
        entity.decay_ttl_days = None;
        let outcome = fs.propose(&user, entity, None, None, &pol()).unwrap();
        prop_assert_eq!(outcome.entity_status, EntityStatus::Active);

        let pool = aim_fs::db::open_pool(
            &dir.path().join("_service").join("db").join("aim_fs.db"),
        )
        .unwrap();
        let _ = aim_fs::sweeper::sweep_once(&pool).unwrap();

        let after = fs.get_entity(&user, &outcome.entity_id).unwrap();
        prop_assert_eq!(after.status, EntityStatus::Active);
    }

    /// browse: profile_view counts must equal the actual SQL counts. No drift
    /// between the aggregate API and direct queries.
    #[test]
    fn profile_counts_match_sql(
        title in arb_title(),
        body in arb_body(),
        tags in arb_tags(),
        n_facts in 0usize..=4,
        n_feedback in 0usize..=4,
    ) {
        let dir = tempfile::tempdir().unwrap();
        let fs = AimFs::open(dir.path()).unwrap();
        let user = Uuid::new_v4().to_string();

        for i in 0..n_facts {
            let mut e = make_entity(
                &user,
                "user_fact_v1",
                Source::UserCommand,
                format!("{title}-fact-{i}"),
                body.clone(),
                tags.clone(),
            );
            e.confidence = Some(0.99);
            fs.propose(&user, e, None, None, &pol()).unwrap();
        }
        for i in 0..n_feedback {
            // feedback is in require_approval_for → pending; bump to active.
            let e = make_entity(
                &user,
                "feedback_v1",
                Source::System,
                format!("{title}-fb-{i}"),
                body.clone(),
                tags.clone(),
            );
            let out = fs.propose(&user, e, None, None, &pol()).unwrap();
            let actor = Actor { user_id: user.clone(), session_id: None };
            fs.approve_proposal(&user, &out.proposal_id, &actor).unwrap();
        }

        let profile = fs.profile_view(&user).unwrap();
        prop_assert_eq!(profile.counts.user_facts, n_facts as u32);
        prop_assert_eq!(profile.counts.feedback_rules, n_feedback as u32);
    }

    /// browse: project_activity returns only entities scoped to the requested project,
    /// regardless of how many entities exist with other scopes.
    #[test]
    fn project_activity_scope_filter(
        title in arb_title(),
        body in arb_body(),
        tags in arb_tags(),
    ) {
        let dir = tempfile::tempdir().unwrap();
        let fs = AimFs::open(dir.path()).unwrap();
        let user = Uuid::new_v4().to_string();

        // Two entities — one scoped to `proj_a`, one to `proj_b`.
        let mut a = make_entity(
            &user,
            "fact_v1",
            Source::UserCommand,
            format!("{title}-a"),
            body.clone(),
            tags.clone(),
        );
        a.scope_project_ids = Some(vec!["proj_a".into()]);
        fs.propose(&user, a, None, None, &pol()).unwrap();
        let mut b = make_entity(
            &user,
            "fact_v1",
            Source::UserCommand,
            format!("{title}-b"),
            body,
            tags,
        );
        b.scope_project_ids = Some(vec!["proj_b".into()]);
        fs.propose(&user, b, None, None, &pol()).unwrap();

        let act_a = fs.project_activity(&user, "proj_a").unwrap();
        let act_b = fs.project_activity(&user, "proj_b").unwrap();
        prop_assert_eq!(act_a.entries.len(), 1);
        prop_assert_eq!(act_b.entries.len(), 1);
        prop_assert!(act_a.entries[0].title.as_deref().unwrap().ends_with("-a"));
        prop_assert!(act_b.entries[0].title.as_deref().unwrap().ends_with("-b"));
    }

    /// browse: entity_detail returns the same record regardless of how many
    /// times it's called, with link counts matching the actual links table.
    #[test]
    fn entity_detail_consistent_with_links(
        title in arb_title(),
        body in arb_body(),
        tags in arb_tags(),
    ) {
        let dir = tempfile::tempdir().unwrap();
        let fs = AimFs::open(dir.path()).unwrap();
        let user = Uuid::new_v4().to_string();

        let a = fs
            .propose(
                &user,
                make_entity(
                    &user,
                    "fact_v1",
                    Source::UserCommand,
                    title.clone(),
                    body.clone(),
                    tags.clone(),
                ),
                None,
                None,
                &pol(),
            )
            .unwrap();
        let mut b_ent = make_entity(
            &user,
            "fact_v1",
            Source::UserCommand,
            format!("{title}-derived"),
            body,
            tags,
        );
        b_ent.initial_links = vec![InitialLink {
            target_id: a.entity_id.clone(),
            link_type: LinkType::Refines,
        }];
        let b = fs.propose(&user, b_ent, None, None, &pol()).unwrap();

        let det1 = fs.entity_detail(&user, &a.entity_id).unwrap();
        let det2 = fs.entity_detail(&user, &a.entity_id).unwrap();
        prop_assert_eq!(det1.id, det2.id);
        prop_assert_eq!(det1.version, det2.version);
        prop_assert_eq!(det1.incoming_links.len(), 1);
        prop_assert_eq!(&det1.incoming_links[0].other_id, &b.entity_id);
        prop_assert_eq!(&det1.incoming_links[0].link_type, "refines");

        let det_b = fs.entity_detail(&user, &b.entity_id).unwrap();
        prop_assert_eq!(det_b.outgoing_links.len(), 1);
        prop_assert_eq!(&det_b.outgoing_links[0].other_id, &a.entity_id);
    }

    /// SPEC §5.2: search returns only entities matching the tenant scope.
    /// Tenants must NEVER see each other's hits.
    #[test]
    fn search_respects_tenant_isolation(
        title_a in arb_title(),
        title_b in arb_title(),
    ) {
        let dir = tempfile::tempdir().unwrap();
        let fs = AimFs::open(dir.path()).unwrap();
        let user_a = Uuid::new_v4().to_string();
        let user_b = Uuid::new_v4().to_string();

        let mut ea = make_entity(
            &user_a,
            "fact_v1",
            Source::UserCommand,
            title_a.clone(),
            "**Why:** a\n**How to apply:** a".into(),
            vec!["a".into()],
        );
        ea.scope_user_ids = vec![user_a.clone()];
        fs.propose(&user_a, ea, None, None, &pol()).unwrap();

        let mut eb = make_entity(
            &user_b,
            "fact_v1",
            Source::UserCommand,
            title_b.clone(),
            "**Why:** b\n**How to apply:** b".into(),
            vec!["b".into()],
        );
        eb.scope_user_ids = vec![user_b.clone()];
        fs.propose(&user_b, eb, None, None, &pol()).unwrap();

        let hits_a = fs.search(&user_a, "Why", &SearchScope::default(), 10).unwrap();
        let hits_b = fs.search(&user_b, "Why", &SearchScope::default(), 10).unwrap();
        // Each tenant sees exactly its own entity.
        prop_assert_eq!(hits_a.len(), 1);
        prop_assert_eq!(hits_b.len(), 1);
        prop_assert_ne!(&hits_a[0].id, &hits_b[0].id);
    }
}
