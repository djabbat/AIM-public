use aim_doctor::extract_json;

#[test]
fn pure_json_passes_through() {
    let v = extract_json(r#"{"a":1}"#).unwrap();
    assert_eq!(v["a"], 1);
}

#[test]
fn extracts_from_markdown_fences() {
    let s = "Here you go:\n```json\n{\"chief_complaint\":\"chest pain\"}\n```\nHope that helps.";
    let v = extract_json(s).unwrap();
    assert_eq!(v["chief_complaint"], "chest pain");
}

#[test]
fn picks_largest_when_two_objects() {
    let s = r#"{"a":1} and {"chief_complaint":"x","red_flags":["a","b"]}"#;
    let v = extract_json(s).unwrap();
    // largest substring is the second one
    assert!(v.get("chief_complaint").is_some());
}

#[test]
fn returns_none_on_no_json() {
    assert!(extract_json("just plain text").is_none());
}

#[test]
fn handles_nested_objects() {
    let s = r#"prose {"outer":{"inner":42}} more prose"#;
    let v = extract_json(s).unwrap();
    assert_eq!(v["outer"]["inner"], 42);
}
