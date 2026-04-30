"""cli/setup_wizard.py — interactive setup wizards for AIM.

Two flows:
    run_init_wizard()      — `aim init` — first-time setup of ~/.aim_env
    run_node_setup()       — `aim node setup` — pair this device with a hub

Both write to ~/.aim_env (or %USERPROFILE%\\.aim_env on Windows) atomically:
read-modify-write through a temp file, mode 0600 on Unix.

Skipped questions don't touch existing values — wizard re-runs are safe.
"""
from __future__ import annotations

import getpass
import json
import os
import platform
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


# ── ~/.aim_env helpers ─────────────────────────────────────────────────────


def _env_path() -> Path:
    if platform.system() == "Windows":
        return Path(os.environ.get("USERPROFILE",
                                   str(Path.home()))) / ".aim_env"
    return Path.home() / ".aim_env"


def _read_env() -> dict[str, str]:
    p = _env_path()
    out: dict[str, str] = {}
    if not p.exists():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def _write_env(env: dict[str, str]) -> None:
    p = _env_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(f"{k}={v}" for k, v in sorted(env.items()))
    tmp = p.with_suffix(".tmp")
    tmp.write_text(body + "\n", encoding="utf-8")
    tmp.replace(p)
    if platform.system() != "Windows":
        try:
            os.chmod(p, 0o600)
        except OSError:
            pass


def _set_env(key: str, value: str) -> None:
    env = _read_env()
    env[key] = value
    _write_env(env)


# ── Probes ─────────────────────────────────────────────────────────────────


def _ollama_running() -> bool:
    import http.client
    try:
        c = http.client.HTTPConnection("127.0.0.1", 11434, timeout=1.5)
        c.request("GET", "/api/tags")
        r = c.getresponse()
        return r.status == 200
    except Exception:
        return False


def _ask(label: str, default: str = "", *, secret: bool = False) -> str:
    suffix = f" [{default[:18]+'…' if len(default) > 18 else default}]" if default else ""
    prompt = f"  {label}{suffix}: "
    try:
        if secret:
            v = getpass.getpass(prompt)
        else:
            v = input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        return default
    return v or default


# ── `aim init` — first-time setup ──────────────────────────────────────────


def run_init_wizard(*, non_interactive: bool = False) -> int:
    print("AIM init  ·  one-time setup")
    print(f"writes → {_env_path()}\n")

    env = _read_env()

    # 1. Ollama (auto-detect)
    if _ollama_running():
        print("  ✓ Ollama detected on http://127.0.0.1:11434 (local LLM ready)")
    else:
        print("  ! Ollama not detected — run `curl -fsSL https://ollama.com/install.sh | sh`")
        print("    (AIM works without Ollama if any cloud key is set below)")

    if non_interactive:
        print("\n[non-interactive] no further questions; existing ~/.aim_env preserved.")
        return 0

    print("\nLLM keys (press Enter to keep existing or skip):")
    print("  Get DeepSeek key:  https://platform.deepseek.com")
    print("  Get Gemini key  :  https://aistudio.google.com/apikey  (free, no CC)")
    print("  Get Groq key    :  https://console.groq.com  (free)")
    print("  Get Claude key  :  https://console.anthropic.com  (paid; optional)")
    print()

    for key, label in (
        ("DEEPSEEK_API_KEY",  "DeepSeek API key"),
        ("GEMINI_API_KEY",    "Gemini API key"),
        ("GROQ_API_KEY",      "Groq API key"),
        ("ANTHROPIC_API_KEY", "Anthropic Claude API key"),
    ):
        cur = env.get(key, "")
        masked = (cur[:8] + "…") if cur else ""
        v = _ask(label, masked, secret=True)
        if v and v != masked:
            env[key] = v

    # Hub URL — only ask if not already set (otherwise use `aim node setup`)
    if not env.get("AIM_HUB_URL"):
        print("\nMulti-user mode — does this machine connect to an AIM Hub?")
        print("  Leave blank for local-only single-user mode.")
        print("  Otherwise paste the hub URL (e.g. https://hub.example.com).")
        hub = _ask("AIM_HUB_URL", "")
        if hub:
            env["AIM_HUB_URL"] = hub
            print("  → Run `aim node setup` next to pair this device with the hub.")

    _write_env(env)
    print(f"\n✓ wrote {_env_path()}")
    print("\nNext steps:")
    print("  • `aim doctor`  — verify providers")
    print("  • `aim ai`      — start the AI assistant")
    print("  • `aim cli`     — full medical menu")
    return 0


# ── `aim node setup` — device pairing ──────────────────────────────────────


def run_node_setup(*, non_interactive: bool = False,
                   hub_url: str | None = None,
                   code: str | None = None) -> int:
    print("AIM node setup  ·  pair this device with a Hub")

    env = _read_env()

    # 1. Hub URL
    if not hub_url:
        hub_url = env.get("AIM_HUB_URL") or ""
        if non_interactive and not hub_url:
            print("ERROR: --hub-url required in non-interactive mode", file=sys.stderr)
            return 2
        if not non_interactive:
            print("\nWhat is the URL of your AIM Hub?")
            print("  Format: https://hub.example.com  (no trailing slash)")
            hub_url = _ask("hub URL", hub_url)
    hub_url = (hub_url or "").rstrip("/")
    if not hub_url:
        print("ERROR: hub URL is required.", file=sys.stderr)
        return 2

    # 2. Pair code
    if not code:
        if non_interactive:
            print("ERROR: --code required in non-interactive mode", file=sys.stderr)
            return 2
        print("\nAsk your hub admin to run:")
        print(f"    aim hub pair <your-username>")
        print("They will print a 6-digit code. Paste it below (10-min validity).")
        code = _ask("code", "").strip()
    if not (code.isdigit() and len(code) == 6):
        print("ERROR: code must be exactly 6 digits", file=sys.stderr)
        return 2

    # 3. Call hub
    try:
        node_id = f"{socket.gethostname()}-{os.environ.get('USER') or os.environ.get('USERNAME') or 'anon'}"
    except Exception:
        node_id = "unknown-node"

    payload = json.dumps({
        "code": code,
        "node_id": node_id,
        "host": socket.gethostname(),
        "version": "7.1",
    }).encode()
    req = urllib.request.Request(
        f"{hub_url}/api/auth/consume-pair-code",
        data=payload, method="POST",
        headers={"Content-Type": "application/json",
                 "User-Agent": "aim-node/7.1 (setup-wizard)"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status >= 300:
                print(f"ERROR: hub returned HTTP {resp.status}", file=sys.stderr)
                return 3
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = ""
        try: body = e.read().decode()[:200]
        except Exception: pass
        print(f"ERROR: hub rejected the code (HTTP {e.code}): {body}",
              file=sys.stderr)
        return 3
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        print(f"ERROR: cannot reach hub at {hub_url}: {e}", file=sys.stderr)
        return 3

    if not data.get("ok") or not data.get("token"):
        print(f"ERROR: hub rejected the code: {data}", file=sys.stderr)
        return 3

    user = data.get("user") or {}
    token = data["token"]

    # 4. Persist to ~/.aim_env
    env = _read_env()  # re-read in case anything changed
    env["AIM_HUB_URL"]    = hub_url
    env["AIM_USER_TOKEN"] = token
    env["AIM_NODE_ID"]    = node_id
    _write_env(env)

    print()
    print(f"✓ paired as user '{user.get('username', '?')}' (role={user.get('role','?')})")
    print(f"  hub:     {hub_url}")
    print(f"  node_id: {node_id}")
    print(f"  token written to {_env_path()} (mode 0600)")
    print()
    print("Next: `aim ai` or `aim cli` — you're authenticated.")
    return 0
