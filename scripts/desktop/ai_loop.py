"""scripts/desktop/ai_loop.py — interactive entry for the "AIM AI" launcher.

This is a standalone .py file (NOT inlined into a shell heredoc) so that
sys.stdin stays attached to the user's terminal — heredoc-based entry
breaks input() because stdin is already exhausted by the heredoc.

Run by ai_loop.sh (Linux/macOS) and ai_loop.bat (Windows).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

AIM_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(AIM_ROOT))


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
    print("Type a task and press Enter. Empty line OR /quit OR Ctrl-D = exit.")
    print("Tip: ask in Russian/English/Georgian — provider tier chooses model.\n")


def main() -> int:
    _banner()
    try:
        from agents.generalist import run_streaming
    except Exception as e:
        print(f"FATAL: cannot import generalist: {e}")
        input("\nPress Enter to close…")
        return 2

    while True:
        try:
            task = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not task or task.lower() in ("/quit", "/exit", "quit", "exit"):
            break

        # Stream events live so the user sees progress, not a 2-min wall.
        answer = ""
        tools_used: list[str] = []
        try:
            for ev in run_streaming(task, max_iters=12):
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
