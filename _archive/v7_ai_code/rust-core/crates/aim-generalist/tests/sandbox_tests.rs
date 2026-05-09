use aim_generalist::tools::sandbox;
use serial_test::serial;

fn setup_root() -> tempdir::TempDir {
    let dir = tempdir::TempDir::new("aim-sandbox").unwrap();
    std::env::set_var("AIM_GENERALIST_ROOT", dir.path());
    dir
}

#[test]
#[serial(env_root)]
fn rejects_path_outside_root() {
    let _root = setup_root();
    let r = sandbox::validate("/etc/passwd", true);
    assert!(r.is_err(), "must reject /etc/passwd");
}

#[test]
#[serial(env_root)]
fn rejects_traversal_via_dotdot() {
    let dir = setup_root();
    let inside = dir.path().join("real.txt");
    std::fs::write(&inside, "hi").unwrap();
    let r = sandbox::validate(
        &format!("{}/../../etc/passwd", dir.path().display()),
        false,
    );
    assert!(r.is_err(), "must reject ../ traversal");
}

#[test]
#[serial(env_root)]
fn accepts_path_inside_root() {
    let dir = setup_root();
    let f = dir.path().join("test.md");
    std::fs::write(&f, "data").unwrap();
    let r = sandbox::validate(f.to_str().unwrap(), true);
    assert!(r.is_ok(), "should accept in-root file: {:?}", r);
}

#[test]
#[serial(env_root)]
fn rejects_disallowed_extension() {
    let dir = setup_root();
    let f = dir.path().join("evil.sh");
    std::fs::write(&f, "#!/bin/sh\nrm -rf /\n").unwrap();
    let r = sandbox::validate(f.to_str().unwrap(), true);
    assert!(r.is_err(), "must reject .sh files");
}

#[test]
fn truncate_at_char_no_panic_on_multibyte() {
    let s = "ჩუმუჩი".repeat(20);
    for cut in [1, 3, 5, 7, 11, 50, s.len() - 1] {
        let truncated = sandbox::truncate_at_char(&s, cut);
        assert!(s.starts_with(truncated), "cut at {cut} broke prefix");
        assert!(std::str::from_utf8(truncated.as_bytes()).is_ok());
    }
}

#[test]
fn truncate_at_char_passes_short_strings() {
    let s = "hello";
    assert_eq!(sandbox::truncate_at_char(s, 100), "hello");
}
