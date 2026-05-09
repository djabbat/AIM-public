"""agents/generalist_pkg/gates.py — kernel-law sandbox gates for tool calls.

Phase 10 hybrid step 2 (2026-05-07): extracted from `agents/generalist.py`
without changing semantics. Re-exported via the legacy module path:

    from agents.generalist import _gate_external, _gate_path, _gate_write,
                                  _post_write_verify

continues to work for the existing 50+ internal call sites.

Functions guard tool calls per AIM kernel laws:
  - L_PRIVACY    — no Patient/* paths or PII patterns leaving the box
  - L_CONSENT    — public-blast actions need explicit user_confirmed
  - L_VERIFIABILITY — emit_text must have all PMIDs/DOIs verifiable
  - path sandbox — explicit allow / block roots based on env vars
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Optional


def _post_write_verify(p: Path) -> Optional[str]:
    """Implicit syntax check after a file write. Returns warning string if
    syntax is broken (None if clean / unsupported extension)."""
    suf = p.suffix.lower()
    try:
        if suf == ".py":
            import ast
            ast.parse(p.read_text(encoding="utf-8"))
        elif suf in (".json",):
            json.loads(p.read_text(encoding="utf-8"))
        elif suf in (".yaml", ".yml"):
            import yaml  # type: ignore
            yaml.safe_load(p.read_text(encoding="utf-8"))
        elif suf in (".toml",):
            try:
                import tomllib  # 3.11+
                tomllib.loads(p.read_text(encoding="utf-8"))
            except ImportError:
                pass
    except SyntaxError as e:
        return f"WARN:syntax: {e}"
    except (json.JSONDecodeError, ValueError) as e:
        return f"WARN:parse: {e}"
    except Exception as e:
        return f"WARN:verify: {type(e).__name__}: {e}"
    return None


def _gate_external(action_type: str, payload: dict,
                   require_verifiability: bool = False) -> Optional[str]:
    """L_CONSENT + L_VERIFIABILITY pre-flight gate for actions whose blast
    radius exceeds the local box (email_send, git_push_public, etc).

    Returns ERROR string on block, None on pass.
    """
    from agents.kernel import Decision
    from agents.kernel_legacy import (
        evaluate_l_consent, evaluate_l_verifiability,
    )
    auto = os.environ.get("AIM_AUTO_CONSENT") == "1"
    d = Decision(id=f"gen-{action_type}",
                 description=action_type,
                 action_type=action_type,
                 payload=payload)
    ctx = {"user_confirmed": True} if auto else {}
    ok, reason = evaluate_l_consent(d, {}, ctx)
    if not ok:
        return f"ERROR:PERMISSION:{reason}"
    if require_verifiability:
        ok, reason = evaluate_l_verifiability(d, {}, ctx)
        if not ok:
            return f"ERROR:PERMISSION:{reason}"
    return None


_SECRET_PATH_RE = re.compile(
    r"(\.aim_env|\.env$|/\.ssh/|/secrets?/|"
    r"id_rsa|id_ed25519|api[_-]?key|"
    r"AIM_USER_TOKEN|GROQ_API_KEY|DEEPSEEK_API_KEY|"
    r"ANTHROPIC_API_KEY|GEMINI_API_KEY)",
    re.IGNORECASE,
)


def _gate_path(path: str, *, write: bool) -> Optional[str]:
    """Sandbox: refuse paths outside AIM_PROJECT_ROOT or in secret-name
    patterns. Bypass with AIM_NO_PATH_SANDBOX=1."""
    s = str(path)
    if os.environ.get("AIM_NO_PATH_SANDBOX") == "1":
        return None
    try:
        p_in = Path(path).expanduser()
        p_abs = p_in.resolve(strict=False)
    except (OSError, ValueError) as e:
        return f"ERROR:INVALID_INPUT:bad path '{path}': {e}"
    if _SECRET_PATH_RE.search(s):
        return ("ERROR:PERMISSION:path matches secret pattern; "
                "set AIM_NO_PATH_SANDBOX=1 to override.")
    root = Path(os.environ.get(
        "AIM_PROJECT_ROOT",
        str(Path(__file__).resolve().parent.parent.parent),
    )).resolve()
    try:
        p_abs.relative_to(root)
    except ValueError:
        allow_prefixes = ("/tmp/", str(Path.home() / ".cache" / "aim"))
        if not str(p_abs).startswith(allow_prefixes):
            return (f"ERROR:PERMISSION:path '{p_abs}' outside "
                    f"AIM_PROJECT_ROOT ({root}); "
                    "set AIM_NO_PATH_SANDBOX=1 to override.")
    return None


def _gate_write(path: str, content: str = "") -> Optional[str]:
    """Run kernel L_PRIVACY + L_CONSENT before any file write.

    Returns ERROR string if the write must be blocked, else None.
    Files inside Patients/ require explicit privacy_consent context.
    Writes that contain Patients/ paths or PII patterns get blocked.
    """
    from agents.kernel import Decision, evaluate_l_privacy
    blob = f"{path}\n{content[:8000]}"
    if "Patients/" in str(path) or "/Patients/" in str(path):
        if os.environ.get("AIM_ALLOW_PATIENT_WRITE") != "1":
            return ("ERROR:PERMISSION:write blocked under L_PRIVACY — "
                    f"path '{path}' is inside Patients/. Set "
                    "AIM_ALLOW_PATIENT_WRITE=1 to override.")
        return None
    d = Decision(id="write", description="file write",
                 action_type="external_api_call_with_data",
                 payload={"path": str(path), "data": blob})
    ok, reason = evaluate_l_privacy(d, {}, {})
    if not ok and not os.environ.get("AIM_ALLOW_PII_WRITE"):
        return f"ERROR:PERMISSION:{reason}"
    return None
