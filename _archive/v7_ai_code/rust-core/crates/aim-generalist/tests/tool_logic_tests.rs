use aim_generalist::tools::sandbox;
use serial_test::serial;

fn setup_root() -> tempdir::TempDir {
    let dir = tempdir::TempDir::new("aim-tools").unwrap();
    std::env::set_var("AIM_GENERALIST_ROOT", dir.path());
    dir
}

#[test]
#[serial(env_root)]
fn sandbox_allows_nested_files() {
    let dir = setup_root();
    let nested = dir.path().join("a/b/c.md");
    std::fs::create_dir_all(nested.parent().unwrap()).unwrap();
    std::fs::write(&nested, "x").unwrap();
    assert!(sandbox::validate(nested.to_str().unwrap(), true).is_ok());
}

#[test]
#[serial(env_root)]
fn sandbox_blocks_symlink_escape() {
    let dir = setup_root();
    let outside = std::env::temp_dir().join(format!("aim-symlink-{}", uuid::Uuid::new_v4()));
    std::fs::write(&outside, "secret").unwrap();
    let link = dir.path().join("escape.md");
    let _ = std::os::unix::fs::symlink(&outside, &link);
    let r = sandbox::validate(link.to_str().unwrap(), true);
    assert!(r.is_err(), "symlink escape must be blocked: {r:?}");
    let _ = std::fs::remove_file(&outside);
}

#[test]
fn truncate_at_char_arabic() {
    let s = "العربية".repeat(100);
    let truncated = sandbox::truncate_at_char(&s, 25);
    assert!(s.starts_with(truncated));
    assert!(std::str::from_utf8(truncated.as_bytes()).is_ok());
}

#[test]
fn truncate_at_char_chinese() {
    let s = "你好世界".repeat(100);
    let truncated = sandbox::truncate_at_char(&s, 13);
    assert!(s.starts_with(truncated));
}

#[test]
fn truncate_at_char_zero() {
    let truncated = sandbox::truncate_at_char("hello", 0);
    assert_eq!(truncated, "");
}
