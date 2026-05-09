use aim_generalist::tools::kernel_check::evaluate;
use serde_json::json;

#[test]
fn ok_for_internal_action() {
    let b = evaluate("read_file", "anything", &json!({}));
    assert!(b.is_empty());
}

#[test]
fn l_consent_blocks_email_without_confirm() {
    let b = evaluate("email_send", "Hello", &json!({}));
    assert!(b.iter().any(|x| x.starts_with("L_CONSENT")));
}

#[test]
fn l_consent_passes_with_confirm() {
    let b = evaluate("email_send", "Hello", &json!({ "user_confirmed": true }));
    assert!(!b.iter().any(|x| x.starts_with("L_CONSENT")));
}

#[test]
fn l_privacy_blocks_patients_path() {
    let b = evaluate("email_send", "see /Patients/SMITH/MEMORY.md", &json!({ "user_confirmed": true }));
    assert!(b.iter().any(|x| x.starts_with("L_PRIVACY") && x.contains("Patients")));
}

#[test]
fn l_privacy_blocks_phone_pattern() {
    let b = evaluate("telegram_send", "call +995 555 185 161 today", &json!({}));
    assert!(b.iter().any(|x| x.contains("phone")));
}

#[test]
fn l_privacy_blocks_dob_pattern() {
    let b = evaluate("web_publish", "patient born 1985-07-12", &json!({ "user_confirmed": true }));
    assert!(b.iter().any(|x| x.contains("DOB")));
}

#[test]
fn l_privacy_passes_with_consent() {
    let ctx = json!({ "privacy_consent": true, "user_confirmed": true });
    let b = evaluate("email_send", "see /Patients/X/MEMORY.md", &ctx);
    assert!(!b.iter().any(|x| x.starts_with("L_PRIVACY")));
}

#[test]
fn l_verifiability_blocks_unmarked_doi() {
    let b = evaluate("email_send", "see DOI 10.3389/fphar.2024.12345",
                     &json!({ "user_confirmed": true }));
    assert!(b.iter().any(|x| x.starts_with("L_VERIFIABILITY")),
        "must flag bare DOI: {b:?}");
}

#[test]
fn l_verifiability_passes_with_marker() {
    let b = evaluate("email_send", "DOI:10.3389/fphar.2024 VERIFIED",
                     &json!({ "user_confirmed": true }));
    assert!(!b.iter().any(|x| x.contains("DOI present")));
}

#[test]
fn l_verifiability_flags_pmid_too_short() {
    let b = evaluate("web_publish", "see PMID:42",
                     &json!({ "user_confirmed": true }));
    assert!(b.iter().any(|x| x.contains("PMID 42 fails sanity check")));
}

#[test]
fn multiple_blockers_returned_together() {
    let b = evaluate("email_send",
        "send to /Patients/X with phone +995555185161 and DOI 10.1234/abc",
        &json!({}));
    assert!(b.len() >= 3, "expected ≥3 blockers, got {}: {b:?}", b.len());
}
