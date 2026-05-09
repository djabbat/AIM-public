//! apply_patch round-trip tests inside a sandboxed tempdir.

use aim_generalist::tools::{Registry, ToolCall, ToolResult};
use serde_json::json;
use serial_test::serial;

fn setup_root() -> tempdir::TempDir {
    let dir = tempdir::TempDir::new("aim-patch").unwrap();
    std::env::set_var("AIM_GENERALIST_ROOT", dir.path());
    dir
}

async fn run(name: &str, args: serde_json::Value) -> ToolResult {
    Registry::with_defaults().dispatch(&ToolCall { name: name.into(), args }).await
}

#[tokio::test]
#[serial(env_root)]
async fn missing_patch_arg() {
    let _root = setup_root();
    let res = run("apply_patch", json!({})).await;
    match res {
        ToolResult::Err(e) => assert!(e.contains("missing arg: patch")),
        ToolResult::Ok(_) => panic!("must require patch"),
    }
}

#[tokio::test]
#[serial(env_root)]
async fn create_new_file_must_have_underscore_prefix() {
    let dir = setup_root();
    let target = dir.path().join("plain.md"); // no underscore!
    let target_str = target.display().to_string();

    let patch = format!(
        "--- /dev/null\n+++ {target_str}\n@@ -0,0 +1,1 @@\n+hello\n"
    );
    let res = run("apply_patch", json!({ "patch": patch })).await;
    match res {
        ToolResult::Err(e) => assert!(e.contains("start with '_'"),
            "expected '_' guard error, got: {e}"),
        ToolResult::Ok(o) => panic!("must reject file without _ prefix: {o}"),
    }
}

#[tokio::test]
#[serial(env_root)]
async fn create_underscore_file_succeeds() {
    let dir = setup_root();
    let target = dir.path().join("_summary.md");
    let target_str = target.display().to_string();

    let patch = format!(
        "--- /dev/null\n+++ {target_str}\n@@ -0,0 +1,1 @@\n+hello world\n"
    );
    let res = run("apply_patch", json!({ "patch": patch })).await;
    match res {
        ToolResult::Ok(_) => {
            let content = std::fs::read_to_string(&target).unwrap();
            assert!(content.contains("hello world"), "unexpected content: {content}");
        }
        ToolResult::Err(e) => panic!("expected success, got: {e}"),
    }
}
