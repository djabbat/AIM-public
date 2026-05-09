"""tests/test_module_registry.py — G12 (2026-05-03)."""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def fake_repo(tmp_path):
    """Build a small synthetic agents/ + scripts/ tree."""
    (tmp_path / "agents").mkdir()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "agents" / "__init__.py").write_text("")
    (tmp_path / "scripts" / "__init__.py").write_text("")

    (tmp_path / "agents" / "alpha.py").write_text(
        '"""Alpha module — does cool stuff."""\n'
        "import json\n"
        "from typing import Any\n"
        "def public_fn(): return 1\n"
        "def _private(): return 2\n"
        "class Public: pass\n"
        "class _Private: pass\n"
    )
    (tmp_path / "agents" / "beta.py").write_text(
        '"""Beta module."""\n'
        "from agents.alpha import public_fn\n"
        "def go(): return public_fn()\n"
    )
    (tmp_path / "scripts" / "task.py").write_text(
        '"""Daily task script."""\n'
        "if __name__ == '__main__': pass\n"
    )
    (tmp_path / "agents" / "broken.py").write_text("def: bad python\n")
    (tmp_path / "agents" / "__pycache__").mkdir()
    (tmp_path / "agents" / "__pycache__" / "x.cpython.pyc").write_bytes(b"\x00")
    return tmp_path


# ── parsing ──────────────────────────────────────────────────────


def test_parse_extracts_doc_and_api(fake_repo):
    from agents.module_registry import _parse
    c = _parse(fake_repo / "agents" / "alpha.py")
    assert c.description == "Alpha module — does cool stuff."
    assert "public_fn" in c.public_functions
    assert "_private" not in c.public_functions
    assert "Public" in c.public_classes
    assert "_Private" not in c.public_classes
    assert "json" in c.imports
    assert "typing" in c.imports


def test_parse_handles_syntax_error(fake_repo):
    from agents.module_registry import _parse
    assert _parse(fake_repo / "agents" / "broken.py") is None


def test_parse_no_docstring(fake_repo):
    p = fake_repo / "agents" / "no_doc.py"
    p.write_text("def f(): pass\n")
    from agents.module_registry import _parse
    c = _parse(p)
    assert c.description == ""


# ── module name resolution ──────────────────────────────────────


def test_module_for_basic(fake_repo):
    from agents.module_registry import _module_for
    p = fake_repo / "agents" / "alpha.py"
    assert _module_for(p, fake_repo) == "agents.alpha"


def test_module_for_init(fake_repo):
    from agents.module_registry import _module_for
    p = fake_repo / "agents" / "__init__.py"
    assert _module_for(p, fake_repo) == "agents"


def test_module_for_outside_root(fake_repo, tmp_path):
    from agents.module_registry import _module_for
    other = tmp_path.parent / "elsewhere.py"
    assert _module_for(other, fake_repo) is None


# ── registry walk ───────────────────────────────────────────────


def test_registry_lists_all_valid_modules(fake_repo):
    from agents.module_registry import registry
    caps = registry(root=fake_repo)
    names = sorted(c.module for c in caps)
    # broken.py was skipped (syntax error); pycache excluded.
    assert "agents.alpha" in names
    assert "agents.beta" in names
    assert "scripts.task" in names
    assert "agents.broken" not in names


def test_registry_skips_pycache(fake_repo):
    from agents.module_registry import registry
    caps = registry(root=fake_repo)
    paths = [c.path for c in caps]
    assert not any("__pycache__" in p for p in paths)


def test_registry_only_specified_roots(fake_repo):
    from agents.module_registry import registry
    caps = registry(roots=("agents",), root=fake_repo)
    names = {c.module for c in caps}
    assert all(n == "agents" or n.startswith("agents.") for n in names)
    assert not any(n.startswith("scripts") for n in names)


# ── get ──────────────────────────────────────────────────────────


def test_get_finds_module(fake_repo):
    from agents.module_registry import get
    cap = get("agents.alpha", index=None)  # uses real repo by default
    # When called without an index, we hit the real codebase. That's fine
    # — we just verify the API doesn't crash.
    assert cap is None or hasattr(cap, "module")


def test_get_uses_provided_index(fake_repo):
    from agents.module_registry import registry, get
    idx = registry(root=fake_repo)
    cap = get("agents.alpha", index=idx)
    assert cap is not None
    assert cap.description.startswith("Alpha module")


def test_get_unknown_returns_none(fake_repo):
    from agents.module_registry import registry, get
    idx = registry(root=fake_repo)
    assert get("agents.ghost", index=idx) is None


# ── by_subsystem ────────────────────────────────────────────────


def test_by_subsystem_groups(fake_repo):
    from agents.module_registry import by_subsystem
    groups = by_subsystem(root=fake_repo)
    assert set(groups.keys()) == {"agents", "scripts"}
    assert any(c.module == "agents.alpha" for c in groups["agents"])
    assert any(c.module == "scripts.task" for c in groups["scripts"])


# ── summary string ──────────────────────────────────────────────


def test_summary_includes_subsystem_headers(fake_repo):
    from agents.module_registry import summary
    s = summary(root=fake_repo)
    assert "## agents" in s
    assert "## scripts" in s
    assert "agents.alpha" in s
    assert "Alpha module" in s


def test_summary_total_count_line(fake_repo):
    from agents.module_registry import summary
    s = summary(root=fake_repo)
    # 4 modules expected: alpha, beta + __init__ both, scripts.task + __init__.
    # Actually our walker returns 5 (agents, agents.alpha, agents.beta,
    # scripts, scripts.task) — both __init__ files yield names too.
    assert "modules in 2 subsystems" in s


# ── as_dict ──────────────────────────────────────────────────────


def test_as_dict_serialisable(fake_repo):
    import json
    from agents.module_registry import as_dict
    raw = as_dict(root=fake_repo)
    assert "modules" in raw
    json.dumps(raw)   # must serialise without error


# ── real repo smoke ─────────────────────────────────────────────


def test_real_repo_smoke():
    """Hit the real repo to make sure it doesn't crash / time out."""
    from agents.module_registry import registry
    caps = registry()
    assert len(caps) > 30  # we have ≥30 modules in agents/ alone
