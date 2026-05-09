"""agents/project_pdf_export.py — markdown → PDF/HTML (PE1, 2026-05-03).

Pipeline: project_owner.morning_brief + readme_generator.generate
→ single markdown blob → pandoc (or fallback pure-Python HTML wrapper)
→ output file. Used by `aim project export-pdf <name>`.

We never bundle binary deps — pandoc must be installed externally. When
pandoc is missing we fall back to a minimal HTML render so the user
always gets *something* shareable.

Public API:
    render_markdown(project) -> str
    export_html(project, *, dest=None) -> Path
    export_pdf(project, *, dest=None) -> Path | None
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import html
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

log = logging.getLogger("aim.project_pdf_export")


def export_root() -> Path:
    env = os.environ.get("AIM_EXPORT_DIR")
    if env:
        return Path(env).expanduser()
    return Path.home() / "Desktop" / "_exports"


# ── compose markdown ─────────────────────────────────────────────


def render_markdown(project: str) -> str:
    """Concatenate brief + README + memory + git activity into one
    markdown document suitable for pandoc."""
    parts: list[str] = []
    title = f"# {project} — snapshot {dt.date.today().isoformat()}\n"
    parts.append(title)

    try:
        from agents.project_owner import morning_brief
        parts.append("## Morning brief\n")
        parts.append("```")
        parts.append(morning_brief(project))
        parts.append("```\n")
    except Exception as e:
        parts.append(f"_(brief failed: {e})_\n")

    try:
        from agents.readme_generator import generate
        parts.append(generate(project))
    except Exception as e:
        parts.append(f"_(README generation failed: {e})_\n")

    return "\n".join(parts)


# ── HTML fallback ───────────────────────────────────────────────


def _markdown_to_html_fallback(md: str, title: str) -> str:
    """Best-effort markdown → HTML when pandoc is missing.

    Handles: ATX headings (#-####), bullet lists, fenced code blocks,
    paragraph breaks, inline emphasis (`*…*`, `**…**`, `` `…` ``).
    """
    import re
    lines = md.splitlines()
    out: list[str] = []
    in_code = False
    in_list = False

    def close_list():
        nonlocal in_list
        if in_list:
            out.append("</ul>")
            in_list = False

    for raw in lines:
        line = raw.rstrip()
        if line.startswith("```"):
            close_list()
            if not in_code:
                out.append("<pre><code>")
                in_code = True
            else:
                out.append("</code></pre>")
                in_code = False
            continue
        if in_code:
            out.append(html.escape(line))
            continue
        m = re.match(r"^(#{1,4})\s+(.*)$", line)
        if m:
            close_list()
            level = len(m.group(1))
            out.append(f"<h{level}>{html.escape(m.group(2))}</h{level}>")
            continue
        m = re.match(r"^\s*[-•]\s+(.*)$", line)
        if m:
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{_inline(m.group(1))}</li>")
            continue
        if line.strip() == "":
            close_list()
            out.append("")
            continue
        close_list()
        out.append(f"<p>{_inline(line)}</p>")

    if in_list:
        out.append("</ul>")
    if in_code:
        out.append("</code></pre>")

    body = "\n".join(out)
    return _wrap_html(title, body)


def _inline(text: str) -> str:
    import re
    text = html.escape(text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", text)
    return text


def _wrap_html(title: str, body: str) -> str:
    return (
        f"<!doctype html><html><head><meta charset=\"utf-8\">"
        f"<title>{html.escape(title)}</title>"
        f"<style>body{{font-family:Helvetica,Arial,sans-serif;"
        f"max-width:46em;margin:2em auto;padding:0 1em;line-height:1.45}}"
        f"h1,h2,h3,h4{{margin-top:1.5em}}"
        f"pre{{background:#f5f5f5;padding:0.6em;overflow-x:auto;"
        f"border-radius:4px}}"
        f"code{{font-family:ui-monospace,Menlo,monospace;font-size:0.9em}}"
        f"li{{margin:0.2em 0}}</style></head>"
        f"<body>{body}</body></html>"
    )


# ── exports ──────────────────────────────────────────────────────


def export_html(project: str, *, dest: Optional[Path] = None,
                use_pandoc: bool = True) -> Path:
    md = render_markdown(project)
    title = f"{project} — {dt.date.today().isoformat()}"
    body: str
    if use_pandoc and shutil.which("pandoc"):
        try:
            r = subprocess.run(
                ["pandoc", "-f", "markdown", "-t", "html5",
                 "--standalone", "--metadata", f"title={title}"],
                input=md, capture_output=True, text=True, check=True,
            )
            body = r.stdout
        except subprocess.CalledProcessError as e:
            log.warning("pandoc HTML failed: %s", e)
            body = _markdown_to_html_fallback(md, title)
    else:
        body = _markdown_to_html_fallback(md, title)

    if dest is None:
        out_dir = export_root()
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        dest = out_dir / f"{project}-{stamp}.html"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(body, encoding="utf-8")
    return dest


def export_pdf(project: str, *, dest: Optional[Path] = None) -> Optional[Path]:
    """Try pandoc → PDF. Returns None if pandoc isn't available
    (caller should fall back to export_html)."""
    if not shutil.which("pandoc"):
        log.warning("pandoc not installed; cannot export PDF")
        return None
    md = render_markdown(project)
    if dest is None:
        out_dir = export_root()
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        dest = out_dir / f"{project}-{stamp}.pdf"
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            ["pandoc", "-f", "markdown", "-o", str(dest)],
            input=md, capture_output=True, text=True, check=True,
        )
    except subprocess.CalledProcessError as e:
        log.warning("pandoc PDF failed: %s — stderr: %s", e, e.stderr[:300])
        return None
    return dest
