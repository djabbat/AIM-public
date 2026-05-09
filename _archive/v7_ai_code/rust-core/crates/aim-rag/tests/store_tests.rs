use aim_rag::store::Store;

fn tmpdb() -> String {
    let dir = std::env::temp_dir();
    let p = dir.join(format!("aim-rag-test-{}.db", uuid::Uuid::new_v4()));
    p.to_string_lossy().into_owned()
}

#[test]
fn upsert_and_search_identity() {
    let path = tmpdb();
    let s = Store::open(&path).unwrap();
    let v = vec![1.0, 0.0, 0.0];
    s.upsert("doc1", "hello", &v, None).unwrap();
    let res = s.search(&[1.0, 0.0, 0.0], 5).unwrap();
    assert_eq!(res.len(), 1);
    assert_eq!(res[0].0, "doc1");
    assert!((res[0].1 - 1.0).abs() < 1e-5, "identity cosine should be 1.0, got {}", res[0].1);
    let _ = std::fs::remove_file(&path);
}

#[test]
fn cosine_orthogonal() {
    let path = tmpdb();
    let s = Store::open(&path).unwrap();
    s.upsert("a", "x", &[1.0, 0.0, 0.0], None).unwrap();
    s.upsert("b", "y", &[0.0, 1.0, 0.0], None).unwrap();
    let res = s.search(&[1.0, 0.0, 0.0], 5).unwrap();
    let a = res.iter().find(|(id, _, _, _)| id == "a").unwrap();
    let b = res.iter().find(|(id, _, _, _)| id == "b").unwrap();
    assert!(a.1 > 0.99);
    assert!(b.1.abs() < 0.01);
    let _ = std::fs::remove_file(&path);
}

#[test]
fn upsert_overwrites() {
    let path = tmpdb();
    let s = Store::open(&path).unwrap();
    s.upsert("k", "first", &[1.0, 0.0], None).unwrap();
    s.upsert("k", "second", &[0.0, 1.0], None).unwrap();
    let res = s.search(&[0.0, 1.0], 5).unwrap();
    assert_eq!(res.len(), 1);
    assert_eq!(res[0].2, "second");
    let _ = std::fs::remove_file(&path);
}

#[test]
fn search_topk_ordering() {
    let path = tmpdb();
    let s = Store::open(&path).unwrap();
    for (i, w) in [0.1, 0.5, 0.9, 0.3].iter().enumerate() {
        s.upsert(&format!("d{i}"), "x", &[*w, (1.0 - w).abs()], None).unwrap();
    }
    let res = s.search(&[1.0, 0.0], 4).unwrap();
    // scores must be descending
    let scores: Vec<f32> = res.iter().map(|(_, s, _, _)| *s).collect();
    for w in scores.windows(2) {
        assert!(w[0] >= w[1], "scores not descending: {:?}", scores);
    }
    let _ = std::fs::remove_file(&path);
}

#[test]
fn dim_mismatch_skipped() {
    let path = tmpdb();
    let s = Store::open(&path).unwrap();
    s.upsert("a", "ok", &[1.0, 0.0, 0.0], None).unwrap();
    s.upsert("b", "wrong dim", &[1.0, 0.0], None).unwrap();
    let res = s.search(&[1.0, 0.0, 0.0], 5).unwrap();
    // Only 'a' has matching dim.
    assert_eq!(res.len(), 1);
    assert_eq!(res[0].0, "a");
    let _ = std::fs::remove_file(&path);
}
