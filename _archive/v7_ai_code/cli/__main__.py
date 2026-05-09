"""cli/__main__.py — single command-surface for AIM.

Installed via `pipx install aim-generalist`, the user gets these commands:

    aim init                  — interactive 5-question setup wizard
    aim ai                    — free-form ReAct loop (the AI assistant)
    aim cli                   — full medical menu (medical_system.py)
    aim gui                   — tkinter GUI
    aim web                   — local FastAPI on 127.0.0.1:8080
    aim telegram              — Telegram bot

    aim hub start             — run as multi-user Hub
    aim hub pair <username>   — issue a 6-digit pairing code
    aim hub users             — list / create / disable users
    aim node setup            — interactive: connect to a hub
    aim node status           — show current identity + cached state

    aim doctor                — sanity check: providers, paths, tools

The `aim-hub`, `aim-node`, `aim-ai` console_scripts are thin aliases that
call into the same dispatcher with a fixed first argument.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Allow running from a clone without installing
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ── Sub-commands ────────────────────────────────────────────────────────────


def cmd_ai(args) -> int:
    """Free-form ReAct loop — the canonical 'AIM AI' assistant."""
    from scripts.desktop import ai_loop
    return ai_loop.main()


def cmd_cli(args) -> int:
    """Full medical menu (medical_system.AIM)."""
    from medical_system import AIM
    AIM().run()
    return 0


def cmd_gui(args) -> int:
    from aim_gui import main as gui_main
    gui_main()
    return 0


def cmd_web(args) -> int:
    import os as _os
    _os.environ.setdefault("AIM_ROLE", "node")
    from web.api import _main as web_main
    sys.argv = ["aim-web", "--port", str(args.port)]
    web_main()
    return 0


def cmd_telegram(args) -> int:
    from telegram_bot import main as tg_main
    tg_main()
    return 0


# ── Hub sub-commands ────────────────────────────────────────────────────────


def cmd_hub_start(args) -> int:
    os.environ["AIM_ROLE"] = "hub"
    from web.api import _main as web_main
    sys.argv = ["aim-hub", "--host", args.host, "--port", str(args.port)]
    web_main()
    return 0


def cmd_hub_pair(args) -> int:
    """Issue a 6-digit pairing code valid 5 minutes."""
    from agents import auth, pairing
    u = auth.get_user_by_username(args.username)
    if u is None:
        if args.create:
            import getpass
            pw = (getpass.getpass("password (min 8 chars): ")
                  if not args.password else args.password)
            existing = auth.list_users()
            role = "admin" if not existing else "user"
            u = auth.create_user(args.username, pw, role=role)
            print(f"[+] created user '{args.username}' (role={role})")
        else:
            print(f"ERROR: user '{args.username}' does not exist. "
                  f"Pass --create to create it on the fly.", file=sys.stderr)
            return 2
    code, expires = pairing.issue_pair_code(u["id"], ttl_min=args.ttl)
    print()
    print("┌──────────────────────────────────────────────────────────┐")
    print(f"│  AIM pairing code:    {code:>6}                             │")
    print(f"│  for user:            {u['username']:<30}        │")
    print(f"│  valid for:           {args.ttl} minutes                          │")
    print("│                                                          │")
    print("│  On the user's machine run:                              │")
    print("│      pipx install aim-generalist                         │")
    print(f"│      aim node setup                                     │")
    print("│  paste the code when asked.                              │")
    print("└──────────────────────────────────────────────────────────┘")
    return 0


def cmd_hub_users(args) -> int:
    from agents import auth
    if args.subcmd == "list":
        rows = auth.list_users()
        if not rows:
            print("(no users — create the first admin with `aim hub pair <name> --create`)")
            return 0
        print(f"{'ID':>3}  {'USERNAME':<20} {'ROLE':<6} {'STATE':<8} CREATED")
        for u in rows:
            state = "DISABLED" if u["disabled"] else "active"
            print(f"{u['id']:>3}  {u['username']:<20} {u['role']:<6} {state:<8} {u['created_at']}")
        return 0
    if args.subcmd == "disable":
        u = auth.get_user_by_username(args.username)
        if not u:
            print(f"not found: {args.username}", file=sys.stderr); return 2
        auth.disable_user(u["id"])
        print(f"disabled {args.username}")
        return 0
    if args.subcmd == "enable":
        u = auth.get_user_by_username(args.username)
        if not u:
            print(f"not found: {args.username}", file=sys.stderr); return 2
        auth.enable_user(u["id"])
        print(f"enabled {args.username}")
        return 0
    print(f"unknown subcommand: {args.subcmd}", file=sys.stderr)
    return 2


# ── Node sub-commands ──────────────────────────────────────────────────────


def cmd_node_setup(args) -> int:
    from cli.setup_wizard import run_node_setup
    return run_node_setup(non_interactive=args.non_interactive,
                          hub_url=args.hub_url, code=args.code)


def cmd_node_status(args) -> int:
    from agents import hub_client
    import json
    if hub_client.is_local_only():
        print("AIM_HUB_URL not set — running in local-only mode")
        return 0
    u = hub_client.current_user()
    if u is None:
        print("Not authenticated. Run `aim node setup` to pair this device.")
        return 1
    print(json.dumps(u, indent=2, ensure_ascii=False))
    return 0


# ── Init wizard + doctor ───────────────────────────────────────────────────


def cmd_init(args) -> int:
    from cli.setup_wizard import run_init_wizard
    return run_init_wizard(non_interactive=args.non_interactive)


def cmd_doctor(args) -> int:
    """Sanity check: providers, paths, tools, ollama, db."""
    import json
    from llm import providers_status
    print("─ Providers ─" + "─" * 40)
    print(json.dumps(providers_status(), indent=2))
    print()
    try:
        from agents.generalist import _TOOLS
        print(f"─ Tools registered: {len(_TOOLS)} ─" + "─" * 30)
        for n in sorted(_TOOLS):
            print(f"  • {n}")
    except Exception as e:
        print(f"ERROR loading tools: {e}")
    print()
    try:
        from agents import hub_client
        print(f"─ Hub state ─" + "─" * 40)
        print(f"  AIM_HUB_URL = {os.environ.get('AIM_HUB_URL') or '(not set)'}")
        print(f"  is_local_only = {hub_client.is_local_only()}")
        if not hub_client.is_local_only():
            u = hub_client.current_user()
            print(f"  authenticated as: {u['username'] if u else '(none)'}")
    except Exception as e:
        print(f"ERROR hub_client: {e}")
    return 0


# ── Argparse plumbing ──────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="aim",
        description="AIM — local-first tool-using AI agent for medicine and research")
    sp = p.add_subparsers(dest="cmd", required=True)

    sp.add_parser("init", help="interactive setup wizard").set_defaults(func=cmd_init)
    sp.choices["init"].add_argument("--non-interactive", action="store_true")

    sp.add_parser("ai",       help="free-form ReAct AI assistant").set_defaults(func=cmd_ai)
    sp.add_parser("cli",      help="full medical menu (CLI)").set_defaults(func=cmd_cli)
    sp.add_parser("gui",      help="tkinter GUI").set_defaults(func=cmd_gui)
    sp.add_parser("telegram", help="Telegram bot").set_defaults(func=cmd_telegram)
    sp.add_parser("doctor",   help="sanity check — providers, tools, paths").set_defaults(func=cmd_doctor)

    web = sp.add_parser("web", help="local FastAPI server")
    web.add_argument("--port", type=int, default=8080)
    web.set_defaults(func=cmd_web)

    # hub
    hub = sp.add_parser("hub", help="multi-user Hub commands")
    hub_sp = hub.add_subparsers(dest="hub_cmd", required=True)

    hubs = hub_sp.add_parser("start", help="run AIM as a Hub server")
    hubs.add_argument("--host", default="0.0.0.0")
    hubs.add_argument("--port", type=int, default=8000)
    hubs.set_defaults(func=cmd_hub_start)

    hubp = hub_sp.add_parser("pair", help="issue a 6-digit pairing code")
    hubp.add_argument("username")
    hubp.add_argument("--create", action="store_true",
                      help="create the user if absent (first admin auto-promoted)")
    hubp.add_argument("--password", default=None,
                      help="(non-interactive) password when --create is used")
    hubp.add_argument("--ttl", type=int, default=10, help="minutes (default 10)")
    hubp.set_defaults(func=cmd_hub_pair)

    hubu = hub_sp.add_parser("users", help="list / create / disable users")
    hubu.add_argument("subcmd", choices=["list", "disable", "enable"])
    hubu.add_argument("username", nargs="?")
    hubu.set_defaults(func=cmd_hub_users)

    # node
    node = sp.add_parser("node", help="connect this device to a Hub")
    node_sp = node.add_subparsers(dest="node_cmd", required=True)

    nsetup = node_sp.add_parser("setup", help="pair this device with a hub")
    nsetup.add_argument("--non-interactive", action="store_true")
    nsetup.add_argument("--hub-url", default=None)
    nsetup.add_argument("--code", default=None)
    nsetup.set_defaults(func=cmd_node_setup)

    nst = node_sp.add_parser("status", help="show identity + cached state")
    nst.set_defaults(func=cmd_node_status)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


# Convenience entry-points wired in pyproject.toml

def main_hub() -> int:    return main(["hub"] + sys.argv[1:])
def main_node() -> int:   return main(["node"] + sys.argv[1:])
def main_ai() -> int:     return main(["ai"]   + sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
