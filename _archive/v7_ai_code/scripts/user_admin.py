"""scripts/user_admin.py — admin CLI for the AIM Hub user system.

Run on the hub machine (where AIM_HUB_DB lives). First user created
automatically becomes admin. Cross-platform (Linux/macOS/Windows).

Examples:
    python -m scripts.user_admin create alice               # prompts for password
    python -m scripts.user_admin create alice --role admin
    python -m scripts.user_admin list
    python -m scripts.user_admin token alice                # issue/print api token
    python -m scripts.user_admin revoke-token alice
    python -m scripts.user_admin reset alice                # prompts for new password
    python -m scripts.user_admin disable alice
    python -m scripts.user_admin enable alice
    python -m scripts.user_admin link-code alice            # 6-digit code for /link
    python -m scripts.user_admin nodes                      # show registered nodes
    python -m scripts.user_admin audit --user alice -n 50
"""
from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path

# Allow `python scripts/user_admin.py ...` from AIM root
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents import auth  # noqa: E402


def _resolve_user(name_or_id: str) -> dict:
    if name_or_id.isdigit():
        u = auth.get_user(int(name_or_id))
    else:
        u = auth.get_user_by_username(name_or_id)
    if u is None:
        sys.exit(f"user not found: {name_or_id}")
    return u


def _read_password(confirm: bool = True) -> str:
    pw = getpass.getpass("password: ")
    if confirm:
        pw2 = getpass.getpass("repeat:   ")
        if pw != pw2:
            sys.exit("passwords do not match")
    if len(pw) < 8:
        sys.exit("password must be at least 8 characters")
    return pw


def cmd_create(args) -> int:
    role = args.role
    # Auto-promote: first user is admin unless explicitly told otherwise
    existing = auth.list_users()
    if not existing and role == "user":
        print("[i] first user — auto-promoted to admin")
        role = "admin"
    pw = args.password or _read_password()
    u = auth.create_user(args.username, pw, role=role, email=args.email)
    auth.audit(u["id"], "user.create", target=u["username"])
    print(json.dumps(u, indent=2, default=str))
    return 0


def cmd_list(args) -> int:
    rows = auth.list_users()
    if args.json:
        print(json.dumps(rows, indent=2, default=str))
        return 0
    if not rows:
        print("(no users)")
        return 0
    print(f"{'ID':>3}  {'USERNAME':<20} {'ROLE':<6} {'TG':>10} {'STATE':<8} CREATED")
    for u in rows:
        state = "DISABLED" if u["disabled"] else "active"
        tg = u.get("telegram_id") or "-"
        print(f"{u['id']:>3}  {u['username']:<20} {u['role']:<6} {str(tg):>10} "
              f"{state:<8} {u['created_at']}")
    return 0


def cmd_token(args) -> int:
    u = _resolve_user(args.username)
    tok = auth.issue_api_token(u["id"])
    auth.audit(u["id"], "token.issue")
    print(tok)
    print(f"\n[i] put on the user's machine in ~/.aim_env (or %USERPROFILE%\\.aim_env on Windows):\n"
          f"    AIM_HUB_URL=https://your-hub-host\n"
          f"    AIM_USER_TOKEN={tok}\n", file=sys.stderr)
    return 0


def cmd_revoke_token(args) -> int:
    u = _resolve_user(args.username)
    auth.revoke_api_token(u["id"])
    auth.audit(u["id"], "token.revoke")
    print(f"revoked api token for {u['username']}")
    return 0


def cmd_reset(args) -> int:
    u = _resolve_user(args.username)
    pw = args.password or _read_password()
    auth.set_password(u["id"], pw)
    auth.audit(u["id"], "password.reset")
    print(f"password reset for {u['username']}")
    return 0


def cmd_disable(args) -> int:
    u = _resolve_user(args.username)
    auth.disable_user(u["id"])
    auth.audit(u["id"], "user.disable")
    print(f"disabled {u['username']} (api token revoked)")
    return 0


def cmd_enable(args) -> int:
    u = _resolve_user(args.username)
    auth.enable_user(u["id"])
    auth.audit(u["id"], "user.enable")
    print(f"enabled {u['username']}")
    return 0


def cmd_link_code(args) -> int:
    u = _resolve_user(args.username)
    code = auth.create_link_code(u["id"], ttl_min=args.ttl)
    print(code)
    print(f"\n[i] tell the user to send this to the Telegram bot:\n"
          f"    /link {code}\n"
          f"    (valid for {args.ttl} minutes)", file=sys.stderr)
    return 0


def cmd_nodes(args) -> int:
    rows = auth.list_nodes()
    if args.json:
        print(json.dumps(rows, indent=2, default=str))
        return 0
    if not rows:
        print("(no nodes have phoned home yet)")
        return 0
    print(f"{'USER':<20} {'NODE_ID':<20} {'HOST':<25} {'VER':<8} LAST_SEEN")
    for n in rows:
        print(f"{n.get('username', '?'):<20} {n['node_id']:<20} "
              f"{(n.get('host') or '-'):<25} {(n.get('version') or '-'):<8} "
              f"{n['last_seen']}")
    return 0


def cmd_audit(args) -> int:
    user_id = None
    if args.user:
        user_id = _resolve_user(args.user)["id"]
    rows = auth.list_audit(user_id=user_id, limit=args.n)
    if args.json:
        print(json.dumps(rows, indent=2, default=str))
        return 0
    for r in rows:
        print(f"{r['ts']}  user={r['user_id']}  {r['action']}  "
              f"target={r.get('target') or '-'}  ip={r.get('ip') or '-'}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(prog="aim-user-admin")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("create", help="create a new user")
    c.add_argument("username")
    c.add_argument("--role", choices=["admin", "user"], default="user")
    c.add_argument("--email", default=None)
    c.add_argument("--password", default=None,
                   help="(non-interactive; prefer omitting and typing at prompt)")
    c.set_defaults(func=cmd_create)

    c = sub.add_parser("list", help="list all users")
    c.add_argument("--json", action="store_true")
    c.set_defaults(func=cmd_list)

    c = sub.add_parser("token", help="issue / re-issue API token (prints it)")
    c.add_argument("username")
    c.set_defaults(func=cmd_token)

    c = sub.add_parser("revoke-token", help="revoke API token")
    c.add_argument("username")
    c.set_defaults(func=cmd_revoke_token)

    c = sub.add_parser("reset", help="reset password")
    c.add_argument("username")
    c.add_argument("--password", default=None)
    c.set_defaults(func=cmd_reset)

    c = sub.add_parser("disable", help="disable user (also revokes api token)")
    c.add_argument("username")
    c.set_defaults(func=cmd_disable)

    c = sub.add_parser("enable", help="re-enable user")
    c.add_argument("username")
    c.set_defaults(func=cmd_enable)

    c = sub.add_parser("link-code", help="generate a Telegram /link code")
    c.add_argument("username")
    c.add_argument("--ttl", type=int, default=10, help="minutes (default 10)")
    c.set_defaults(func=cmd_link_code)

    c = sub.add_parser("nodes", help="list registered AIM nodes (heartbeat)")
    c.add_argument("--json", action="store_true")
    c.set_defaults(func=cmd_nodes)

    c = sub.add_parser("audit", help="show audit log")
    c.add_argument("--user", default=None)
    c.add_argument("-n", type=int, default=50)
    c.add_argument("--json", action="store_true")
    c.set_defaults(func=cmd_audit)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
