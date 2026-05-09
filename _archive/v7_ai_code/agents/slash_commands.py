"""agents/slash_commands.py — slash-command router for the AIM REPL.

Used by `aim-graph-prompt-py` (and any other interactive surface). Each
command is a small handler returning a string (or None for plain pass-
through to the agent).

Commands are grouped:
    Memory:    /mem  /add  /forget  /snap  /roll  /diff  /dedup  /stats
    Graph:     /graph  /tree  /debate  /review  /no-mem  /full-mem
    System:    /cost  /health  /jobs  /metrics  /trace  /pi
    Profile:   /profile  /use
    Aider:     /aider  /clear-aider
    Misc:      /help  /clear  /exit  /quit
"""

from __future__ import annotations

import json
import logging
import re
import shlex
import subprocess
import sys
from typing import Callable, Optional

log = logging.getLogger("aim.slash")


# ── command implementations ────────────────────────────────────────────────


def _h_help(args: str, ctx: dict) -> str:
    return _help_text()


def _h_mem(args: str, ctx: dict) -> str:
    if not args.strip():
        return "usage: /mem <query> [--graph]"
    graph = "--graph" in args
    q = args.replace("--graph", "").strip()
    if graph:
        from agents.graphrag import query as gq
        hits = gq(q, k=10, hops=1)
    else:
        from agents.memory_index import retrieve
        hits = retrieve(q, k=10)
    if not hits:
        return "(no hits)"
    out = []
    for h in hits[:10]:
        out.append(f"  [{h.get('_distance', 0):.3f}]  {h.get('file','?')}\n"
                   f"    {h.get('text','').replace(chr(10),' ')[:200]}…")
    return "\n".join(out)


def _h_add(args: str, ctx: dict) -> str:
    parts = shlex.split(args) if args else []
    if not parts:
        return "usage: /add [--priority high] [--category x] [--ttl 720] <fact>"
    priority = "NORMAL"
    category = "general"
    ttl_hours = None
    fact_words: list[str] = []
    i = 0
    while i < len(parts):
        if parts[i] == "--priority" and i + 1 < len(parts):
            priority = parts[i + 1].upper(); i += 2
        elif parts[i] == "--category" and i + 1 < len(parts):
            category = parts[i + 1]; i += 2
        elif parts[i] == "--ttl" and i + 1 < len(parts):
            ttl_hours = int(parts[i + 1]); i += 2
        else:
            fact_words.append(parts[i]); i += 1
    fact = " ".join(fact_words).strip()
    if not fact:
        return "fact text empty"
    from agents.memory_priority import save_with_priority, Priority
    try:
        prio = Priority[priority]
    except KeyError:
        prio = Priority.NORMAL
    path = save_with_priority(fact, category=category, priority=prio, ttl_hours=ttl_hours)
    return f"saved → {path}"


def _h_forget(args: str, ctx: dict) -> str:
    if not args.strip():
        return "usage: /forget <pattern>"
    from agents.memory_store import forget
    n = forget(args.strip())
    return f"removed {n} files"


def _h_snap(args: str, ctx: dict) -> str:
    from agents.memory_versioning import MemoryVersioning
    return MemoryVersioning().snapshot(args.strip() or "interactive")


def _h_roll(args: str, ctx: dict) -> str:
    if not args.strip():
        return "usage: /roll <version_id>"
    from agents.memory_versioning import MemoryVersioning
    MemoryVersioning().rollback(args.strip())
    return f"rolled back to {args.strip()}"


def _h_diff(args: str, ctx: dict) -> str:
    parts = args.split()
    if len(parts) != 2:
        return "usage: /diff <ver_a> <ver_b>"
    from agents.memory_versioning import MemoryVersioning
    d = MemoryVersioning().diff(parts[0], parts[1])
    return json.dumps({"added": d["total_added"],
                       "removed": d["total_removed"],
                       "changed": d["total_changed"]}, indent=2)


def _h_dedup(args: str, ctx: dict) -> str:
    apply = "--apply" in args
    from agents.memory_deduplicate import MemoryDeduplicator
    pairs = MemoryDeduplicator().scan(dry_run=not apply)
    return f"found {len(pairs)} duplicate pair(s){'  (applied)' if apply else '  (dry-run)'}"


def _h_stats(args: str, ctx: dict) -> str:
    return _shell_capture(["python3", "-m", "agents.memory_cli", "stats"])


def _h_cost(args: str, ctx: dict) -> str:
    from agents.cost_monitor import stats as cstats
    s = cstats()
    return (f"daily ${s['daily_cost']:.4f} / ${s['daily_limit']:.2f}    "
            f"monthly ${s['monthly_cost']:.4f} / ${s['monthly_limit']:.2f}\n"
            f"calls: {s['total_calls']}   in_tok: {s['total_input_tokens']:,}   "
            f"out_tok: {s['total_output_tokens']:,}")


def _h_health(args: str, ctx: dict) -> str:
    from agents.memory_health import MemoryHealthChecker
    return json.dumps(MemoryHealthChecker().check(), ensure_ascii=False, indent=2)


def _h_jobs(args: str, ctx: dict) -> str:
    from agents.job_queue import list_jobs
    rows = list_jobs(limit=10)
    if not rows:
        return "(no jobs)"
    return "\n".join(
        f"  {r['status']:<10} {r['id']}  {r['name']}  ({r.get('duration_s') or '-'}s)"
        for r in rows
    )


def _h_metrics(args: str, ctx: dict) -> str:
    return _shell_capture(["curl", "-sS", "http://127.0.0.1:9091/healthz"]) or \
           "metrics server not running (start with `aim-graph --metrics`)"


def _h_trace(args: str, ctx: dict) -> str:
    from agents.tracing import init_tracing, ENABLED, ENDPOINT
    init_tracing()
    return f"tracing enabled={ENABLED}   endpoint={ENDPOINT}"


def _h_pi(args: str, ctx: dict) -> str:
    from agents.pi_agent import get_pi
    pi = get_pi()
    if args.strip() == "suggest":
        return "\n".join(f"💡 [{s['type']}] {s['msg']}" for s in pi.suggest()) or "(no suggestions)"
    return json.dumps(pi.stats(), ensure_ascii=False, indent=2)


def _h_profile(args: str, ctx: dict) -> str:
    parts = args.split()
    from agents.profile import list_profiles, get_active, use
    if not parts:
        cur = get_active()
        out = [f"current: {cur}"]
        for p in list_profiles():
            mark = "*" if p["active"] else " "
            out.append(f"  {mark} {p['name']:<20}  files={p['memory_md_count']}")
        return "\n".join(out)
    if parts[0] == "use" and len(parts) > 1:
        use(parts[1])
        ctx["profile"] = parts[1]
        return f"active: {parts[1]}"
    return "usage: /profile  |  /profile use <name>"


def _h_use(args: str, ctx: dict) -> str:
    return _h_profile(f"use {args}", ctx)


def _h_clear(args: str, ctx: dict) -> str:
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.flush()
    return ""


def _h_exit(args: str, ctx: dict) -> str:
    raise SystemExit(0)


# ── flag-toggle commands (return None and mutate ctx) ──────────────────────


def _toggle(flag: str) -> Callable:
    def _h(args: str, ctx: dict) -> Optional[str]:
        ctx[flag] = True
        return f"[ok] {flag} включён для следующего запроса"
    return _h


def _h_no_mem(args, ctx):
    ctx["no_mem"] = True
    return "[ok] память выкл. для следующего запроса"


# ── registry ───────────────────────────────────────────────────────────────


COMMANDS: dict[str, dict] = {
    "/help":         {"fn": _h_help,    "desc": "show command list"},
    "/mem":          {"fn": _h_mem,     "desc": "/mem <query> [--graph] — search memory"},
    "/add":          {"fn": _h_add,     "desc": "/add [--priority X] [--category Y] [--ttl N] <fact>"},
    "/forget":       {"fn": _h_forget,  "desc": "/forget <pattern>"},
    "/snap":         {"fn": _h_snap,    "desc": "/snap [description]"},
    "/roll":         {"fn": _h_roll,    "desc": "/roll <version_id>"},
    "/diff":         {"fn": _h_diff,    "desc": "/diff <a> <b>"},
    "/dedup":        {"fn": _h_dedup,   "desc": "/dedup [--apply]"},
    "/stats":        {"fn": _h_stats,   "desc": "memory stats"},
    "/cost":         {"fn": _h_cost,    "desc": "API token cost summary"},
    "/health":       {"fn": _h_health,  "desc": "memory health check"},
    "/jobs":         {"fn": _h_jobs,    "desc": "list async jobs"},
    "/metrics":      {"fn": _h_metrics, "desc": "show /healthz JSON"},
    "/trace":        {"fn": _h_trace,   "desc": "tracing status"},
    "/pi":           {"fn": _h_pi,      "desc": "/pi  |  /pi suggest"},
    "/profile":      {"fn": _h_profile, "desc": "/profile  |  /profile use <name>"},
    "/use":          {"fn": _h_use,     "desc": "/use <profile>"},
    "/clear":        {"fn": _h_clear,   "desc": "clear screen"},
    "/exit":         {"fn": _h_exit,    "desc": "leave session"},
    "/quit":         {"fn": _h_exit,    "desc": "leave session"},
    # transient flags for the next /graph call
    "/no-mem":       {"fn": _h_no_mem,                 "desc": "next request without memory"},
    "/review":       {"fn": _toggle("review"),         "desc": "next request HITL review"},
    "/parallel":     {"fn": _toggle("parallel"),       "desc": "next request parallel executor"},
    "/tree":         {"fn": _toggle("tree_plan"),      "desc": "next request tree-of-thoughts planner"},
    "/debate":       {"fn": _toggle("debate"),         "desc": "next request debate executor"},
    "/full-mem":     {"fn": _toggle("full_memory"),    "desc": "next request full memory"},
    "/stream":       {"fn": _toggle("stream_review"),  "desc": "next request streaming reviewer"},
    "/edit-plan":    {"fn": _toggle("edit_plan"),      "desc": "next request HITL plan editor"},
}


def _help_text() -> str:
    groups = {
        "Memory":  ["/mem", "/add", "/forget", "/snap", "/roll", "/diff", "/dedup", "/stats"],
        "Graph":   ["/no-mem", "/full-mem", "/review", "/parallel", "/tree", "/debate", "/stream", "/edit-plan"],
        "System":  ["/cost", "/health", "/jobs", "/metrics", "/trace", "/pi"],
        "Profile": ["/profile", "/use"],
        "Misc":    ["/help", "/clear", "/exit"],
    }
    out = []
    for grp, cmds in groups.items():
        out.append(f"\n[{grp}]")
        for c in cmds:
            if c in COMMANDS:
                out.append(f"  {c:<14} {COMMANDS[c]['desc']}")
    return "\n".join(out)


def _shell_capture(cmd: list[str]) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        return (r.stdout or r.stderr or "").strip()
    except Exception as e:
        return f"shell error: {e}"


# ── public dispatcher ──────────────────────────────────────────────────────


def is_slash(text: str) -> bool:
    return text.lstrip().startswith("/") and not text.lstrip().startswith("//")


def dispatch(text: str, ctx: dict) -> Optional[str]:
    """Return the command output string, or None if `text` is not a slash command."""
    if not is_slash(text):
        return None
    text = text.strip()
    if " " in text:
        cmd, args = text.split(" ", 1)
    else:
        cmd, args = text, ""
    cmd = cmd.lower()
    if cmd not in COMMANDS:
        return f"❌ unknown command: {cmd}\n{_help_text()}"
    try:
        return COMMANDS[cmd]["fn"](args, ctx)
    except SystemExit:
        raise
    except Exception as e:
        return f"❌ {cmd} failed: {e}"
