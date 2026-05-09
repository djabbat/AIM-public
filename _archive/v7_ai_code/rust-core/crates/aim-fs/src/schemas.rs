//! Schema registry — implements SPEC §3.2.
//!
//! Each `schema` field on a `NewEntity` is dispatched to a validator that
//! checks structural requirements (title length, tag presence, mandatory body
//! fragments, scope rules, …) before the entity is committed.
//!
//! For MVP we use plain Rust validators rather than full JSON Schema; the
//! contract is the same (validate or reject) but avoids a new heavy dep.
//! Schemas can be migrated to `_schemas/<name>.json` files in a follow-up
//! without changing the call sites.

use crate::error::{AimFsError, Result};
use crate::types::{NewEntity, Source};

/// Validate a `NewEntity` before commit.  Unknown schemas are accepted (no
/// rules → trivially pass) so existing imports keep working; named schemas
/// enforce their required structure.
pub fn validate(new: &NewEntity) -> Result<()> {
    match new.schema.as_str() {
        "feedback_v1" => validate_feedback(new),
        "fact_v1" => validate_fact(new),
        "user_fact_v1" => validate_user_fact(new),
        "contact_v1" => validate_contact(new),
        "proposal_v1" => validate_proposal(new),
        "project_state_v1" => validate_project_state(new),
        "patient_anamnesis_v1" => validate_patient_anamnesis(new),
        "recipe_v1" => validate_recipe(new),
        "diagnosis_v1" => validate_diagnosis(new),
        // imported / unknown — pass through
        _ => Ok(()),
    }
}

fn need_title(new: &NewEntity) -> Result<()> {
    match new.title.as_deref() {
        Some(s) if !s.trim().is_empty() => Ok(()),
        _ => Err(AimFsError::SchemaInvalid(format!(
            "{} requires non-empty title",
            new.schema
        ))),
    }
}

fn validate_feedback(new: &NewEntity) -> Result<()> {
    need_title(new)?;
    if new.tags.is_empty() {
        return Err(AimFsError::SchemaInvalid(
            "feedback_v1 requires at least one tag".into(),
        ));
    }
    // Per memory rule format_scientific_paper / feedback structure: should hint at Why / How to apply.
    let body = new.body.as_deref().unwrap_or("");
    if !(body.contains("**Why:**")
        || body.contains("**How to apply:**")
        || body.contains("Why:")
        || body.contains("How to apply:"))
    {
        return Err(AimFsError::SchemaInvalid(
            "feedback_v1 body must contain `Why:` or `How to apply:` line".into(),
        ));
    }
    Ok(())
}

fn validate_fact(new: &NewEntity) -> Result<()> {
    need_title(new)?;
    Ok(())
}

fn validate_user_fact(new: &NewEntity) -> Result<()> {
    need_title(new)?;
    match new.source {
        Source::UserCommand | Source::UserMessage | Source::System => Ok(()),
    }
}

fn validate_contact(new: &NewEntity) -> Result<()> {
    need_title(new)?;
    if new.tags.iter().any(|t| t == "contact") || new.schema.starts_with("contact_") {
        Ok(())
    } else {
        Err(AimFsError::SchemaInvalid(
            "contact_v1 should be tagged 'contact' (or use schema starting with `contact_`)".into(),
        ))
    }
}

fn validate_proposal(new: &NewEntity) -> Result<()> {
    need_title(new)?;
    let body = new.body.as_deref().unwrap_or("");
    for required in ["## Что предлагаю", "## Доказательства", "## Риски"] {
        if !body.contains(required) {
            return Err(AimFsError::SchemaInvalid(format!(
                "proposal_v1 body missing section `{required}`"
            )));
        }
    }
    Ok(())
}

fn validate_project_state(new: &NewEntity) -> Result<()> {
    need_title(new)?;
    Ok(())
}

fn validate_patient_anamnesis(new: &NewEntity) -> Result<()> {
    need_title(new)?;
    if new.scope_patient_ids.is_empty() {
        return Err(AimFsError::SchemaInvalid(
            "patient_anamnesis_v1 requires non-empty scope.patient_ids".into(),
        ));
    }
    Ok(())
}

fn validate_recipe(new: &NewEntity) -> Result<()> {
    need_title(new)?;
    if new.scope_patient_ids.is_empty() {
        return Err(AimFsError::SchemaInvalid(
            "recipe_v1 must be scoped to at least one patient".into(),
        ));
    }
    let body = new.body.as_deref().unwrap_or("");
    // recipe_v1 must list explicit dose with a numeric value so the
    // doctor can audit what the AI agent prescribed.  We look for a
    // "Dose:" / "Доза:" line followed by digits within the same body.
    let needles = ["Dose:", "dose:", "Доза:", "доза:", "Доз:"];
    let has_kw = needles.iter().any(|n| body.contains(n));
    let has_digit_near_kw = body
        .lines()
        .any(|l| {
            needles.iter().any(|n| l.contains(n))
                && l.chars().any(|c| c.is_ascii_digit())
        });
    if !has_kw {
        return Err(AimFsError::SchemaInvalid(
            "recipe_v1 body must include `Dose:` / `Доза:` line".into(),
        ));
    }
    if !has_digit_near_kw {
        return Err(AimFsError::SchemaInvalid(
            "recipe_v1 dose line must include a numeric value".into(),
        ));
    }
    Ok(())
}

fn validate_diagnosis(new: &NewEntity) -> Result<()> {
    need_title(new)?;
    if new.scope_patient_ids.is_empty() {
        return Err(AimFsError::SchemaInvalid(
            "diagnosis_v1 must be scoped to a patient".into(),
        ));
    }
    let body = new.body.as_deref().unwrap_or("");
    if !(body.contains("Differential")
        || body.contains("Дифдиагноз")
        || body.contains("DDx")
        || body.contains("Working diagnosis"))
    {
        return Err(AimFsError::SchemaInvalid(
            "diagnosis_v1 body must include Differential / Дифдиагноз / DDx / Working diagnosis section".into(),
        ));
    }
    if new.confidence.is_none() {
        return Err(AimFsError::SchemaInvalid(
            "diagnosis_v1 must declare confidence (0..1) explicitly".into(),
        ));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::types::*;

    fn baseline(schema: &str, src: Source) -> NewEntity {
        NewEntity {
            schema: schema.into(),
            schema_version: 1,
            title: Some("title".into()),
            description: None,
            body: Some("**Why:** because\n**How to apply:** here".into()),
            source: src,
            user_id: "u".into(),
            session_id: None,
            llm_model: None,
            confidence: None,
            requires_verification: false,
            scope_global: false,
            scope_user_ids: vec![],
            scope_project_ids: None,
            scope_patient_ids: vec![],
            tags: vec!["a".into()],
            decay_ttl_days: None,
            decay_on_expire: None,
            initial_links: vec![],
        }
    }

    #[test]
    fn feedback_requires_why_section() {
        let mut e = baseline("feedback_v1", Source::UserCommand);
        e.body = Some("just a plain note".into());
        assert!(validate(&e).is_err());
    }

    #[test]
    fn feedback_requires_at_least_one_tag() {
        let mut e = baseline("feedback_v1", Source::UserCommand);
        e.tags.clear();
        assert!(validate(&e).is_err());
    }

    #[test]
    fn feedback_minimal_valid() {
        let e = baseline("feedback_v1", Source::UserCommand);
        validate(&e).unwrap();
    }

    #[test]
    fn recipe_requires_patient_scope() {
        let e = baseline("recipe_v1", Source::UserCommand);
        assert!(validate(&e).is_err());
    }

    #[test]
    fn unknown_schema_passes_through() {
        let e = baseline("imported_md_v1", Source::System);
        validate(&e).unwrap();
    }

    #[test]
    fn proposal_must_have_three_sections() {
        let mut e = baseline("proposal_v1", Source::UserCommand);
        e.body = Some("## Что предлагаю\nfoo".into());
        assert!(validate(&e).is_err());
        e.body = Some(
            "## Что предлагаю\n...\n## Доказательства\n...\n## Риски\n...".into(),
        );
        validate(&e).unwrap();
    }
}
