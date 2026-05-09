//! Mock-server tests for verify_pmid / verify_doi / search_pubmed.
//! Use mockito to simulate PubMed and Crossref endpoints.

use aim_generalist::tools::*;
use serde_json::json;
use serial_test::serial;

// We can't override the URL in the tool itself (it's hard-coded).
// So this suite exercises validation paths that don't require network.

mod via_tool {
    use super::*;
    use aim_generalist::tools;

    fn build_registry() -> tools::Registry {
        tools::Registry::with_defaults()
    }

    #[tokio::test]
    async fn verify_pmid_rejects_non_numeric() {
        let r = build_registry();
        let call = tools::ToolCall {
            name: "verify_pmid".into(),
            args: json!({ "pmid": "abc-not-numeric" }),
        };
        match r.dispatch(&call).await {
            tools::ToolResult::Err(e) => assert!(e.contains("not a numeric"),
                "expected validation error, got: {e}"),
            tools::ToolResult::Ok(o) => panic!("should have errored, got: {o}"),
        }
    }

    #[tokio::test]
    async fn verify_doi_rejects_no_slash() {
        let r = build_registry();
        let call = tools::ToolCall {
            name: "verify_doi".into(),
            args: json!({ "doi": "10no_slash_here" }),
        };
        match r.dispatch(&call).await {
            tools::ToolResult::Err(e) => assert!(e.contains("not a DOI"),
                "expected validation error, got: {e}"),
            tools::ToolResult::Ok(o) => panic!("should have errored, got: {o}"),
        }
    }

    #[tokio::test]
    async fn verify_pmid_strips_prefix() {
        // "PMID:abc" should still fail because it's non-numeric, but the prefix
        // should be stripped before validation.
        let r = build_registry();
        let call = tools::ToolCall {
            name: "verify_pmid".into(),
            args: json!({ "pmid": "PMID:foo" }),
        };
        match r.dispatch(&call).await {
            tools::ToolResult::Err(e) => assert!(e.contains("not a numeric PMID: foo"),
                "stripped check missed: {e}"),
            tools::ToolResult::Ok(_) => panic!("should have errored"),
        }
    }

    #[tokio::test]
    async fn verify_doi_strips_url_prefix() {
        let r = build_registry();
        let call = tools::ToolCall {
            name: "verify_doi".into(),
            args: json!({ "doi": "https://doi.org/no_slash" }),
        };
        match r.dispatch(&call).await {
            tools::ToolResult::Err(e) => assert!(e.contains("not a DOI: no_slash"),
                "url prefix stripping wrong: {e}"),
            tools::ToolResult::Ok(_) => panic!("should have errored"),
        }
    }

    #[tokio::test]
    #[serial(env_root)]
    async fn unknown_tool_returns_err() {
        let r = build_registry();
        let call = tools::ToolCall {
            name: "totally_unknown".into(),
            args: json!({}),
        };
        match r.dispatch(&call).await {
            tools::ToolResult::Err(e) => assert!(e.contains("unknown tool")),
            tools::ToolResult::Ok(_) => panic!("expected unknown tool error"),
        }
    }
}
