"""export/report_exporter.py — render an agent run result as HTML / PDF / MD.

Inputs accepted:
    • a result dict (as returned by run_agent / web/api.py)
    • a JSON file dumped from such a dict
    • stdin JSON

Backends:
    HTML  — plain Jinja-like template, zero deps
    MD    — for git checkin / Obsidian
    PDF   — three fallbacks tried in order:
              1. WeasyPrint (cleanest)              `pip install weasyprint`
              2. wkhtmltopdf (CLI, system-installed)
              3. pandoc + xelatex (likely already installed)

CLI:
    python -m export.report_exporter render result.json out/ --formats md html pdf
    aim-graph "task" | python -m export.report_exporter render --stdin --out report
"""

from __future__ import annotations

import argparse
import html
import json
import logging
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterable

log = logging.getLogger("aim.report")


_HTML_TEMPLATE = """<!doctype html>
<html lang="ru"><head>
<meta charset="utf-8">
<title>AIM Report — {ts}</title>
<style>
body{{font-family:system-ui,sans-serif;max-width:920px;margin:2rem auto;padding:0 1rem;color:#222;line-height:1.55;}}
h1{{margin:.4rem 0 1rem 0;font-size:1.6rem;}}
h2{{margin-top:1.5rem;font-size:1.15rem;color:#205493;}}
.meta{{color:#777;font-size:.92em;margin-bottom:1.5rem;}}
.task,.plan,.step,.review{{padding:.9rem 1rem;border-radius:6px;margin-bottom:1rem;}}
.task   {{background:#f4f4f6;}}
.plan   {{background:#eef4fb;}}
.step   {{background:#f3faf3;}}
.review {{background:#fff7e6;}}
ol{{margin:.4rem 0;padding-left:1.4rem;}}
pre  {{background:#0e1117;color:#d6deeb;padding:.9rem;overflow-x:auto;border-radius:4px;font-size:.88em;}}
code {{font-family:JetBrains Mono,monospace;}}
.tag {{display:inline-block;padding:.05rem .55rem;background:#dde6f5;border-radius:4px;margin-right:.4rem;font-size:.82em;}}
hr{{border:0;border-top:1px solid #eee;margin:1rem 0;}}
</style></head>
<body>
<h1>AIM Report</h1>
<div class=meta>
  <span class=tag>generated {ts}</span>
  <span class=tag>iteration {iteration}</span>
  {extra_tags}
</div>

<div class=task>
  <h2>Task</h2>
  <pre>{task}</pre>
</div>

<div class=plan>
  <h2>Plan ({n_steps} step{plural})</h2>
  <ol>
{plan_items}  </ol>
</div>

<h2>Execution</h2>
{step_blocks}

<div class=review>
  <h2>Reviewer verdict</h2>
  <pre>{review}</pre>
</div>
</body></html>
"""


def _esc(s: str) -> str:
    return html.escape(s or "")


def render_html(result: dict, *, extra_tags: Iterable[str] = ()) -> str:
    plan = result.get("plan", []) or []
    plan_items = "\n".join(f"    <li>{_esc(p)}</li>" for p in plan)
    n_steps = len(plan)
    plural = "" if n_steps == 1 else "s"
    step_blocks = "\n".join(
        f"<div class=step><pre>{_esc(s)}</pre></div>"
        for s in result.get("step_results", []) or []
    )
    extra = " ".join(f"<span class=tag>{_esc(t)}</span>" for t in extra_tags)
    return _HTML_TEMPLATE.format(
        ts=datetime.now().isoformat(timespec="seconds"),
        task=_esc(result.get("task", "")),
        plan_items=plan_items,
        n_steps=n_steps, plural=plural,
        step_blocks=step_blocks or "<div class=step><pre>(empty)</pre></div>",
        review=_esc(result.get("review", "(no review)")),
        iteration=result.get("iteration", 0),
        extra_tags=extra,
    )


def render_md(result: dict) -> str:
    lines = [
        f"# AIM Report",
        f"",
        f"_generated: {datetime.now().isoformat(timespec='seconds')}_  ",
        f"_iteration: {result.get('iteration', 0)}_",
        f"",
        f"## Task",
        f"",
        f"```\n{result.get('task','')}\n```",
        f"",
        f"## Plan",
        f"",
    ]
    for i, step in enumerate(result.get("plan", []) or [], 1):
        lines.append(f"{i}. {step}")
    lines.append("")
    lines.append("## Execution")
    lines.append("")
    for s in result.get("step_results", []) or []:
        lines.append("```")
        lines.append(s)
        lines.append("```")
        lines.append("")
    lines.append("## Reviewer verdict")
    lines.append("")
    lines.append("```")
    lines.append(result.get("review", "(no review)"))
    lines.append("```")
    return "\n".join(lines) + "\n"


# ── PDF backends ───────────────────────────────────────────────────────────


def _pdf_via_weasyprint(html_str: str, out: Path) -> bool:
    try:
        from weasyprint import HTML
        HTML(string=html_str).write_pdf(str(out))
        return True
    except ImportError:
        return False
    except Exception as e:
        log.warning(f"weasyprint failed: {e}")
        return False


def _pdf_via_wkhtmltopdf(html_str: str, out: Path) -> bool:
    if not shutil.which("wkhtmltopdf"):
        return False
    tmp = out.with_suffix(".tmp.html")
    tmp.write_text(html_str, encoding="utf-8")
    try:
        r = subprocess.run(["wkhtmltopdf", "--quiet", str(tmp), str(out)],
                           capture_output=True, timeout=30)
        return r.returncode == 0 and out.exists()
    finally:
        tmp.unlink(missing_ok=True)


def _pdf_via_pandoc(md_str: str, out: Path) -> bool:
    if not shutil.which("pandoc"):
        return False
    tmp = out.with_suffix(".tmp.md")
    tmp.write_text(md_str, encoding="utf-8")
    try:
        r = subprocess.run([
            "pandoc", str(tmp), "-o", str(out),
            "--pdf-engine=xelatex",
            "-V", "mainfont=DejaVu Sans",
            "-V", "geometry:margin=2cm",
        ], capture_output=True, timeout=120)
        return r.returncode == 0 and out.exists()
    finally:
        tmp.unlink(missing_ok=True)


def render_pdf(html_str: str, md_str: str, out: Path) -> bool:
    out.parent.mkdir(parents=True, exist_ok=True)
    for fn, name in (
        (_pdf_via_weasyprint,   "weasyprint"),
        (_pdf_via_wkhtmltopdf,  "wkhtmltopdf"),
    ):
        if fn(html_str, out):
            log.info(f"pdf via {name} → {out}")
            return True
    if _pdf_via_pandoc(md_str, out):
        log.info(f"pdf via pandoc → {out}")
        return True
    log.warning("no PDF backend available "
                "(install weasyprint OR wkhtmltopdf OR pandoc+xelatex)")
    return False


# ── public + CLI ───────────────────────────────────────────────────────────


def render(result: dict, out_dir: Path,
           formats: list[str] = ("md", "html"),
           name: str = "report") -> dict:
    out_dir = Path(out_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, str] = {}

    md_str = render_md(result)
    html_str = render_html(result)

    if "md" in formats:
        p = out_dir / f"{name}.md"
        p.write_text(md_str, encoding="utf-8");  written["md"] = str(p)
    if "html" in formats:
        p = out_dir / f"{name}.html"
        p.write_text(html_str, encoding="utf-8"); written["html"] = str(p)
    if "pdf" in formats:
        p = out_dir / f"{name}.pdf"
        ok = render_pdf(html_str, md_str, p)
        written["pdf"] = str(p) if ok else "(failed — no backend)"
    return written


def _main() -> int:
    p = argparse.ArgumentParser(prog="aim-report")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("render")
    r.add_argument("input", nargs="?",
                   help="path to result.json (omit for stdin)")
    r.add_argument("--stdin", action="store_true",
                   help="read JSON from stdin (must be a result dict)")
    r.add_argument("--out", default="./aim_report",
                   help="output directory")
    r.add_argument("--formats", nargs="+",
                   choices=["md", "html", "pdf"],
                   default=["md", "html"])
    r.add_argument("--name", default="report")

    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")

    if args.cmd == "render":
        if args.stdin or not args.input:
            data = sys.stdin.read()
        else:
            data = Path(args.input).read_text(encoding="utf-8")
        try:
            result = json.loads(data)
        except json.JSONDecodeError:
            # If user piped raw aim-graph stdout, wrap minimally
            result = {"task": "", "plan": [],
                      "step_results": [data], "review": "", "iteration": 1}
        written = render(result, Path(args.out), formats=args.formats, name=args.name)
        print(json.dumps(written, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
