use aim_llm::ensemble;

#[test]
fn jaccard_identical_texts_one() {
    let a = "the quick brown fox jumps over the lazy dog";
    assert_eq!(ensemble::jaccard_for_test(a, a, 3), 1.0);
}

#[test]
fn jaccard_disjoint_texts_zero() {
    let a = "alpha beta gamma delta";
    let b = "one two three four five";
    let s = ensemble::jaccard_for_test(a, b, 2);
    assert!(s < 0.01, "expected ~0, got {s}");
}

#[test]
fn jaccard_partial_overlap() {
    let a = "the patient has chest pain and shortness of breath";
    let b = "patient reports chest pain shortness of breath dyspnea";
    let s = ensemble::jaccard_for_test(a, b, 2);
    assert!(s > 0.0 && s < 1.0, "expected partial overlap, got {s}");
}

#[test]
fn jaccard_short_texts_below_k() {
    // "a b" with k=5 → no shingles → both empty → 1.0 by convention
    assert_eq!(ensemble::jaccard_for_test("a b", "c d", 5), 1.0);
}
