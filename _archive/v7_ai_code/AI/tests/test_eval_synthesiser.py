"""AI/tests/test_eval_synthesiser.py — S8 (2026-05-03)."""
from __future__ import annotations

import datetime as dt
import json
import textwrap

import pytest


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_SYNTH_CASES_DIR", str(tmp_path / "cases"))
    monkeypatch.setenv("AIM_HOME", str(tmp_path / "home"))
    import importlib, sys
    if "AI.ai.eval_synthesiser" in sys.modules:
        importlib.reload(sys.modules["AI.ai.eval_synthesiser"])
    return tmp_path


def _finding(kind, support=5, **sample):
    """Quick stand-in for pattern_miner.Finding."""
    from agents.pattern_miner import Finding
    return Finding(kind=kind, summary=f"{kind} test", support=support,
                   sample=sample)


# ── slug helper ──────────────────────────────────────────────────


def test_slug_lowercases_and_dashes(isolated):
    from AI.ai.eval_synthesiser import _slug
    assert _slug("read_file") == "read-file"
    assert _slug("FOO BAR baz") == "foo-bar-baz"


def test_slug_truncates(isolated):
    from AI.ai.eval_synthesiser import _slug
    out = _slug("a" * 100, max_len=10)
    assert len(out) == 10


# ── _from_finding: per-kind translation ─────────────────────────


def test_from_finding_tool_failure(isolated):
    from AI.ai.eval_synthesiser import _from_finding
    spec = _from_finding(_finding("tool_failure_rate", tool="bash"))
    assert spec is not None
    assert "ERROR:" in spec.rubrics["forbids"]
    assert "bash" in spec.task
    assert "tool_failure" in spec.tags


def test_from_finding_slow_tool(isolated):
    from AI.ai.eval_synthesiser import _from_finding
    spec = _from_finding(_finding("slow_tool", name="memory_recall"))
    assert spec is not None
    assert spec.rubrics["max_length"] == 1200
    assert "memory_recall" in spec.task


def test_from_finding_error_freq(isolated):
    from AI.ai.eval_synthesiser import _from_finding
    spec = _from_finding(_finding("error_type_frequency",
                                    prefix="ERROR:PERMISSION:bash"))
    assert spec is not None
    assert "ERROR:PERMISSION:bash" in spec.rubrics["forbids"]


def test_from_finding_sequential_pair(isolated):
    from AI.ai.eval_synthesiser import _from_finding
    spec = _from_finding(_finding("sequential_pair",
                                    a="read_file", b="edit_file"))
    assert spec is not None
    assert set(spec.rubrics["contains_all"]) == {"read_file", "edit_file"}


def test_from_finding_pair_missing_args_returns_none(isolated):
    from AI.ai.eval_synthesiser import _from_finding
    spec = _from_finding(_finding("sequential_pair", a="", b=""))
    assert spec is None


def test_from_finding_redundant_memory(isolated):
    from AI.ai.eval_synthesiser import _from_finding
    spec = _from_finding(_finding("redundant_memory_query"))
    assert spec is not None
    assert "recall" in spec.rubrics["forbids"]


def test_from_finding_unknown_kind(isolated):
    from AI.ai.eval_synthesiser import _from_finding
    spec = _from_finding(_finding("ghost_kind"))
    assert spec is None


# ── reflexion → CaseSpec ───────────────────────────────────────


def test_reflexion_extracts_keyterms(isolated):
    from AI.ai.eval_synthesiser import synthesise_from_reflexion
    spec = synthesise_from_reflexion(
        "Always cite real PubMed PMIDs; never fabricate DOI numbers.")
    assert spec is not None
    assert any(term in spec.rubrics["contains_all"]
               for term in ("PubMed", "fabricate", "PMIDs"))


def test_reflexion_too_short(isolated):
    from AI.ai.eval_synthesiser import synthesise_from_reflexion
    assert synthesise_from_reflexion("nope") is None


def test_reflexion_drops_filler_only(isolated):
    from AI.ai.eval_synthesiser import synthesise_from_reflexion
    spec = synthesise_from_reflexion("the and for with that this from they")
    # Even if length passes, filler-only string yields no terms.
    assert spec is None


# ── YAML emission ───────────────────────────────────────────────


def test_to_yaml_round_trips(isolated):
    import yaml
    from AI.ai.eval_synthesiser import _from_finding
    spec = _from_finding(_finding("tool_failure_rate", tool="bash"))
    text = spec.to_yaml()
    parsed = yaml.safe_load(text)
    assert parsed["id"] == spec.id
    assert parsed["task"].startswith("You must complete a task")
    assert parsed["rubrics"]["min_length"] == 40


# ── synthesise() — full pipeline ────────────────────────────────


def test_synthesise_writes_yaml_files(isolated):
    from AI.ai.eval_synthesiser import synthesise
    findings = [
        _finding("tool_failure_rate", tool="bash"),
        _finding("slow_tool", name="memory_recall"),
    ]
    written = synthesise(pattern_findings=findings, reflexions=[])
    assert len(written) == 2
    for p in written:
        assert p.exists()
        text = p.read_text()
        assert text.startswith("id:")


def test_synthesise_dry_run_persists_nothing(isolated):
    from AI.ai.eval_synthesiser import synthesise
    findings = [_finding("tool_failure_rate", tool="bash")]
    written = synthesise(pattern_findings=findings, reflexions=[],
                          dry_run=True)
    assert len(written) == 1
    assert not written[0].exists()


def test_synthesise_dedupes_by_id(isolated):
    from AI.ai.eval_synthesiser import synthesise
    findings = [
        _finding("tool_failure_rate", tool="bash"),
        _finding("tool_failure_rate", tool="bash"),  # duplicate
    ]
    written = synthesise(pattern_findings=findings, reflexions=[])
    assert len(written) == 1


def test_synthesise_combines_findings_and_reflexions(isolated):
    from AI.ai.eval_synthesiser import synthesise
    findings = [_finding("slow_tool", name="grep")]
    reflexions = [
        "Always verify PubMed PMIDs against the API; never fabricate."]
    written = synthesise(pattern_findings=findings, reflexions=reflexions)
    assert len(written) == 2


def test_synthesise_no_inputs_yields_nothing(isolated):
    from AI.ai.eval_synthesiser import synthesise
    assert synthesise(pattern_findings=[], reflexions=[]) == []


def test_synthesise_audit_log(isolated):
    from AI.ai.eval_synthesiser import synthesise, audit
    synthesise(pattern_findings=[_finding("slow_tool", name="g")],
                reflexions=[])
    h = audit()
    assert h and h[-1]["case_id"].startswith("auto-slow-")


# ── reflexion file scanner (real fs layout) ─────────────────────


def test_gather_reflexions_skips_old(isolated, tmp_path, monkeypatch):
    mem = tmp_path / ".claude" / "projects" / "-home-oem" / "memory"
    mem.mkdir(parents=True)
    new = mem / "feedback_new.md"
    old = mem / "feedback_old.md"
    new.write_text("Always verify PubMed PMIDs against the API.")
    old.write_text("Old guidance from forever ago.")
    import os, time
    o = time.time() - 365 * 24 * 3600
    os.utime(old, (o, o))
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    import importlib, AI.ai.eval_synthesiser as es
    importlib.reload(es)
    out = es._gather_reflexion_texts(window_days=30)
    assert any("PubMed" in t for t in out)
    assert not any("forever ago" in t for t in out)


def test_gather_reflexions_strips_frontmatter(isolated, tmp_path,
                                                monkeypatch):
    mem = tmp_path / ".claude" / "projects" / "-home-oem" / "memory"
    mem.mkdir(parents=True)
    (mem / "feedback_x.md").write_text(textwrap.dedent("""
        ---
        type: feedback
        ---
        Verify each citation against PubMed before emitting.
    """).lstrip())
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    import importlib, AI.ai.eval_synthesiser as es
    importlib.reload(es)
    out = es._gather_reflexion_texts(window_days=999)
    assert out and "Verify each citation" in out[0]
    assert "type: feedback" not in out[0]


# ── CLI smoke ───────────────────────────────────────────────────


def test_main_dry_run(isolated, monkeypatch, capsys):
    from agents import pattern_miner as pm
    monkeypatch.setattr(pm, "mine",
                        lambda window_days=7: [
                            _finding("tool_failure_rate", tool="bash")])
    import sys
    monkeypatch.setattr(sys, "argv", ["es", "--dry-run"])
    from AI.ai.eval_synthesiser import _main
    _main()
    out = capsys.readouterr().out
    assert "synthesised" in out


# ── CRIT-1 fix: L_VERIFIABILITY gate ─────────────────────────────


def test_persist_blocks_case_with_pmid(isolated):
    """Auto-generated case containing PMID must NOT be persisted."""
    from AI.ai.eval_synthesiser import (
        CaseSpec, _verify_no_fabricated_citations, _persist,
    )
    spec = CaseSpec(
        id="auto-bad", task="Verify PMID: 99999 against PubMed",
        rubrics={"min_length": 10}, tags=["auto"], source="test",
    )
    err = _verify_no_fabricated_citations(spec)
    assert err is not None
    assert "99999" in err or "pmid" in err.lower()
    target = _persist(spec, dry_run=False)
    assert target is None
    cases = list((isolated / "cases").glob("auto-bad*"))
    assert cases == []


def test_persist_blocks_case_with_doi(isolated):
    from AI.ai.eval_synthesiser import CaseSpec, _persist
    spec = CaseSpec(
        id="auto-doi", task="cite 10.1234/foo.bar to support",
        rubrics={"min_length": 10}, tags=["auto"], source="test",
    )
    assert _persist(spec, dry_run=False) is None


def test_persist_allows_clean_case(isolated):
    from AI.ai.eval_synthesiser import CaseSpec, _persist
    spec = CaseSpec(
        id="auto-clean", task="No citations here, just plain text.",
        rubrics={"contains_any": ["plain", "text"]},
        tags=["auto"], source="test",
    )
    target = _persist(spec, dry_run=False)
    assert target is not None
    assert target.exists()


def test_synthesise_skips_polluted_findings(isolated, monkeypatch):
    from AI.ai.eval_synthesiser import synthesise, CaseSpec
    import AI.ai.eval_synthesiser as es

    def evil_from_finding(_f):
        return CaseSpec(
            id="auto-evil", task="Cite PMID: 99999 in your answer",
            rubrics={"min_length": 5}, tags=["auto"], source="test",
        )

    monkeypatch.setattr(es, "_from_finding", evil_from_finding)
    out = synthesise(pattern_findings=[object()], reflexions=[],
                      dry_run=False)
    assert out == []   # blocked by L_VERIFIABILITY


def test_verify_skips_when_citation_guard_missing(isolated):
    """If agents.citation_guard can't be imported, gate is permissive."""
    import sys
    sys.modules["agents.citation_guard"] = type(sys)("agents.citation_guard")
    try:
        from AI.ai.eval_synthesiser import (
            CaseSpec, _verify_no_fabricated_citations,
        )
        spec = CaseSpec(id="auto-x", task="PMID: 12345",
                         rubrics={}, tags=[], source="test")
        assert _verify_no_fabricated_citations(spec) is None
    finally:
        sys.modules.pop("agents.citation_guard", None)
