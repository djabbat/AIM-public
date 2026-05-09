"""AI/tests/test_reflexion_cluster.py — S10 (2026-05-03)."""
from __future__ import annotations

import textwrap

import pytest


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AIM_HOME", str(tmp_path / "home"))
    import importlib, sys
    if "AI.ai.reflexion_cluster" in sys.modules:
        importlib.reload(sys.modules["AI.ai.reflexion_cluster"])
    return tmp_path


# ── tokenisation ────────────────────────────────────────────────


# ── cluster() ────────────────────────────────────────────────────


def test_cluster_groups_similar(isolated):
    from AI.ai.reflexion_cluster import cluster
    notes = [
        "Always verify PubMed PMIDs against the API; never fabricate.",
        "Verify each PubMed citation before emitting; PMIDs must resolve.",
        "Watch out for fabricated DOI numbers in scientific writing.",
        "Use bash sandbox; never call python -c with arbitrary code.",
    ]
    out = cluster(notes, threshold=0.2)
    # The first three are about citations; the fourth is about bash.
    assert any(c.n >= 2 for c in out)
    big = max(out, key=lambda c: c.n)
    assert any("pubmed" in t for t in big.theme) or \
           any("verify" in t for t in big.theme) or \
           any("citation" in t.lower() for t in big.theme)


def test_cluster_distinct_themes_separate(isolated):
    from AI.ai.reflexion_cluster import cluster
    notes = [
        "Always verify PubMed citations before emitting.",
        "Drug interactions: never combine warfarin with aspirin.",
    ]
    out = cluster(notes, threshold=0.5)
    assert len(out) == 2


def test_cluster_drops_too_short(isolated):
    from AI.ai.reflexion_cluster import cluster
    out = cluster(["short", "x"])
    assert out == []


def test_cluster_drops_non_strings(isolated):
    from AI.ai.reflexion_cluster import cluster
    out = cluster([123, None, "Always verify PubMed citations carefully"])
    assert len(out) == 1
    assert out[0].n == 1


def test_cluster_orders_by_size(isolated):
    from AI.ai.reflexion_cluster import cluster
    notes = (
        ["citations PubMed PMID DOI verify"] * 4
        + ["regimen warfarin aspirin contraindicated avoid"] * 2
    )
    out = cluster(notes, threshold=0.3)
    assert out[0].n >= out[-1].n


# ── theme extraction ────────────────────────────────────────────


def test_theme_picks_shared_terms(isolated):
    from AI.ai.reflexion_cluster import cluster
    notes = [
        "verify pubmed citations always before publishing",
        "verify pubmed pmid before each grant submission",
        "always verify pubmed when writing a paper",
    ]
    out = cluster(notes, threshold=0.3)
    big = out[0]
    assert big.n == 3
    assert "verify" in big.theme
    assert "pubmed" in big.theme


def test_suggestion_uses_theme(isolated):
    from AI.ai.reflexion_cluster import cluster
    notes = ["verify pubmed citations always", "verify pubmed pmid lists"]
    out = cluster(notes, threshold=0.3)
    s = out[0].suggestion
    assert "Remember" in s
    assert "verify" in s.lower() or "pubmed" in s.lower()


def test_suggestion_falls_back_when_no_theme(isolated):
    from AI.ai.reflexion_cluster import Cluster
    c = Cluster(notes=["x" * 30], theme=[], representative="x" * 30)
    assert c.suggestion.startswith("x")


# ── memory pull ──────────────────────────────────────────────────


def test_clusters_from_memory_pulls_feedback_notes(isolated, monkeypatch):
    """Patch the inner pullers directly — robust against Path.home() quirks."""
    import AI.ai.reflexion_cluster as rc
    monkeypatch.setattr(rc, "_from_feedback_memory",
                        lambda window_days=180: [
                            "Always verify PubMed citations before emitting.",
                            "Verify PubMed PMIDs against the API.",
                        ])
    monkeypatch.setattr(rc, "_from_reflexion_buckets",
                        lambda n_per_bucket=8: [])
    out = rc.clusters_from_memory(window_days=999, threshold=0.2)
    assert any(c.n >= 2 for c in out)


def test_clusters_from_memory_includes_reflexion_buckets(isolated,
                                                          monkeypatch):
    import AI.ai.reflexion_cluster as rc
    monkeypatch.setattr(rc, "_from_feedback_memory",
                        lambda window_days=180: [])
    monkeypatch.setattr(rc, "_from_reflexion_buckets",
                        lambda n_per_bucket=8: [
                            "Verify each PubMed citation carefully before emit",
                            "Always verify PubMed PMIDs through API not LLM",
                        ])
    out = rc.clusters_from_memory(threshold=0.2)
    assert any(c.n >= 2 for c in out)


# ── summary ──────────────────────────────────────────────────────


def test_summary_calm_when_empty(isolated, monkeypatch):
    import AI.ai.reflexion_cluster as rc
    monkeypatch.setattr(rc, "clusters_from_memory",
                        lambda window_days=180, threshold=0.25: [])
    assert "no reflexions" in rc.summary()


def test_summary_renders_clusters(isolated, monkeypatch):
    from AI.ai.reflexion_cluster import Cluster
    import AI.ai.reflexion_cluster as rc
    monkeypatch.setattr(rc, "clusters_from_memory",
                        lambda window_days=180, threshold=0.25: [
                            Cluster(notes=["a"]*3,
                                     theme=["verify", "pubmed"],
                                     representative="verify pubmed always")])
    s = rc.summary()
    assert "Reflexion clusters" in s
    assert "verify" in s
