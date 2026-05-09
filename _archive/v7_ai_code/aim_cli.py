"""aim_cli.py — single entry-point dispatcher (G8, 2026-05-03).

Replaces the constellation of ad-hoc `python -m agents.X` and
`python -m scripts.Y` invocations with one unified CLI:

    aim brief                   — daily brief (today's projects + deadlines)
    aim brief --lang en
    aim brief --project FCLC

    aim recall <query> [--k 5] [--json]
    aim digest                  — weekly self-improvement digest
    aim followups [--save]      — auto-draft follow-up emails to overdue contacts

    aim eval [--version v]      — run the eval harness once
    aim eval auto               — run regression-detection mode
    aim eval list

    aim project list
    aim project archive <name>
    aim project sweep [--apply]
    aim project transition <name> <DST>

    aim memory                  — memory hygiene summary
    aim cost                    — cost ledger summary
    aim escalate                — fire escalation rules across all projects

    aim health                  — full health snapshot

    aim version

Install symlink (in ~/.aim/install_node.sh or manually):
    ln -sf $AIM/aim_cli.py /usr/local/bin/aim
"""
from __future__ import annotations

import argparse
import importlib
import logging
import sys
from pathlib import Path
from typing import Callable

# Make the AIM package importable when invoked from any cwd.
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="aim",
        description="AIM — single entry point for the agent toolchain")
    sub = p.add_subparsers(dest="cmd", required=True)

    # brief
    g = sub.add_parser("brief", help="daily project + deadline brief")
    g.add_argument("--project", default=None)
    g.add_argument("--lang", default=None)

    # recall
    g = sub.add_parser("recall", help="semantic memory recall")
    g.add_argument("query", nargs="+")
    g.add_argument("--k", type=int, default=5)
    g.add_argument("--json", action="store_true")

    # digest
    sub.add_parser("digest", help="weekly self-improvement digest")

    # followups
    g = sub.add_parser("followups", help="draft follow-up emails")
    g.add_argument("--save", action="store_true",
                   help="actually save Gmail drafts (default = preview)")

    # eval
    g = sub.add_parser("eval", help="eval harness")
    eg = g.add_subparsers(dest="eval_cmd", required=False)
    er = eg.add_parser("run", help="single run")
    er.add_argument("--version", required=False, default=None)
    er.add_argument("--tag", default=None)
    eg.add_parser("auto", help="regression-detection mode")
    eg.add_parser("list", help="list configured cases")

    # project
    g = sub.add_parser("project", help="project ownership ops")
    pg = g.add_subparsers(dest="project_cmd", required=True)
    pg.add_parser("list")
    a = pg.add_parser("archive")
    a.add_argument("name")
    a.add_argument("--reason", default="")
    a = pg.add_parser("unarchive")
    a.add_argument("name")
    a = pg.add_parser("sweep")
    a.add_argument("--apply", action="store_true")
    a.add_argument("--idle-months", type=int, default=6)
    a = pg.add_parser("transition")
    a.add_argument("name")
    a.add_argument("dst")
    a.add_argument("--reason", default="")

    # do — freeform dispatcher (Q1)
    g = sub.add_parser("do", help="freeform task dispatcher")
    g.add_argument("query", nargs="+", help="natural-language request")

    # setup-key — interactive provider-key setup; writes to ~/.aim_env
    g = sub.add_parser("setup-key",
                       help="set/replace personal LLM provider keys (DeepSeek, Groq, Anthropic, Gemini)")
    g.add_argument("--provider", action="append", default=None,
                   choices=["deepseek", "groq", "anthropic", "gemini"],
                   help="restrict to these providers (repeatable; default: all)")
    g.add_argument("--status", action="store_true",
                   help="just show which keys are currently set, without prompting")

    # serve — long-running daemon (G10)
    g = sub.add_parser("serve", help="run AIM as a foreground daemon")
    g.add_argument("--once", action="store_true",
                   help="fire one tick, then exit")
    g.add_argument("--tick-seconds", type=int, default=30)

    # routine — named bundles (RB1)
    g = sub.add_parser("routine", help="run a named action bundle")
    rg = g.add_subparsers(dest="routine_cmd", required=False)
    rg.add_parser("list", help="list configured routines")
    rr = rg.add_parser("run", help="run a routine by name")
    rr.add_argument("name")

    # diag — read latest self-diagnostic and emit fix plan
    g = sub.add_parser("diag",
                        help="render fix plan from latest self-diag report")
    g.add_argument("--report", default=None,
                    help="path to a specific report (default: latest)")
    g.add_argument("--save", action="store_true",
                    help="write fix plan markdown to artifacts/")
    g.add_argument("--context", type=int, default=2,
                    help="snippet context lines (default 2)")
    g.add_argument("--trend", action="store_true",
                    help="show diagnostic-ledger trend instead of fix plan")
    g.add_argument("--history", type=int, default=0, metavar="N",
                    help="list last N ledger records (0 = off)")
    g.add_argument("--regress", action="store_true",
                    help="show regression check between last two ledger runs")
    g.add_argument("--gen-cases", action="store_true",
                    help="convert findings from latest report into eval cases")
    g.add_argument("--dashboard", action="store_true",
                    help="render full AI/ subproject dashboard")
    g.add_argument("--doctor", action="store_true",
                    help="smoke-test AI/ subproject wiring")
    g.add_argument("--validate-cases", action="store_true",
                    help="validate every yaml case in AIM_EVAL_CASES_DIR")
    g.add_argument("--json", action="store_true",
                    help="emit dashboard as JSON (use with --dashboard)")
    g.add_argument("--compact", action="store_true",
                    help="Telegram-friendly 1-line-per-section dashboard")
    g.add_argument("--archive-cases", action="store_true",
                    help="move stale FE1 regression cases to _archived/")
    g.add_argument("--dry-run", action="store_true",
                    help="with --archive-cases, list without moving")
    g.add_argument("--morning", action="store_true",
                    help="single-shot wake-up brief: wiring + regression + trend")
    g.add_argument("--sweep", action="store_true",
                    help="run periodic maintenance: prompt fingerprint + "
                         "case validate + case archive (use --dry-run)")
    g.add_argument("--score", action="store_true",
                    help="single 0-100 health score across all signals")
    g.add_argument("--info", action="store_true",
                    help="one-line health summary for cron logs")
    g.add_argument("--prune-phantom", action="store_true",
                    help="remove ledger rows whose report_path no longer exists")
    g.add_argument("--suppress", metavar="REF",
                    help="add a finding suppression (file:line); RA1/RD1 ignore")
    g.add_argument("--unsuppress", metavar="REF",
                    help="remove a finding suppression")
    g.add_argument("--list-suppressions", action="store_true",
                    help="list active finding suppressions")
    g.add_argument("--backup", metavar="PATH", nargs="?", const="",
                    help="dump all DB state to JSON (default: artifacts/)")
    g.add_argument("--restore", metavar="PATH",
                    help="restore from a backup JSON file")
    g.add_argument("--validate-findings", action="store_true",
                    help="auto-validate findings in latest diagnostic")
    g.add_argument("--explain", action="store_true",
                    help="explain score breakdown with concrete recovery actions")
    g.add_argument("--hive-preview", action="store_true",
                    help="preview anonymized payload that hive worker would send")
    g.add_argument("--hive-status", action="store_true",
                    help="show hive worker sync state + queen state")

    # passthroughs
    sub.add_parser("memory", help="memory hygiene scan")
    sub.add_parser("cost",   help="cost ledger summary")
    sub.add_parser("escalate", help="fire escalation rules")
    sub.add_parser("health", help="full self-health JSON")
    sub.add_parser("version")
    return p


# ── commands ─────────────────────────────────────────────────────


def _cmd_brief(args) -> int:
    from agents.brief_preamble import compose
    from agents import project_owner as po
    if args.project:
        text = po.morning_brief(args.project)
    else:
        preamble = compose(lang=args.lang)
        text = preamble + "\n\n" + po.all_briefs()
    print(text)
    return 0


def _cmd_recall(args) -> int:
    from agents.recall_cli import recall_top, recall_json
    q = " ".join(args.query)
    if args.json:
        print(recall_json([q], k=args.k))
    else:
        print(recall_top(q, k=args.k))
    return 0


def _cmd_digest(_args) -> int:
    from scripts.weekly_digest import render_digest, send_telegram
    text = render_digest()
    if not send_telegram(text):
        print(text)
    return 0


def _cmd_followups(args) -> int:
    from agents.follow_up_generator import generate_all, save_drafts
    drafts = generate_all()
    if not drafts:
        print("(no overdue stakeholders)")
        return 0
    for d in drafts:
        print(f"=== draft for {d.contact_name} <{d.contact_email}> "
              f"({d.lang}, {d.days_silent}d silent) ===")
        print(f"Subject: {d.subject}")
        print(d.body)
        print()
    if args.save:
        ids = save_drafts(drafts)
        print(f"saved {len(ids)} Gmail drafts: {ids}")
    return 0


def _cmd_eval(args) -> int:
    from agents import evals as ev
    sub = (args.eval_cmd or "run")
    if sub == "list":
        for c in ev.load_cases():
            print(f"{c.id:30s}  tags={c.tags}")
        return 0
    if sub == "auto":
        from scripts.auto_eval import main as _auto
        return _auto()
    # default: run
    version = args.version or __import__("datetime").date.today().isoformat()
    from llm import ask
    run = ev.run_all(ask, version=version, tag_filter=args.tag)
    print(f"version={run.version} score={run.aggregate_score:.3f} "
          f"n={len(run.cases)}")
    return 0


def _cmd_project(args) -> int:
    sub = args.project_cmd
    if sub == "list":
        from agents import project_owner as po
        for n in po.list_projects():
            print(n)
        return 0
    from agents import project_archive as pa
    if sub == "archive":
        path = pa.archive(args.name, reason=args.reason)
        print(f"archived → {path}")
        return 0
    if sub == "unarchive":
        path = pa.unarchive(args.name)
        print(f"restored → {path}")
        return 0
    if sub == "sweep":
        cands = pa.autosweep(idle_months=args.idle_months,
                             dry_run=not args.apply)
        for c in cands:
            print(f"  {c.project}  phase={c.phase}  idle={c.idle_days}d")
        if not cands:
            print("(no candidates)")
        return 0
    if sub == "transition":
        from agents import project_state_machine as sm
        rec = sm.transition(args.name, args.dst, reason=args.reason)
        import json as _json
        print(_json.dumps(rec, ensure_ascii=False))
        return 0
    return 1


def _cmd_memory(_args) -> int:
    from agents.memory_monitor import summary
    print(summary())
    return 0


def _cmd_cost(_args) -> int:
    from agents.cost_ledger import summary
    print(summary())
    return 0


def _cmd_escalate(_args) -> int:
    from agents.escalation_engine import evaluate_all
    alerts = evaluate_all(cooldown_hours=0)
    if not alerts:
        print("(no rules matched)")
        return 0
    for a in alerts:
        print(a.to_text())
    return 0


def _cmd_health(_args) -> int:
    from agents.health_extended import report_json
    print(report_json())
    return 0


def _cmd_version(_args) -> int:
    print("AIM 2026.05.03 (post Phases 1-5 + extension wave)")
    return 0


def _cmd_do(args) -> int:
    from agents.quick_action import handle
    import json as _json
    q = " ".join(args.query)
    result = handle(q)
    print(_json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not result.get("error") else 1


def _cmd_serve(args) -> int:
    from agents.serve_daemon import run_once, run_forever
    if args.once:
        fired = run_once()
        print(f"fired: {fired}")
        return 0
    run_forever(tick_seconds=args.tick_seconds)
    return 0


def _cmd_routine(args) -> int:
    from agents.routines import list_routines, run as run_routine
    sub = (args.routine_cmd or "list")
    if sub == "list":
        for n in list_routines():
            print(n)
        return 0
    if sub == "run":
        try:
            res = run_routine(args.name)
        except KeyError as e:
            print(f"ERROR: {e}")
            return 2
        print(f"routine {res.name}: {len(res.steps)} steps, ok={res.ok}")
        for s in res.steps:
            mark = "✅" if s.ok else "❌"
            print(f"  {mark} step {s.step}: {s.action}")
            if not s.ok:
                print(f"     error: {s.error}")
        return 0 if res.ok else 1
    return 1


def _cmd_diag(args) -> int:
    from pathlib import Path
    from AI.ai.meta_evaluator import parse_report
    from AI.ai.fix_planner import plan, render_markdown, summary as fp_summary

    if getattr(args, "trend", False):
        from AI.ai.diagnostic_ledger import summary as trend_summary
        print(trend_summary())
        return 0

    if getattr(args, "history", 0):
        from AI.ai.diagnostic_ledger import recent
        rows = recent(n=args.history)
        if not rows:
            print("(no diagnostic runs recorded)")
            return 0
        for r in rows:
            print(f"{r.ts[:19]}  {r.model:18s}  grade={r.grade or '-':<2}"
                  f"  refs={r.n_refs:>3}  comp={r.compliance:>5.0%}"
                  f"  retry={'Y' if r.retry_used else 'N'}")
        return 0

    if getattr(args, "regress", False):
        from AI.ai.regression_detector import summary as regr_summary
        print(regr_summary())
        return 0

    if getattr(args, "dashboard", False):
        from AI.ai.dashboard import render, render_json, render_compact
        if getattr(args, "json", False):
            print(render_json())
        elif getattr(args, "compact", False):
            print(render_compact())
        else:
            print(render())
        return 0

    if getattr(args, "doctor", False):
        from AI.ai.doctor import summary, has_critical_failure
        print(summary())
        return 1 if has_critical_failure() else 0

    if getattr(args, "validate_cases", False):
        from AI.ai.case_validator import validate_dir, summary
        r = validate_dir()
        print(summary())
        return 0 if r.all_ok else 1

    if getattr(args, "archive_cases", False):
        from AI.ai.case_archiver import archive, summary
        print(summary())
        if not getattr(args, "dry_run", False):
            res = archive(dry_run=False)
            print(f"\nmoved {res.n_moved} → {res.archive_dir}")
        return 0

    if getattr(args, "morning", False):
        from AI.ai.morning_brief import render
        print(render())
        return 0

    if getattr(args, "sweep", False):
        from AI.ai.auto_sweep import summary as sweep_summary
        print(sweep_summary(dry_run=getattr(args, "dry_run", False)))
        return 0

    if getattr(args, "score", False):
        from AI.ai.health_score import summary, score, trend
        print(summary())
        t = trend()
        if t["n"] >= 2:
            arrow = "↑" if t["delta"] > 0 else ("↓" if t["delta"] < 0 else "=")
            print(f"\n  trend: {t['first_total']} → {t['last_total']} "
                  f"{arrow} ({t['delta']:+d}) over {t['n']} snapshots")
        s = score()
        return 0 if s.total >= 60 else 1

    if getattr(args, "info", False):
        from AI.ai.health_score import info_line, score
        print(info_line())
        return 0 if score().total >= 60 else 1

    if getattr(args, "prune_phantom", False):
        from AI.ai.diagnostic_ledger import prune_phantom
        res = prune_phantom(dry_run=getattr(args, "dry_run", False))
        if res["dry_run"]:
            print(f"would remove {res['would_remove']} phantom row(s); "
                  f"keeping {res['kept']}")
        else:
            print(f"removed {res['removed']} phantom row(s); "
                  f"kept {res['kept']}")
        return 0

    if getattr(args, "suppress", None):
        from AI.ai.finding_suppressions import suppress
        s = suppress(args.suppress)
        print(f"suppressed: {s.ref}")
        return 0

    if getattr(args, "unsuppress", None):
        from AI.ai.finding_suppressions import unsuppress
        ok = unsuppress(args.unsuppress)
        print(f"unsuppressed: {args.unsuppress}" if ok
              else f"no such suppression: {args.unsuppress}")
        return 0 if ok else 1

    if getattr(args, "list_suppressions", False):
        from AI.ai.finding_suppressions import summary
        print(summary())
        return 0

    if getattr(args, "backup", None) is not None:
        from AI.ai.backup import write_snapshot
        from pathlib import Path as _P
        target = _P(args.backup) if args.backup else None
        out = write_snapshot(target)
        print(f"backup written: {out}")
        return 0

    if getattr(args, "restore", None):
        from AI.ai.backup import restore
        from pathlib import Path as _P
        counts = restore(_P(args.restore),
                          dry_run=getattr(args, "dry_run", False))
        verb = "would insert" if counts["dry_run"] else "inserted"
        for db, tcounts in counts.items():
            if db == "dry_run":
                continue
            print(f"{db}:")
            for t, n in tcounts.items():
                print(f"  {verb} {n} into {t}")
        return 0

    if getattr(args, "explain", False):
        from AI.ai.explainer import summary
        print(summary())
        return 0

    if getattr(args, "hive_preview", False):
        from AI.ai.hive_telemetry import preview
        print(preview())
        return 0

    if getattr(args, "hive_status", False):
        from AI.ai.hive_telemetry import summary as ts
        from AI.ai.hive_queen import summary as qs
        from AI.ai.hive_consumer import summary as cs
        print(ts())
        print()
        print(qs())
        print()
        print(cs())
        return 0

    if getattr(args, "validate_findings", False):
        from AI.ai.finding_validator import summary
        from pathlib import Path as _P

        if args.report:
            report_path = _P(args.report).expanduser()
        else:
            artifacts = _P(__file__).resolve().parent / "AI" / "artifacts"
            cands = sorted(p for p in artifacts.glob("self_diag_*.md")
                            if "_request_" not in p.name)
            if not cands:
                print("ERROR: no self_diag_*.md in AI/artifacts/")
                return 2
            report_path = cands[-1]
        if not report_path.exists():
            print(f"ERROR: report not found: {report_path}")
            return 2
        print(summary(report_path.read_text(encoding="utf-8")))
        return 0

    if getattr(args, "gen_cases", False):
        from AI.ai.meta_evaluator import parse_report
        from AI.ai.findings_to_evals import write_cases
        from pathlib import Path

        if args.report:
            report_path = Path(args.report).expanduser()
        else:
            artifacts = Path(__file__).resolve().parent / "AI" / "artifacts"
            cands = sorted(p for p in artifacts.glob("self_diag_*.md")
                            if "_request_" not in p.name)
            if not cands:
                print("ERROR: no self_diag_*.md in AI/artifacts/")
                return 2
            report_path = cands[-1]

        if not report_path.exists():
            print(f"ERROR: report not found: {report_path}")
            return 2

        parsed = parse_report(report_path.read_text(encoding="utf-8"))
        written = write_cases(parsed.findings)
        print(f"report: {report_path.name}")
        print(f"  refs:    {len(parsed.findings)}")
        print(f"  written: {len(written)} new eval cases")
        for p in written[:10]:
            print(f"    • {p.name}")
        if len(written) > 10:
            print(f"    (+{len(written) - 10} more)")
        return 0

    if args.report:
        report_path = Path(args.report).expanduser()
    else:
        artifacts = Path(__file__).resolve().parent / "AI" / "artifacts"
        candidates = sorted(p for p in artifacts.glob("self_diag_*.md")
                             if "_request_" not in p.name)
        if not candidates:
            print("ERROR: no self_diag_*.md in AI/artifacts/")
            return 2
        report_path = candidates[-1]

    if not report_path.exists():
        print(f"ERROR: report not found: {report_path}")
        return 2

    text = report_path.read_text(encoding="utf-8")
    parsed = parse_report(text)
    print(f"report: {report_path.name}")
    print(f"  grade={parsed.grade}  refs={len(parsed.findings)}  "
          f"line_compliance={parsed.line_compliance:.0%}")
    if parsed.findings and parsed.line_compliance < 0.5:
        print("  ⚠ low compliance — refs may be unreliable; rerun "
              "with stricter prompt before acting.")

    fp = plan(parsed.findings, context_lines=args.context)
    print()
    print(fp_summary(fp))

    if args.save:
        out = (report_path.parent
               / report_path.name.replace("self_diag_", "fix_plan_"))
        out.write_text(render_markdown(fp), encoding="utf-8")
        print(f"\nsaved: {out}")
    return 0


def _cmd_setup_key(args) -> int:
    from key_setup import run_interactive, show_status
    if args.status:
        show_status()
        return 0
    run_interactive(args.provider)
    return 0


_HANDLERS: dict[str, Callable] = {
    "brief":     _cmd_brief,
    "recall":    _cmd_recall,
    "digest":    _cmd_digest,
    "followups": _cmd_followups,
    "eval":      _cmd_eval,
    "project":   _cmd_project,
    "do":        _cmd_do,
    "serve":     _cmd_serve,
    "routine":   _cmd_routine,
    "diag":      _cmd_diag,
    "memory":    _cmd_memory,
    "cost":      _cmd_cost,
    "escalate":  _cmd_escalate,
    "health":    _cmd_health,
    "version":   _cmd_version,
    "setup-key": _cmd_setup_key,
}


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    fn = _HANDLERS.get(args.cmd)
    if fn is None:
        parser.error(f"unknown command {args.cmd!r}")
        return 2
    return fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
