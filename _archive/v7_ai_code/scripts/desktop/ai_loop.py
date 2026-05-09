"""scripts/desktop/ai_loop.py — interactive entry for the "AIM AI" launcher.

Standalone .py (not heredoc) so sys.stdin stays attached to the user's TTY.
Uses prompt_toolkit when available so multi-line PASTE works correctly
(bracketed-paste mode keeps the whole pasted block as one input event,
internal blank lines no longer exit the loop).

Run by ai_loop.sh (Linux/macOS) and ai_loop.bat (Windows).
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

AIM_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(AIM_ROOT))

# user@host:path$  or  user@host:path#  with optional whitespace after.
# Strips an accidentally-pasted shell prompt prefix so the rest is
# treated as natural language, not a shell command.
_SHELL_PROMPT_RE = re.compile(r"^[\w.-]+@[\w.-]+:[^\s$#]*[\$#]\s*")


def _strip_shell_prompt(s: str) -> str:
    return _SHELL_PROMPT_RE.sub("", s, count=1)


_EXIT_CMDS = {"/quit", "/exit", "quit", "exit", ":q"}


def _make_reader():
    """Return a callable that reads one logical user input.

    Multi-line PASTE arrives as a single buffered string (newlines preserved).
    Empty submits return "" — the caller decides what to do (re-prompt, no exit).
    """
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.history import InMemoryHistory
        session = PromptSession(history=InMemoryHistory())

        def read():
            return session.prompt("you> ")
        return read
    except Exception:
        # Fallback: plain input(). Multi-line paste will arrive line-by-line;
        # tell user to use ::: paste-mode block (handled in main()).
        def read():
            return input("you> ")
        return read


def _banner() -> None:
    try:
        from llm import providers_status
        ps = providers_status()
        chain = ps.get("tier_chain", {})
        flags = " · ".join(
            f"{k}{'✓' if ps.get(k) else '✗'}"
            for k in ("anthropic", "gemini", "deepseek", "groq", "ollama")
        )
        print(f"AIM AI assistant  ·  free-form ReAct loop")
        print(f"providers: {flags}")
        print(f"critical-tier model: {chain.get('critical', '?')}")
    except Exception:
        print("AIM AI assistant  ·  free-form ReAct loop")
    print("Type a task and press Enter. /quit OR Ctrl-D = exit.")
    print("Multi-line: paste freely (bracketed paste preserves newlines), or")
    print("type ::: to begin a multi-line block, end the block with another :::")
    print("Tip: ask in any UN-6 language + Georgian, native or translit.")
    print("Heavy audit prompt? raise the iteration cap with /maxiters 40\n")


def _read_paste_block(reader) -> str:
    """Read until a line containing only ':::' is entered."""
    lines: list[str] = []
    while True:
        try:
            ln = reader().rstrip("\r\n")
        except (EOFError, KeyboardInterrupt):
            break
        if ln.strip() == ":::":
            break
        lines.append(ln)
    return "\n".join(lines).strip()


def main() -> int:
    _banner()
    try:
        from agents.generalist import run_streaming
    except Exception as e:
        print(f"FATAL: cannot import generalist: {e}")
        try:
            input("\nPress Enter to close…")
        except Exception:
            pass
        return 2

    reader = _make_reader()

    # Default 25 iters fits most prompts. Heavy audits (long paste with
    # many sections) may need more — user can bump with /maxiters N.
    max_iters = int(os.environ.get("AIM_MAX_ITERS", "25"))

    while True:
        try:
            raw = reader()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        # Strip shell prompt (accidentally-pasted "user@host:~$ ")
        task = _strip_shell_prompt(raw).strip()

        if task in _EXIT_CMDS:
            break
        if task.startswith("/maxiters"):
            parts = task.split()
            if len(parts) == 2 and parts[1].isdigit():
                max_iters = max(1, min(100, int(parts[1])))
                print(f"  max_iters = {max_iters}")
            else:
                print(f"  current max_iters = {max_iters}; usage: /maxiters N")
            continue
        if task == ":::":
            task = _read_paste_block(reader)
            task = _strip_shell_prompt(task).strip()
            if not task:
                continue
        if not task:
            # Empty input: just re-prompt, never exit. (Was: exit.)
            continue

        # Stream events live so the user sees progress, not a 2-min wall.
        answer = ""
        tools_used: list[str] = []
        try:
            for ev in run_streaming(task, max_iters=max_iters):
                et = ev.get("type")
                if et == "start":
                    flag = "  [critical]" if ev.get("critical") else ""
                    print(f"  ⏳ thinking…{flag}")
                elif et == "tool_call":
                    kind = "‖" if ev.get("parallel") else "→"
                    args = ev.get("args") or {}
                    short = ", ".join(f"{k}={str(v)[:40]}"
                                       for k, v in list(args.items())[:3])
                    print(f"  {kind} {ev['tool']}({short})")
                elif et == "tool_result":
                    tools_used.append(ev["tool"])
                    flag = "✓" if ev.get("ok") else "✗"
                    cached = " (cached)" if ev.get("cached") else ""
                    preview = (ev.get("result_preview") or "")[:120]
                    print(f"    {flag} {ev['tool']}{cached}: {preview}")
                elif et == "self_critique_start":
                    print("  · self-critique…")
                elif et == "self_critique_failed":
                    print(f"  ✗ critique flagged issues — regenerating")
                elif et == "self_critique_passed":
                    print("  ✓ critique passed")
                elif et == "stuck_aborted":
                    print(f"  ✗ stuck-loop aborted")
                elif et == "interrupted":
                    print("  ✗ interrupted")
                elif et == "final":
                    answer = ev.get("answer", "")
                elif et == "error":
                    print(f"  ! error: {ev.get('error')}")
        except KeyboardInterrupt:
            print("\n  (interrupted by Ctrl-C)")
            continue
        except Exception as e:
            print(f"  ! generalist error: {e}")
            continue

        print()
        print(answer or "(no answer)")
        print()
        if tools_used:
            print(f"  tools used: {', '.join(tools_used)}")
        print()

    print("bye.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
