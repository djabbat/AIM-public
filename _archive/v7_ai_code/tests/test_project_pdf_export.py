"""tests/test_project_pdf_export.py — PE1 (2026-05-03)."""
from __future__ import annotations

import shutil

import pytest


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AIM_PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("AIM_EXPORT_DIR", str(tmp_path / "exports"))
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "projects").mkdir()
    (tmp_path / "Desktop").mkdir()
    import importlib, sys
    for m in ["agents.project_owner", "agents.readme_generator",
              "agents.project_pdf_export"]:
        if m in sys.modules:
            importlib.reload(sys.modules[m])
    return tmp_path


def write_proj(setup, name, body="name: P\nphase: DRAFT\n"):
    (setup / "projects" / f"{name}.yaml").write_text(body, encoding="utf-8")


# ── render_markdown ──────────────────────────────────────────────


def test_render_includes_title(isolated):
    write_proj(isolated, "FCLC")
    from agents.project_pdf_export import render_markdown
    md = render_markdown("FCLC")
    assert md.startswith("# FCLC")


def test_render_includes_brief_section(isolated):
    import textwrap
    write_proj(isolated, "P", textwrap.dedent("""
        name: P
        phase: SUBMITTED
        milestones:
          - id: hot
            deadline: 2026-05-05
            criticality: high
            status: pending
    """).lstrip())
    from agents.project_pdf_export import render_markdown
    md = render_markdown("P")
    assert "Morning brief" in md
    assert "hot" in md


def test_render_includes_readme_section(isolated):
    write_proj(isolated, "P", "name: P\nphase: SUBMITTED\n")
    from agents.project_pdf_export import render_markdown
    md = render_markdown("P")
    assert "## Goals" not in md  # no goals declared
    assert "P" in md


# ── HTML fallback (pandoc not required) ─────────────────────────


def test_export_html_fallback_writes_file(isolated, monkeypatch):
    write_proj(isolated, "P", "name: P\n")
    from agents.project_pdf_export import export_html
    out = export_html("P", use_pandoc=False)
    assert out.exists()
    text = out.read_text()
    assert text.startswith("<!doctype html>")
    assert "<h1>" in text
    assert "P" in text


def test_export_html_renders_lists(isolated, monkeypatch):
    import textwrap
    write_proj(isolated, "P", textwrap.dedent("""
        name: P
        goals:
          - alpha
          - beta
    """).lstrip())
    from agents.project_pdf_export import export_html
    out = export_html("P", use_pandoc=False)
    text = out.read_text()
    assert "<ul>" in text
    assert "<li>alpha</li>" in text


def test_export_html_renders_code_blocks(isolated):
    write_proj(isolated, "P", "name: P\n")
    from agents.project_pdf_export import export_html
    out = export_html("P", use_pandoc=False)
    text = out.read_text()
    # The "Morning brief" section is inside ```…```.
    assert "<pre><code>" in text


def test_export_html_custom_dest(isolated, tmp_path):
    write_proj(isolated, "P", "name: P\n")
    dest = tmp_path / "custom" / "out.html"
    from agents.project_pdf_export import export_html
    out = export_html("P", dest=dest, use_pandoc=False)
    assert out == dest
    assert dest.exists()


# ── pandoc smoke (only when binary present) ─────────────────────


@pytest.mark.skipif(shutil.which("pandoc") is None,
                    reason="pandoc not installed")
def test_export_html_pandoc_path(isolated):
    write_proj(isolated, "P", "name: P\n")
    from agents.project_pdf_export import export_html
    out = export_html("P", use_pandoc=True)
    text = out.read_text()
    # pandoc adds <!DOCTYPE> and a <head> with metadata.
    assert "html" in text.lower()


@pytest.mark.skipif(shutil.which("pandoc") is None,
                    reason="pandoc not installed")
def test_export_pdf_returns_path_when_available(isolated):
    write_proj(isolated, "P", "name: P\n")
    from agents.project_pdf_export import export_pdf
    out = export_pdf("P")
    # PDF backend may fail if no LaTeX installed; we accept None too.
    assert out is None or out.exists()


def test_export_pdf_returns_none_without_pandoc(isolated, monkeypatch):
    """Force shutil.which to return None and confirm we get None back."""
    monkeypatch.setattr("shutil.which", lambda _name: None)
    write_proj(isolated, "P", "name: P\n")
    import importlib, agents.project_pdf_export as ppe
    importlib.reload(ppe)
    monkeypatch.setattr(ppe, "shutil", type("S", (), {"which": lambda *a, **kw: None})())
    out = ppe.export_pdf("P")
    assert out is None


# ── inline markdown niceties ────────────────────────────────────


def test_inline_emphasis_rendered(isolated):
    from agents.project_pdf_export import _inline
    assert "<strong>bold</strong>" in _inline("**bold**")
    assert "<em>italic</em>" in _inline("*italic*")
    assert "<code>code</code>" in _inline("`code`")


def test_inline_html_escape(isolated):
    from agents.project_pdf_export import _inline
    out = _inline("<script>alert(1)</script>")
    assert "&lt;script&gt;" in out
