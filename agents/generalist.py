"""agents/generalist.py — tool-using executor (Claude-style agency).

Replaces the rigid Planner→Executor→Reviewer LangGraph 3-node loop with a
free-form ReAct-style cycle:

    while not done:
        next_action = LLM(history)
        if next_action is "final":
            return answer
        result = run_tool(next_action)
        history.append(result)

The LLM is DeepSeek-V4 (cloud, default per user 2026-04-30). Tools wrap
the existing AIM stack: read/edit/bash, memory_recall/save, doctor delegate,
writer delegate, researcher delegate, kernel_check, citation_verify.

Public API:
    run(task, *, max_iters=10, kernel=True, model_hint=None) → dict
        returns {"answer": str, "trace": [...], "tools_used": [...]}
"""
from __future__ import annotations

import json
import logging
import os
import shlex
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from llm import ask, ask_deep, ask_long, ask_critical

log = logging.getLogger("aim.generalist")


# ── Tool registry ──────────────────────────────────────────────────────────


@dataclass
class Tool:
    name: str
    description: str
    fn: Callable[..., Any]
    schema: dict = field(default_factory=dict)


_TOOLS: dict[str, Tool] = {}


def register_tool(name: str, description: str, schema: dict):
    def deco(fn):
        _TOOLS[name] = Tool(name=name, description=description, fn=fn, schema=schema)
        return fn
    return deco


# ── Built-in tools (file I/O, bash, memory, agents, kernel) ────────────────


@register_tool(
    "read_file",
    "Read a UTF-8 text file. Returns first 6000 chars; pass offset/limit to page.",
    {"path": "absolute path", "offset": "int line start (default 0)",
     "limit": "int line count (default 200)"},
)
def _t_read_file(path: str, offset: int = 0, limit: int = 200) -> str:
    p = Path(path).expanduser()
    if not p.exists():
        return f"ERROR: not found: {p}"
    text = p.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    sl = lines[offset:offset + limit]
    return "\n".join(sl)[:6000]


@register_tool(
    "write_file",
    "Write text to a file (overwrites). Returns 'OK <bytes>' on success.",
    {"path": "absolute path", "content": "text to write"},
)
def _t_write_file(path: str, content: str) -> str:
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"OK {len(content)} bytes → {p}"


@register_tool(
    "edit_file",
    "Replace one occurrence of old_text with new_text in the file. old_text must be unique.",
    {"path": "abs path", "old_text": "exact match", "new_text": "replacement"},
)
def _t_edit_file(path: str, old_text: str, new_text: str) -> str:
    p = Path(path).expanduser()
    if not p.exists():
        return f"ERROR: not found: {p}"
    content = p.read_text(encoding="utf-8")
    occ = content.count(old_text)
    if occ == 0:
        return "ERROR: old_text not found"
    if occ > 1:
        return f"ERROR: old_text occurs {occ} times; provide more context to make it unique"
    p.write_text(content.replace(old_text, new_text, 1), encoding="utf-8")
    return f"OK 1 replacement"


@register_tool(
    "apply_patch",
    "Apply a unified diff to one or more files atomically (uses `patch -p0` or git apply). Format: standard `--- a/file` / `+++ b/file` headers. Either all hunks apply or none do.",
    {"diff": "unified-diff text including file headers and @@ hunks",
     "strip": "int (default 0; pass 1 if diff has a/ and b/ prefixes)"},
)
def _t_apply_patch(diff: str, strip: int = 0) -> str:
    if not diff.strip():
        return "ERROR: empty diff"
    if "@@" not in diff:
        return "ERROR: not a unified diff (no @@ hunk markers)"
    # Try `git apply` first if available — better error messages, preserves
    # mode bits, supports binary diffs.
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".diff", delete=False) as f:
        f.write(diff if diff.endswith("\n") else diff + "\n")
        tmp = f.name
    try:
        # Try git apply --check first (no side-effects) to validate
        check = subprocess.run(["git", "apply", "--check",
                                f"-p{strip}", tmp],
                                capture_output=True, text=True)
        if check.returncode == 0:
            do = subprocess.run(["git", "apply", f"-p{strip}", tmp],
                                capture_output=True, text=True)
            if do.returncode == 0:
                return f"OK applied via git apply (-p{strip})"
            return f"ERROR: git apply failed: {do.stderr.strip()}"
        # Fall back to standard `patch`
        do = subprocess.run(["patch", f"-p{strip}", "-N", "-i", tmp],
                            capture_output=True, text=True)
        if do.returncode == 0:
            return f"OK applied via patch -p{strip}\n{do.stdout.strip()[:1000]}"
        return (f"ERROR: patch failed (rc={do.returncode}): "
                f"{do.stdout.strip()}\n{do.stderr.strip()}")[:2000]
    finally:
        Path(tmp).unlink(missing_ok=True)


@register_tool(
    "glob",
    "Glob for files matching a shell pattern (e.g. 'agents/*.py' or '**/*.md'). Returns up to 200 paths.",
    {"pattern": "glob pattern", "root": "optional root directory (default cwd)"},
)
def _t_glob(pattern: str, root: str = ".") -> str:
    from pathlib import Path as _P
    base = _P(root).expanduser().resolve()
    if not base.is_dir():
        return f"ERROR: not a directory: {base}"
    matches = sorted(str(p) for p in base.glob(pattern) if p.exists())[:200]
    return "\n".join(matches) or "(no matches)"


@register_tool(
    "grep",
    "Search for a regex pattern across files. Uses ripgrep if available, else Python re. Returns matches with file:line:text.",
    {"pattern": "regex (Python or POSIX-extended)", "path": "directory or file (default '.')",
     "max_results": "int default 100"},
)
def _t_grep(pattern: str, path: str = ".", max_results: int = 100) -> str:
    rg = subprocess.run(["which", "rg"], capture_output=True, text=True)
    if rg.returncode == 0 and rg.stdout.strip():
        out = subprocess.run(["rg", "--no-heading", "--line-number",
                               "-m", str(max_results), pattern, path],
                             capture_output=True, text=True, timeout=15)
        return (out.stdout.strip() or "(no matches)")[:6000]
    # Pure-Python fallback
    import re as _re
    try:
        rgx = _re.compile(pattern)
    except _re.error as e:
        return f"ERROR: bad regex — {e}"
    base = Path(path).expanduser()
    files = [base] if base.is_file() else \
            [p for p in base.rglob("*") if p.is_file() and p.stat().st_size < 5_000_000]
    out: list[str] = []
    for f in files:
        try:
            for i, line in enumerate(f.read_text(encoding="utf-8",
                                                  errors="replace").splitlines(), 1):
                if rgx.search(line):
                    out.append(f"{f}:{i}:{line[:200]}")
                    if len(out) >= max_results:
                        return "\n".join(out)[:6000]
        except Exception:
            continue
    return "\n".join(out)[:6000] or "(no matches)"


@register_tool(
    "bash",
    "Run a shell command (whitelisted: ls, cat, head, tail, wc, grep, find, git status/log/diff, python3 -c, pytest). Returns stdout+stderr (truncated).",
    {"command": "shell command string"},
)
def _t_bash(command: str) -> str:
    allow = ("ls", "cat", "head", "tail", "wc", "grep", "find",
             "git", "python", "python3", "pytest", "pip", "echo",
             "diff", "stat", "file", "which")
    first = (shlex.split(command) or [""])[0].split("/")[-1]
    if first not in allow:
        return f"ERROR: command '{first}' not whitelisted; allowed: {allow}"
    proc = subprocess.run(command, shell=True, capture_output=True,
                          text=True, timeout=60)
    out = (proc.stdout + proc.stderr).strip()
    return out[:4000] + ("\n[…truncated]" if len(out) > 4000 else "")


@register_tool(
    "memory_recall",
    "Semantic search over Claude memory + cross-project Desktop memory. Returns top-k passages.",
    {"query": "string", "k": "int default 6"},
)
def _t_memory_recall(query: str, k: int = 6) -> str:
    try:
        from agents.memory_index import retrieve
        hits = retrieve(query, k=k)
    except Exception as e:
        return f"ERROR: memory_index unavailable: {e}"
    if not hits:
        return "(no hits)"
    out = []
    for h in hits[:k]:
        out.append(f"— {h.get('file','?')}\n  {h.get('text','')[:300]}")
    return "\n".join(out)


@register_tool(
    "memory_save",
    "Save a short atomic fact to user's auto-memory. Use for explicit user instructions to remember.",
    {"text": "fact to remember", "category": "str default 'general'"},
)
def _t_memory_save(text: str, category: str = "general") -> str:
    try:
        from agents.memory_store import remember
        path = remember(text, category=category, quiet=True)
        return f"OK saved → {Path(str(path)).name}"
    except Exception as e:
        return f"ERROR: {e}"


@register_tool(
    "web_search",
    "Search the web (DuckDuckGo, no API key). Returns list of {title, url, snippet}. Use for grants, news, anything outside PubMed.",
    {"query": "search query string", "n": "int default 8"},
)
def _t_web_search(query: str, n: int = 8) -> str:
    from tools.web import web_search
    hits = web_search(query, n=n)
    return json.dumps(hits, ensure_ascii=False)[:6000]


@register_tool(
    "web_fetch",
    "Fetch a URL, strip HTML to plain text. Returns up to ~8000 chars of readable content.",
    {"url": "absolute URL", "max_chars": "int default 8000"},
)
def _t_web_fetch(url: str, max_chars: int = 8000) -> str:
    from tools.web import web_fetch
    return web_fetch(url, max_chars=max_chars)


@register_tool(
    "view_image",
    "Look at a PNG/JPG/PDF page and answer a question about it. Native vision via Claude or DS-V4 (OCR as last-resort fallback).",
    {"path": "absolute path to image or PDF",
     "prompt": "what to look for / question",
     "page": "PDF page number (0-indexed, default 0)"},
)
def _t_view_image(path: str, prompt: str, page: int = 0) -> str:
    from tools.vision import see
    return see(path, prompt, page=page)


@register_tool(
    "verify_pmid",
    "Look up a PMID at PubMed. Returns metadata or ERROR if it does not exist.",
    {"pmid": "string of digits"},
)
def _t_verify_pmid(pmid: str) -> str:
    from tools.literature import verify_pmid
    rec = verify_pmid(pmid)
    return json.dumps(rec, ensure_ascii=False) if rec else f"ERROR: PMID {pmid} not found at PubMed"


@register_tool(
    "verify_doi",
    "Look up a DOI at Crossref. Returns metadata or ERROR if it does not exist.",
    {"doi": "DOI string (e.g. 10.1126/sciadv.adh2560)"},
)
def _t_verify_doi(doi: str) -> str:
    from tools.literature import verify_doi
    rec = verify_doi(doi)
    return json.dumps(rec, ensure_ascii=False) if rec else f"ERROR: DOI {doi} not found at Crossref"


@register_tool(
    "search_pubmed",
    "Search PubMed and return up to n verified records. Each record is real.",
    {"query": "string", "n": "int default 8"},
)
def _t_search_pubmed(query: str, n: int = 8) -> str:
    from tools.literature import pubmed_search
    rows = pubmed_search(query, n=n)
    return json.dumps(rows, ensure_ascii=False)[:6000]


@register_tool(
    "delegate_doctor",
    "Delegate a clinical task to DoctorAgent (diagnose/treatment/labs). Returns the doctor's response.",
    {"action": "diagnose|treatment|labs|chat", "input": "free text"},
)
def _t_delegate_doctor(action: str, input: str) -> str:
    try:
        from agents.doctor import DoctorAgent
        d = DoctorAgent()
        fn = {"diagnose": d.diagnose, "treatment": d.treatment,
              "labs": d.interpret_labs, "chat": d.chat}.get(action)
        if not fn:
            return f"ERROR: unknown doctor action '{action}'"
        return fn(input)
    except Exception as e:
        return f"ERROR: doctor delegation failed: {e}"


@register_tool(
    "delegate_writer",
    "Delegate a writing task: peer-review, edit, cover letter, response-to-reviewers, md→docx.",
    {"action": "review|edit|cover_letter|response|md_to_docx",
     "args": "dict of parameters"},
)
def _t_delegate_writer(action: str, args: dict) -> str:
    from agents import writer as W
    args = args or {}
    try:
        if action == "review":
            return W.review(args["text"], focus=args.get("focus", "peer-review"),
                            lang=args.get("lang", "en"))
        if action == "edit":
            return W.edit(args["text"], mode=args.get("mode", "tighten"),
                          lang=args.get("lang", "en"))
        if action == "cover_letter":
            return W.cover_letter(args["manuscript"], args["journal"],
                                  author=args.get("author", "Jaba Tkemaladze"),
                                  lang=args.get("lang", "en"))
        if action == "response":
            return W.response_to_reviewers(args["manuscript"], args["reviews"],
                                           lang=args.get("lang", "en"))
        if action == "md_to_docx":
            out = W.md_to_docx(args["md"], args["docx"])
            return f"OK → {out}"
    except Exception as e:
        return f"ERROR: writer.{action} failed: {e}"
    return f"ERROR: unknown writer action '{action}'"


@register_tool(
    "delegate_email",
    "Gmail operations: list/search threads, read thread, draft, or send. send requires explicit user_confirmed=True.",
    {"action": "list|search|get|draft|send|labels",
     "args": "dict — see agents.email_agent docstring"},
)
def _t_delegate_email(action: str, args: dict | None = None) -> str:
    from agents import email_agent as E
    args = args or {}
    try:
        if action == "list":
            return json.dumps(E.list_threads(q=args.get("q", "newer_than:7d"),
                                              n=args.get("n", 20)),
                              ensure_ascii=False)[:6000]
        if action == "search":
            return json.dumps(E.search(args["query"], n=args.get("n", 20)),
                              ensure_ascii=False)[:6000]
        if action == "get":
            t = E.get_thread(args["thread_id"])
            # truncate giant payload
            return json.dumps({"id": t.get("id"),
                               "n": len(t.get("messages", [])),
                               "snippet": t.get("snippet", "")},
                              ensure_ascii=False)
        if action == "draft":
            r = E.draft(args["to"], args["subject"], args["body"],
                        thread_id=args.get("thread_id"),
                        cc=args.get("cc"), bcc=args.get("bcc"))
            return f"DRAFT created: id={r.get('id')}"
        if action == "send":
            r = E.send(args["to"], args["subject"], args["body"],
                       thread_id=args.get("thread_id"),
                       cc=args.get("cc"), bcc=args.get("bcc"),
                       user_confirmed=bool(args.get("user_confirmed")))
            return f"SENT id={r.get('id')} threadId={r.get('threadId')}"
        if action == "labels":
            return json.dumps(E.list_labels(), ensure_ascii=False)[:4000]
    except PermissionError as e:
        return f"BLOCKED by kernel: {e}"
    except Exception as e:
        return f"ERROR: email.{action} failed: {e}"
    return f"ERROR: unknown email action '{action}'"


@register_tool(
    "delegate_coder",
    "Delegate code-edits to CoderAgent (Aider wrap + edit-then-test loop). For one-shot edits OR iterate-until-tests-pass.",
    {"files": "list of file paths to edit",
     "instruction": "natural-language edit task",
     "test_cmd": "optional shell test command (e.g. 'pytest tests/test_x.py -q'); when given, runs edit→test→fix loop",
     "max_iters": "int default 3 (only used when test_cmd is set)"},
)
def _t_delegate_coder(files: list[str], instruction: str,
                      test_cmd: Optional[str] = None,
                      max_iters: int = 3) -> str:
    from agents.coder import CoderAgent
    try:
        agent = CoderAgent(files)
        if test_cmd:
            res = agent.edit_and_test(instruction, test_cmd, max_iters=max_iters)
            tail = res.last_test[-1500:]
            return (f"ok={res.ok} iters={res.iters}\n"
                    f"--- last test output ---\n{tail}")
        return agent.edit(instruction)[:6000]
    except Exception as e:
        return f"ERROR: coder.delegate failed: {e}"


@register_tool(
    "delegate_researcher",
    "Literature search & summarisation with hard PMID/DOI verification.",
    {"action": "find|summarise|verify_text|formulate_queries", "args": "dict"},
)
def _t_delegate_researcher(action: str, args: dict) -> str:
    from agents import researcher as R
    args = args or {}
    try:
        if action == "find":
            rows = R.find(args["query"], n=args.get("n", 10),
                          source=args.get("source", "pubmed"))
            return json.dumps(rows, ensure_ascii=False)[:6000]
        if action == "summarise":
            return R.summarise(args["records"], args.get("focus", ""),
                               lang=args.get("lang", "en"))
        if action == "verify_text":
            rep = R.verify_text(args["text"], mode=args.get("mode", "annotate"))
            return rep.summary() + "\n\n" + rep.text[:4000]
        if action == "formulate_queries":
            return json.dumps(R.formulate_queries(args["topic"],
                              n=args.get("n", 5)), ensure_ascii=False)
    except Exception as e:
        return f"ERROR: researcher.{action} failed: {e}"
    return f"ERROR: unknown researcher action '{action}'"


@register_tool(
    "delegate_parallel",
    "Spawn N independent generalist sub-runs and synthesize their answers. Use for fan-out (e.g. peer-review each section in parallel).",
    {"tasks": "list of task strings (each will run in its own generalist)",
     "max_iters": "int per sub-run (default 6)",
     "synthesise": "if True, ask LLM to merge results into one answer (default True)"},
)
def _t_delegate_parallel(tasks: list[str], max_iters: int = 6,
                         synthesise: bool = True) -> str:
    if not isinstance(tasks, list) or not tasks:
        return "ERROR: tasks must be a non-empty list of strings"
    results: list[str] = [""] * len(tasks)
    with ThreadPoolExecutor(max_workers=min(len(tasks), 4)) as pool:
        futs = {pool.submit(run, t, max_iters=max_iters, speculative=False): i
                for i, t in enumerate(tasks)}
        for fut in as_completed(futs):
            i = futs[fut]
            try:
                results[i] = fut.result().get("answer", "")
            except Exception as e:
                results[i] = f"[sub-task failed: {e}]"
    if not synthesise:
        return json.dumps([{"task": t, "answer": r}
                           for t, r in zip(tasks, results)],
                          ensure_ascii=False)[:6000]
    blocks = "\n\n".join(f"=== Sub-task {i+1}: {tasks[i]} ===\n{results[i]}"
                         for i in range(len(tasks)))
    syn_prompt = (
        "You are synthesising parallel sub-task results into one coherent "
        "answer. Quote only the substance; remove redundancy; preserve every "
        "factual claim that appeared in any sub-result.\n\n" + blocks
    )
    try:
        from llm import ask_critical as _ask
    except Exception:
        from llm import ask_deep as _ask
    return _ask(syn_prompt)


@register_tool(
    "kernel_check",
    "Pre-action check: pass a Decision payload, get L_PRIVACY/L_CONSENT/L_VERIFIABILITY verdict.",
    {"action_type": "string (e.g. email_send, git_push_public, emit_text)",
     "payload": "dict",
     "context": "dict (e.g. {'user_confirmed': true})"},
)
def _t_kernel_check(action_type: str, payload: dict, context: dict | None = None) -> str:
    from agents.kernel import Decision, evaluate_extended
    d = Decision(id="adhoc", description=str(payload)[:80],
                 action_type=action_type, payload=payload or {})
    res = evaluate_extended(d, patient={}, context=context or {})
    return json.dumps({
        "passed": res.passed,
        "privacy": res.privacy, "consent": res.consent,
        "verifiability": res.verifiability,
        "reasons": res.reasons,
    }, ensure_ascii=False)


# ── Tool-loop driver ───────────────────────────────────────────────────────


SYSTEM_PROMPT = """You are AIM Generalist — a tool-using assistant for Jaba Tkemaladze
(Georgia Longevity Alliance). You have access to local files, AIM's medical
agents, a literature verifier (PubMed/Crossref), and a decision kernel.

PROTOCOL — reply with EXACTLY ONE JSON object on a single line, NOTHING ELSE:

  Single tool:
    { "tool": "<tool_name>", "args": { ... } }

  Parallel tools (independent — run concurrently for speed):
    { "parallel": [
        { "tool": "<name>", "args": { ... } },
        { "tool": "<name>", "args": { ... } }
      ]
    }

  Final answer:
    { "final": "<answer to the user>" }

PARALLELISM RULE:
  Use "parallel" ONLY when the calls are truly independent (no call needs
  the output of another). Examples that ARE parallel:
    • verify_pmid for 5 different PMIDs at once
    • read_file for 3 different paths
    • memory_recall + search_pubmed simultaneously
  Examples that are NOT parallel (use single tool steps):
    • read_file then edit_file the same file
    • search_pubmed then verify_pmid on a result of the search

ABSOLUTE RULES:
  1. NEVER fabricate a PMID or DOI. If you reference one, you MUST first
     call verify_pmid / verify_doi. Unverified citations break the law and
     will be auto-stripped.
  2. Before any side-effect with external blast radius (email_send,
     git_push_public, telegram_broadcast), call kernel_check. If consent
     not granted, ask the user before proceeding.
  3. Patient data NEVER leaves the machine in tool calls.
  4. Russian/English/Georgian — match the user's language.
  5. Keep outputs concise. Prefer pointed answers over walls of text.
"""


def _format_tools_block() -> str:
    rows = []
    for t in _TOOLS.values():
        schema_str = ", ".join(f"{k}: {v}" for k, v in t.schema.items())
        rows.append(f"  {t.name}({schema_str})  — {t.description}")
    return "AVAILABLE TOOLS:\n" + "\n".join(rows)


def run(task: str, *, max_iters: int = 10, kernel: bool = True,
        model_hint: Optional[str] = None,
        speculative: bool = True,
        critique: bool = True,
        ensemble: bool = True,
        on_event: Optional[Callable[[dict], None]] = None) -> dict:
    """Tool-agency cycle. Returns dict with answer + trace.

    Args:
        speculative: background prefetch of likely tools while LLM thinks.
        critique:    on critical tasks, run a self-critique pass on `final`
                     and regenerate once if material flaws are found.
        ensemble:    on critical tasks, route the FIRST plan via ensemble
                     (3 models in parallel + adjudication) for grounding.
    """
    history: list[dict] = [{"role": "user", "content": task}]
    trace: list[dict] = []
    tools_used: list[str] = []
    critical = False
    try:
        from agents.ensemble import is_critical as _is_crit
        critical = _is_crit(task)
    except Exception:
        pass

    def emit(ev: dict) -> None:
        if on_event:
            try:
                on_event(ev)
            except Exception as _e:
                log.debug(f"on_event callback raised: {_e}")

    emit({"type": "start", "task": task, "critical": critical})

    pf = None
    if speculative:
        try:
            from agents.speculative_prefetch import Prefetcher
            pf = Prefetcher()
        except Exception as e:
            log.debug(f"prefetcher disabled: {e}")

    sys_prompt = SYSTEM_PROMPT + "\n\n" + _format_tools_block()

    # On critical tasks, use ensemble to ground the first plan across providers.
    if critical and ensemble:
        try:
            from agents.ensemble import ensemble_ask
            res = ensemble_ask(
                "Outline (5-10 numbered bullets) the strongest plan to "
                "accomplish this task. Be concrete; mention which AIM tools "
                f"are needed. Task: {task}",
                system="You are a planning advisor for a tool-using agent.")
            history.append({"role": "tool", "name": "_ensemble_plan",
                            "result": ("ENSEMBLE PLAN "
                                f"(consensus={res.get('consensus')}, "
                                f"agreement={res.get('agreement')}):\n"
                                + (res.get("answer") or "")[:3000])})
            tools_used.append("ensemble_plan")
            trace.append({"iter": -1, "ensemble": {
                "consensus": res.get("consensus"),
                "agreement": res.get("agreement"),
                "adjudicator": res.get("adjudicator"),
            }})
        except Exception as e:
            log.warning(f"ensemble plan skipped: {e}")

    for it in range(max_iters):
        if pf is not None:
            pf.observe(history)
        history = _maybe_compact(history)
        # A1: native messages[] with strict JSON mode (DS/Gemini/Groq) —
        # better prefix-cache hit, fewer parse failures. Synthetic prompt
        # is used only for the deep-reasoning path or as a fallback.
        if it == 0 or "research" in task.lower() or "review" in task.lower():
            # Deep path: use synthetic prompt because DS-reasoner doesn't
            # always honour response_format on the first reasoning turn.
            prompt = _render_for_llm(history)
            raw = ask_deep(prompt, system=sys_prompt)
        else:
            msgs = _render_messages(history, sys_prompt)
            raw = _llm_call_msgs(msgs)
            if not raw:
                # Cloud unreachable → fall back to synthetic prompt + ask()
                prompt = _render_for_llm(history)
                raw = ask(prompt, system=sys_prompt)
        action = _parse_action(raw)
        trace.append({"iter": it, "raw": raw[:500], "action": action})

        # Parse failure → feed error back, retry
        if not action:
            log.warning("generalist: invalid JSON from LLM; retrying")
            history.append({"role": "tool", "name": "_parser",
                            "result": "ERROR: previous reply was not valid JSON. "
                                      "Reply with EXACTLY one JSON object: "
                                      '{"tool": "...", "args": {...}} '
                                      'OR {"parallel": [...]} OR {"final": "..."}'})
            continue

        if "final" in action:
            final_text = action["final"]
            if critical and critique and final_text and not action.get("_critiqued"):
                emit({"type": "self_critique_start"})
                fix = _self_critique(task, final_text)
                if fix:
                    log.info("generalist: self-critique surfaced flaws; regenerating")
                    emit({"type": "self_critique_failed",
                          "preview": fix[:200]})
                    history.append({"role": "tool", "name": "_self_critique",
                                    "result": "CRITIQUE OF YOUR DRAFT FINAL:\n"
                                              + fix[:2000]
                                              + "\nPlease emit a corrected final."})
                    tools_used.append("self_critique")
                    continue
                emit({"type": "self_critique_passed"})
            if pf is not None:
                pf.shutdown()
            emit({"type": "final", "answer": final_text,
                  "tools_used": tools_used, "iters": it + 1})
            return {"answer": final_text, "trace": trace,
                    "tools_used": tools_used, "iters": it + 1}

        # Parallel tool calls — fan-out concurrently
        if isinstance(action.get("parallel"), list) and action["parallel"]:
            calls = action["parallel"]
            for c in calls:
                emit({"type": "tool_call", "tool": c.get("tool"),
                      "args": c.get("args"), "parallel": True})
            results = _run_tools_parallel(calls)
            for call, result in zip(calls, results):
                tname = call.get("tool", "?")
                tools_used.append(f"{tname}*")
                history.append({"role": "tool", "name": tname,
                                "result": str(result)[:4000]})
                emit({"type": "tool_result", "tool": tname,
                      "ok": not str(result).startswith("ERROR"),
                      "result_preview": str(result)[:200]})
            continue

        # Single tool call
        tool = action.get("tool")
        args = action.get("args") or {}
        if tool not in _TOOLS:
            history.append({"role": "tool", "name": tool or "?",
                            "result": f"ERROR: unknown tool '{tool}'. "
                                      f"Available: {list(_TOOLS)}"})
            emit({"type": "tool_error", "tool": tool, "reason": "unknown"})
            continue
        tools_used.append(tool)
        emit({"type": "tool_call", "tool": tool, "args": args, "parallel": False})
        cached = pf.consume(tool, args) if pf is not None else None
        if cached is not None:
            tools_used[-1] = f"{tool}+spec"
            result = cached
            emit({"type": "tool_result", "tool": tool, "cached": True,
                  "ok": not str(result).startswith("ERROR"),
                  "result_preview": str(result)[:200]})
        else:
            result = _run_one_tool(tool, args)
            emit({"type": "tool_result", "tool": tool, "cached": False,
                  "ok": not str(result).startswith("ERROR"),
                  "result_preview": str(result)[:200]})
        history.append({"role": "tool", "name": tool, "result": str(result)[:4000]})

    if pf is not None:
        pf.shutdown()
    return {"answer": "[max iterations reached without final answer]",
            "trace": trace, "tools_used": tools_used, "iters": max_iters}


def run_streaming(task: str, **kwargs):
    """Generator wrapper that yields events as the generalist works.

    Usage:
        for ev in run_streaming("задача"):
            if ev["type"] == "tool_call":  print(f"  → {ev['tool']}")
            elif ev["type"] == "final":    print(ev["answer"])
    """
    import threading
    import queue as _queue
    q: _queue.Queue = _queue.Queue()
    DONE = object()

    def _emit(ev: dict) -> None:
        q.put(ev)

    def _worker():
        try:
            run(task, on_event=_emit, **kwargs)
        except Exception as e:
            q.put({"type": "error", "error": str(e)})
        finally:
            q.put(DONE)

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    while True:
        ev = q.get()
        if ev is DONE:
            return
        yield ev


def _run_one_tool(tool: str, args: Any) -> str:
    if tool not in _TOOLS:
        return f"ERROR: unknown tool '{tool}'"
    try:
        if isinstance(args, dict):
            return str(_TOOLS[tool].fn(**args))
        return str(_TOOLS[tool].fn(args))
    except TypeError as e:
        return f"ERROR: bad arguments to {tool} — {e}"
    except Exception as e:
        return f"ERROR: {tool} raised: {e}"


def _run_tools_parallel(calls: list[dict], max_workers: int = 6) -> list[str]:
    """Run multiple independent tool calls concurrently. Order preserved."""
    out = [""] * len(calls)
    if not calls:
        return out
    with ThreadPoolExecutor(max_workers=min(max_workers, len(calls))) as pool:
        futs = {pool.submit(_run_one_tool, c.get("tool", ""), c.get("args") or {}): i
                for i, c in enumerate(calls)}
        for fut in as_completed(futs):
            out[futs[fut]] = fut.result()
    return out


_CRITIQUED_TASKS: set[str] = set()


def _self_critique(task: str, draft: str) -> str:
    """Adversarial review of a draft final. Returns critique text only when
    the reviewer flags MATERIAL flaws (≥1 of: missing fact, unsupported
    claim, fabricated citation, factually wrong, harmful advice). One-shot
    only per task — `_CRITIQUED_TASKS` ensures we don't loop."""
    key = task[:200]
    if key in _CRITIQUED_TASKS:
        return ""
    _CRITIQUED_TASKS.add(key)
    crit_sys = (
        "You are an adversarial reviewer. Your job is to find MATERIAL flaws "
        "in the draft answer below. Material flaw = wrong fact, unsupported "
        "claim, fabricated PMID/DOI, harmful or unsafe advice, missing key "
        "constraint from the user request. Do NOT nitpick style.\n"
        "Output: if the draft is acceptable, reply EXACTLY with the literal "
        "string OK and nothing else. Otherwise list flaws as numbered bullets, "
        "each flaw 1-2 lines.")
    crit_prompt = (f"USER TASK: {task}\n\n=== DRAFT FINAL ANSWER ===\n{draft}\n=== END ===")
    try:
        verdict = ask_critical(crit_prompt, system=crit_sys).strip()
    except Exception as e:
        log.warning(f"self_critique LLM error: {e}")
        return ""
    if verdict.upper().startswith("OK") and len(verdict) <= 6:
        return ""
    return verdict


def _approx_tokens(history: list[dict]) -> int:
    return sum(len(str(m.get("content", "") or m.get("result", ""))) // 4
               for m in history)


def _maybe_compact(history: list[dict], *, threshold_tokens: int = 30_000,
                   keep_last: int = 4) -> list[dict]:
    """If history grows too large, summarise everything but the last N turns.

    Returns the (possibly-compacted) history list. The summary is inserted
    as a synthetic role='tool' entry named '_compacted'.
    """
    if _approx_tokens(history) < threshold_tokens or len(history) < keep_last + 4:
        return history
    head = history[:-keep_last]
    tail = history[-keep_last:]
    blob = "\n\n".join(
        (f"[{m.get('role')}]" + (f"[{m.get('name')}]" if m.get("name") else "")
         + " " + (m.get("content") or m.get("result") or "")[:1500])
        for m in head
    )
    try:
        from llm import ask_long
        summary = ask_long(
            "Compact the following AIM agent transcript. Preserve every "
            "decision, every tool result that contains a fact the agent will "
            "still need, and every blocked/failed action. Drop verbosity. "
            "Output a numbered list under 1500 tokens.\n\n=== TRANSCRIPT ===\n"
            + blob,
            system="You are a transcript compactor. Be terse and lossless.",
            max_tokens=4096,
        )
    except Exception as e:
        log.warning(f"compaction failed: {e}; truncating instead")
        summary = ("(compaction failed; only most recent turns retained)")
    log.info(f"generalist: compacted {len(head)} earlier turns "
             f"(~{_approx_tokens(head)} tok → {len(summary)//4} tok)")
    return [
        history[0],     # original user task
        {"role": "tool", "name": "_compacted",
         "result": "EARLIER TURNS COMPACTED:\n" + summary},
        *tail,
    ]


def _render_for_llm(history: list[dict]) -> str:
    """Synthetic-prompt fallback (used when provider can't take messages[])."""
    parts = []
    for msg in history:
        role = msg.get("role")
        if role == "user":
            parts.append(f"USER: {msg['content']}")
        elif role == "tool":
            parts.append(f"TOOL[{msg['name']}] →\n{msg['result']}")
        elif role == "assistant":
            parts.append(f"ASSISTANT (you previously): {msg['content'][:1000]}")
    parts.append("\nReply with ONE JSON object: a tool call, parallel batch, OR a final answer.")
    return "\n\n".join(parts)


def _render_messages(history: list[dict], system: str) -> list[dict]:
    """Native OpenAI-compatible messages[] for DeepSeek/Gemini/Groq.
    Tool results become assistant + user pairs (since OpenAI-compat /v1
    surfaces don't always allow standalone role='tool' without prior
    tool_calls). This formulation works on all three providers reliably.
    """
    msgs: list[dict] = [{"role": "system", "content": system}]
    for m in history:
        role = m.get("role")
        if role == "user":
            msgs.append({"role": "user", "content": m["content"]})
        elif role == "assistant":
            msgs.append({"role": "assistant", "content": m["content"]})
        elif role == "tool":
            msgs.append({"role": "user",
                         "content": f"[tool_result:{m.get('name','?')}]\n"
                                    f"{m.get('result','')}"})
    msgs.append({"role": "user",
                 "content": "Reply with ONE JSON object: "
                            '{"tool":...,"args":...} OR '
                            '{"parallel":[...]} OR {"final":"..."}'})
    return msgs


def _llm_call_msgs(messages: list[dict]) -> str:
    """Call DeepSeek-V4-flash with structured messages — better cache hit
    rate and tool-use accuracy than synthetic prompt rendering. Falls back
    to ask() if DS unreachable."""
    from llm import (DEEPSEEK_API_KEY, _deepseek, _breaker_for, _limiter_for,
                      _record_llm_error)
    from config import Models, LLM_TEMPERATURE, LLM_MAX_TOKENS
    if not DEEPSEEK_API_KEY:
        return ""
    _breaker_for("deepseek").before_call()
    _limiter_for("deepseek").acquire()
    try:
        resp = _deepseek().chat.completions.create(
            model=Models.DS_CHAT, messages=messages,
            temperature=LLM_TEMPERATURE, max_tokens=LLM_MAX_TOKENS,
            response_format={"type": "json_object"},
        )
        _breaker_for("deepseek").on_success()
        return resp.choices[0].message.content.strip()
    except Exception as e:
        _breaker_for("deepseek").on_failure()
        _record_llm_error("deepseek", e)
        log.warning(f"DS structured call failed, fallback to ask(): {e}")
        return ""


def _parse_action(raw: str) -> dict:
    """Extract a valid JSON action from the model output. Returns {} on
    parse failure (caller will feed the failure back to the LLM and retry
    instead of treating raw text as a final answer)."""
    raw = raw.strip()
    try:
        return json.loads(raw)
    except Exception:
        pass
    import re as _re
    m = _re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, _re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    # First balanced {...} block
    depth = 0
    start = -1
    for i, ch in enumerate(raw):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    return json.loads(raw[start:i + 1])
                except Exception:
                    start = -1
    return {}   # parse failure — treated explicitly by run()
