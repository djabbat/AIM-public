"""tests/test_project_graph.py — RT1 (2026-05-03)."""
from __future__ import annotations

import textwrap

import pytest


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AIM_PROJECTS_DIR", str(tmp_path))
    import importlib, sys
    for m in ["agents.project_owner", "agents.project_graph"]:
        if m in sys.modules:
            importlib.reload(sys.modules[m])
    return tmp_path


def write_proj(setup, name, body):
    (setup / f"{name}.yaml").write_text(textwrap.dedent(body), encoding="utf-8")


# ── explicit depends_on ──────────────────────────────────────────


def test_explicit_depends_on(isolated):
    write_proj(isolated, "FCLC", """
        name: FCLC
        depends_on: [CDATA, Ze]
    """)
    write_proj(isolated, "CDATA", "name: CDATA\n")
    write_proj(isolated, "Ze", "name: Ze\n")
    from agents.project_graph import build
    g = build()
    edge_pairs = [(e.src, e.dst, e.kind) for e in g.edges]
    assert ("FCLC", "CDATA", "explicit") in edge_pairs
    assert ("FCLC", "Ze",    "explicit") in edge_pairs


def test_explicit_skips_unknown_target(isolated):
    write_proj(isolated, "P", """
        name: P
        depends_on: [Ghost]
    """)
    from agents.project_graph import build
    g = build()
    assert g.edges == []


def test_explicit_skips_self_reference(isolated):
    write_proj(isolated, "P", """
        name: P
        depends_on: [P]
    """)
    from agents.project_graph import build
    g = build()
    assert g.edges == []


# ── soft refs in milestone blockers ──────────────────────────────


def test_blocker_creates_soft_edge(isolated):
    write_proj(isolated, "FCLC", """
        name: FCLC
        milestones:
          - id: m1
            blockers:
              - "Waiting on CDATA Sobol analysis"
    """)
    write_proj(isolated, "CDATA", "name: CDATA\n")
    from agents.project_graph import build
    g = build()
    edge_kinds = {(e.src, e.dst): e.kind for e in g.edges}
    assert edge_kinds.get(("FCLC", "CDATA")) == "blocker"


def test_goal_creates_soft_edge(isolated):
    write_proj(isolated, "P", """
        name: P
        goals:
          - "Integrate with MCOA framework"
    """)
    write_proj(isolated, "MCOA", "name: MCOA\n")
    from agents.project_graph import build
    g = build()
    assert any(e.dst == "MCOA" and e.kind == "goal" for e in g.edges)


def test_note_creates_soft_edge(isolated):
    write_proj(isolated, "P", """
        name: P
        stakeholders:
          - name: X
            role: r
            notes: "Coordinates Ze theory development"
    """)
    write_proj(isolated, "Ze", "name: Ze\n")
    from agents.project_graph import build
    g = build()
    assert any(e.dst == "Ze" and e.kind == "note" for e in g.edges)


# ── priority ordering ───────────────────────────────────────────


def test_explicit_beats_soft(isolated):
    """When same edge appears via depends_on AND blocker, keep explicit."""
    write_proj(isolated, "FCLC", """
        name: FCLC
        depends_on: [CDATA]
        milestones:
          - id: m
            blockers:
              - "CDATA work pending"
    """)
    write_proj(isolated, "CDATA", "name: CDATA\n")
    from agents.project_graph import build
    g = build()
    fclc_to_cdata = [e for e in g.edges
                      if e.src == "FCLC" and e.dst == "CDATA"]
    assert len(fclc_to_cdata) == 1
    assert fclc_to_cdata[0].kind == "explicit"


# ── renderers ───────────────────────────────────────────────────


def test_dot_format(isolated):
    write_proj(isolated, "A", "name: A\ndepends_on: [B]\n")
    write_proj(isolated, "B", "name: B\n")
    from agents.project_graph import dot
    out = dot()
    assert out.startswith("digraph")
    assert '"A" -> "B"' in out
    assert "[style=solid" in out


def test_mermaid_format(isolated):
    write_proj(isolated, "A", "name: A\ndepends_on: [B]\n")
    write_proj(isolated, "B", "name: B\n")
    from agents.project_graph import mermaid
    out = mermaid()
    assert "```mermaid" in out
    assert "graph TD" in out
    assert "A -->|explicit| B" in out


def test_adjacency_dict(isolated):
    write_proj(isolated, "A", "name: A\ndepends_on: [B, C]\n")
    write_proj(isolated, "B", "name: B\n")
    write_proj(isolated, "C", "name: C\n")
    from agents.project_graph import adjacency
    adj = adjacency()
    targets = {t for t, _kind in adj.get("A", [])}
    assert targets == {"B", "C"}


# ── cycle detection ──────────────────────────────────────────────


def test_no_cycles_when_dag(isolated):
    write_proj(isolated, "A", "name: A\ndepends_on: [B]\n")
    write_proj(isolated, "B", "name: B\ndepends_on: [C]\n")
    write_proj(isolated, "C", "name: C\n")
    from agents.project_graph import cycles
    assert cycles() == []


def test_cycle_detected(isolated):
    write_proj(isolated, "A", "name: A\ndepends_on: [B]\n")
    write_proj(isolated, "B", "name: B\ndepends_on: [A]\n")
    from agents.project_graph import cycles
    out = cycles()
    assert any({"A", "B"}.issubset(set(c)) for c in out)


def test_long_cycle_detected(isolated):
    write_proj(isolated, "A", "name: A\ndepends_on: [B]\n")
    write_proj(isolated, "B", "name: B\ndepends_on: [C]\n")
    write_proj(isolated, "C", "name: C\ndepends_on: [A]\n")
    from agents.project_graph import cycles
    out = cycles()
    assert any({"A", "B", "C"}.issubset(set(c)) for c in out)


# ── empty / edge cases ──────────────────────────────────────────


def test_no_projects_returns_empty(isolated):
    from agents.project_graph import build
    g = build()
    assert g.projects == []
    assert g.edges == []


def test_yaml_parse_failure_skipped(isolated):
    write_proj(isolated, "broken", "- not a mapping\n")
    write_proj(isolated, "good", "name: good\n")
    from agents.project_graph import build
    g = build()
    assert "good" in g.projects
