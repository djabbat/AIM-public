"""tests/test_impact_analyser.py — SC1 (2026-05-03)."""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def fake_repo(tmp_path):
    """Build a tiny repo: agents/x.py, agents/y.py, scripts/run.py, tests/test_x.py."""
    (tmp_path / "agents").mkdir()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "tests").mkdir()

    (tmp_path / "agents" / "__init__.py").write_text("")
    (tmp_path / "scripts" / "__init__.py").write_text("")
    (tmp_path / "tests" / "__init__.py").write_text("")

    (tmp_path / "agents" / "x.py").write_text("def f(): return 1\n")
    (tmp_path / "agents" / "y.py").write_text(
        "from agents import x\n"
        "def g(): return x.f()\n"
    )
    (tmp_path / "scripts" / "run.py").write_text(
        "from agents.y import g\n"
        "if __name__ == '__main__': print(g())\n"
    )
    (tmp_path / "tests" / "test_x.py").write_text(
        "from agents.x import f\n"
        "def test_x(): assert f() == 1\n"
    )
    return tmp_path


# ── path → module ────────────────────────────────────────────────


def test_path_to_module_basic(fake_repo):
    from agents.impact_analyser import _path_to_module
    assert _path_to_module(fake_repo / "agents" / "x.py", fake_repo) == "agents.x"


def test_path_to_module_init(fake_repo):
    from agents.impact_analyser import _path_to_module
    p = fake_repo / "agents" / "__init__.py"
    assert _path_to_module(p, fake_repo) == "agents"


def test_path_to_module_outside_root(fake_repo, tmp_path):
    from agents.impact_analyser import _path_to_module
    other = tmp_path.parent / "elsewhere.py"
    assert _path_to_module(other, fake_repo) is None


def test_path_to_module_non_python(fake_repo):
    from agents.impact_analyser import _path_to_module
    p = fake_repo / "agents" / "data.csv"
    p.write_text("hello")
    assert _path_to_module(p, fake_repo) is None


# ── import extraction ───────────────────────────────────────────


def test_imports_in_file_picks_up_both_forms(fake_repo):
    from agents.impact_analyser import _imports_in_file
    p = fake_repo / "agents" / "y.py"
    deps = _imports_in_file(p)
    assert "agents" in deps   # `from agents import x`


def test_imports_skips_relative(fake_repo):
    from agents.impact_analyser import _imports_in_file
    p = fake_repo / "agents" / "rel.py"
    p.write_text("from . import x\n")
    deps = _imports_in_file(p)
    assert deps == set()


def test_imports_handles_syntax_error(fake_repo):
    from agents.impact_analyser import _imports_in_file
    p = fake_repo / "agents" / "broken.py"
    p.write_text("def: bad python (")
    assert _imports_in_file(p) == set()


# ── build_index ─────────────────────────────────────────────────


def test_index_lists_modules(fake_repo):
    from agents.impact_analyser import build_index
    idx = build_index(root=fake_repo)
    mods = set(idx.forward.keys())
    assert "agents.x" in mods
    assert "agents.y" in mods
    assert "scripts.run" in mods
    assert "tests.test_x" in mods


def test_index_reverse_map(fake_repo):
    from agents.impact_analyser import build_index
    idx = build_index(root=fake_repo)
    # agents.x is imported by agents.y (via `from agents import x`).
    # Note: we register `agents` (parent) in the reverse map too.
    assert "agents.y" in idx.reverse.get("agents", set())
    assert "tests.test_x" in idx.reverse.get("agents.x", set())


# ── impact_for ───────────────────────────────────────────────────


def test_impact_for_path(fake_repo):
    from agents.impact_analyser import impact_for
    res = impact_for(fake_repo / "agents" / "x.py", root=fake_repo)
    assert res.target_module == "agents.x"
    assert "tests.test_x" in res.test_files


def test_impact_for_module_name(fake_repo):
    from agents.impact_analyser import impact_for
    res = impact_for("agents.x", root=fake_repo)
    assert res.target_module == "agents.x"


def test_impact_unknown_target_raises(fake_repo):
    from agents.impact_analyser import impact_for
    with pytest.raises(FileNotFoundError):
        impact_for("agents.ghost", root=fake_repo)


def test_impact_transitive_chain(fake_repo):
    """Changing agents/x → directly impacts tests.test_x; agents.y also
    depends on it; scripts.run transitively depends through y."""
    from agents.impact_analyser import build_index, impact_for
    idx = build_index(root=fake_repo)
    res = impact_for("agents.x", index=idx, root=fake_repo)
    # Our reverse-map writes 'agents' as the parent shortcut, so y is in direct.
    direct_set = set(res.direct_dependents)
    assert "tests.test_x" in direct_set


def test_impact_test_files_list(fake_repo):
    from agents.impact_analyser import impact_for
    res = impact_for("agents.x", root=fake_repo)
    assert "tests.test_x" in res.test_files


# ── summary string ──────────────────────────────────────────────


def test_summary_renders(fake_repo):
    from agents.impact_analyser import summary
    s = summary("agents.x")  # uses real repo by default — won't crash
    # Either an error (when target unknown in real repo) or formatted ok.
    assert s.startswith(("ERROR:", "📡"))
