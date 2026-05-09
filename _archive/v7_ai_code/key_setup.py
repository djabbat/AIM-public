"""agents/key_setup.py — Interactive setup for the local user's LLM keys.

Used by:
  - ``python -m aim_cli setup-key`` (CLI, single-user / OS-user-as-AIM-user)
  - First-run wizard inside ``medical_system.py`` if no key is found

Writes to ``~/.aim_env`` (the same file that ``install_node.sh`` populates).
This is the right home for the *local* (CLI) user's keys: those keys belong
to the OS account that runs the AIM process, are billed to that user's
provider account, and are not shared with anyone else.

For Telegram bot users (one bot serving many people) and multi-tenant web
deployments, use :mod:`agents.user_keys` instead — that module has a
per-user JSON store with thread-local context for runtime resolution.
"""
from __future__ import annotations

import os
import re
from getpass import getpass
from pathlib import Path

from user_keys import PROVIDERS, ENV_VARS

ENV_FILE = Path.home() / ".aim_env"

PROVIDER_INFO = {
    "deepseek": {
        "label": "DeepSeek (primary cloud — chat + reasoner)",
        "url": "https://platform.deepseek.com/api_keys",
        "prefix": "sk-",
    },
    "groq": {
        "label": "Groq (fast cloud, free tier — Llama / Mixtral)",
        "url": "https://console.groq.com/keys",
        "prefix": "gsk_",
    },
    "anthropic": {
        "label": "Anthropic (Claude — premium critical-tier)",
        "url": "https://console.anthropic.com/settings/keys",
        "prefix": "sk-ant-",
    },
    "gemini": {
        "label": "Google Gemini (free 2.5-flash-lite, no credit card)",
        "url": "https://aistudio.google.com/apikey",
        "prefix": "",  # no fixed prefix
    },
}


def _read_env_file() -> dict[str, str]:
    if not ENV_FILE.exists():
        return {}
    out: dict[str, str] = {}
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip()
    return out


def _write_env_file(values: dict[str, str]) -> None:
    """Replace/insert the keys in ~/.aim_env, preserving other entries + comments."""
    existing_lines: list[str] = []
    if ENV_FILE.exists():
        existing_lines = ENV_FILE.read_text(encoding="utf-8").splitlines()

    seen: set[str] = set()
    new_lines: list[str] = []
    for line in existing_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            new_lines.append(line)
            continue
        m = re.match(r"^([A-Z_][A-Z0-9_]*)\s*=", stripped)
        if not m:
            new_lines.append(line)
            continue
        var = m.group(1)
        if var in values:
            new_lines.append(f"{var}={values[var]}")
            seen.add(var)
        else:
            new_lines.append(line)

    for var, val in values.items():
        if var not in seen:
            new_lines.append(f"{var}={val}")

    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    ENV_FILE.write_text("\n".join(new_lines).rstrip() + "\n", encoding="utf-8")
    try:
        os.chmod(ENV_FILE, 0o600)
    except OSError:
        pass


def _mask(value: str) -> str:
    if not value:
        return "(unset)"
    if len(value) <= 8:
        return "*" * len(value)
    return value[:4] + "…" + value[-4:]


def _prompt_one(provider: str, current: str) -> str | None:
    info = PROVIDER_INFO[provider]
    print()
    print(f"  ── {info['label']}")
    print(f"     get a key:  {info['url']}")
    print(f"     current:    {_mask(current)}")
    print(f"     [Enter] keep  ·  type new key to replace  ·  type DELETE to clear")
    new = getpass("     new key (hidden): ").strip()
    if not new:
        return None  # keep
    if new.upper() == "DELETE":
        return ""  # clear
    if info["prefix"] and not new.startswith(info["prefix"]):
        print(f"     ⚠ warning: expected to start with {info['prefix']!r}; "
              "stored anyway — verify on the provider dashboard if calls fail.")
    return new


def run_interactive(providers: list[str] | None = None) -> dict[str, str]:
    """Walk the user through setting/replacing one or more provider keys.

    Returns the mapping of changes that were written (env-var name → new value;
    empty string == cleared).
    """
    providers = providers or list(PROVIDERS)
    bad = [p for p in providers if p not in PROVIDERS]
    if bad:
        raise ValueError(f"unknown provider(s): {bad}; allowed = {PROVIDERS}")

    print("AIM — provider key setup")
    print(f"  file:   {ENV_FILE}")
    print(f"  rule:   each AIM user holds their OWN keys — billing goes to your")
    print(f"          own provider account. Never paste someone else's key.")

    env = _read_env_file()
    changes: dict[str, str] = {}
    for provider in providers:
        var = ENV_VARS[provider]
        current = env.get(var, os.environ.get(var, ""))
        new = _prompt_one(provider, current)
        if new is not None:
            changes[var] = new

    if not changes:
        print("\nNo changes.")
        return {}

    _write_env_file(changes)
    print()
    for var, val in changes.items():
        if val == "":
            print(f"  ✗ cleared {var}")
        else:
            print(f"  ✓ saved   {var} = {_mask(val)}")
    print(f"\n→ {ENV_FILE} updated. Restart AIM to pick up the new keys.")
    return changes


def show_status() -> None:
    """Print which keys are currently set in env / ~/.aim_env."""
    env = _read_env_file()
    print(f"AIM key status — {ENV_FILE}")
    for provider in PROVIDERS:
        var = ENV_VARS[provider]
        current = env.get(var, os.environ.get(var, ""))
        status = "✓ set    " if current else "  unset  "
        print(f"  {status} {var:<22} {_mask(current)}")
