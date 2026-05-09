"""agents/orchestrator.py — central routing gate for service-level tools.

Every delegate_* tool (doctor/writer/researcher/coder/email/...) goes through
orchestrate(), which runs the full kernel pipeline before the service is
called and re-checks emitted text afterwards.

Pipeline order (per user spec 2026-05-02 → 2026-05-02):

    L0 → L1 → L2 → L3            ← Asimov hard laws       (block on fail, PRE)
      → L_PRIVACY                  ← PII/Patients egress    (block on fail, PRE)
      → L_CONSENT                  ← external blast radius  (block on fail, PRE)
        → service_fn(...)          ← actual agent code (Doctor/Writer/...)
      → L_VERIFIABILITY (post)     ← unverified PMID/DOI    (block on fail, POST)
      → Ze-verify (auto, POST)     ← every <file>:<line> ref in output is
                                     mechanically checked against the file
                                     system; broken refs → warning header
      → Ze scoring (post)          ← impedance / 𝒞 / Φ / U (advisory header, POST)
      → return [Ze header] + out

Ze-verify is the routine sceptic stage. It does NOT trust the agent's text:
it pulls every "path/file.ext:NNN" reference out of the output and asks
the file system whether that line exists. If a reference points to a
non-existent file or an out-of-range line, the orchestrator prepends a
visible warning so the consumer (UI / next agent / user) sees it.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from agents.kernel import (
    Decision,
    evaluate_laws,
    evaluate_l_privacy,
    evaluate_l_consent,
    evaluate_l_verifiability,
    score_decision,
)

log = logging.getLogger("aim.orchestrator")

# ── F1 reflexion auto-pull (2026-05-03) ──────────────────────────────


def _reflexion_auto_enabled() -> bool:
    import os
    return os.environ.get("AIM_REFLEXION_AUTO") == "1"


def _gather_reflexion_hints(decision: Decision) -> list[str]:
    """Return up to 3 recent verbal reflections for this task class.

    The bucket key is taken from `decision.action_type`; if reflexion
    has no bucket for it, we fall back to the description text classifier.
    """
    try:
        from agents import reflexion as rfx
    except Exception:
        return []
    try:
        bucket = decision.action_type or rfx.classify(decision.description or "")
        return list(rfx.recent_reflections(decision.description or decision.id,
                                            n=3, bucket=bucket)) or []
    except Exception as e:
        log.debug("reflexion gather failed: %s", e)
        return []


# action_type families that need extended-law gating.
_PRIVACY_ACTIONS = {
    "email_send", "web_post", "git_push_public", "upload_external",
    "external_api_call_with_data",
}
_CONSENT_ACTIONS = {
    "email_send", "git_push_public", "telegram_broadcast",
    "web_publish", "external_api_call_with_data",
}
_VERIFIABILITY_ACTIONS = {
    "emit_text", "write_manuscript", "send_letter",
    "generate_citations", "peer_review_emit", "grant_letter",
}

# Action types that get the clinical Ze scorer (patient-impedance based).
_CLINICAL_ACTIONS = {"dx", "treatment", "test", "imaging",
                     "referral", "wait", "clarify"}


@dataclass
class _ZeMetrics:
    impedance_before: float
    impedance_after: float
    instant_c: float
    phi_ze: float
    utility: float


def _payload_chars(payload: dict) -> int:
    total = 0
    for v in (payload or {}).values():
        if isinstance(v, str):
            total += len(v)
        elif isinstance(v, (list, dict)):
            total += len(str(v))
        else:
            total += len(str(v))
    return total


def _score_nonclinical(decision: Decision, output: str) -> _ZeMetrics:
    """Lightweight Ze scorer for non-clinical decisions.

    Signals:
      * impedance_before — input ambiguity proxy: payload character count
        normalized to [0, 0.8]. 0 chars → 0.10 (baseline), 5000+ chars → 0.8.
      * impedance_after — for emit_text-class actions: output should reduce
        ambiguity but adds "surface" to verify; we set I_after = 0.5 * I_before
        + (output_chars / 16000) to penalise verbose hand-waving.
        For non-emitting actions (email_send, draft): I_after = 0.3 * I_before
        (action completed, less remaining uncertainty).
      * instant_c = (I_before - I_after) / 1.0 (clamped to [-1, 1]).
      * phi_ze — citation hygiene: rate of unverified PMID/DOI in output,
        inverted. 0 fakes = 1.0, 50%+ fakes = 0.0. If no citations, 1.0.
      * utility = 0.4·𝒞 + 0.3·Φ + 0.3·(1 − impedance_after).
    """
    pl_chars = _payload_chars(decision.payload)
    I_before = max(0.10, min(0.10 + pl_chars / 6250, 0.80))

    out_text = output or ""
    out_len = len(out_text)
    if decision.action_type in _VERIFIABILITY_ACTIONS:
        I_after = max(0.0, min(0.5 * I_before + out_len / 16000, 1.0))
    else:
        I_after = max(0.0, 0.3 * I_before)

    c = max(-1.0, min(1.0, I_before - I_after))

    phi = 1.0
    if out_text and decision.action_type in _VERIFIABILITY_ACTIONS:
        try:
            from tools.literature import enforce_citations
            rep = enforce_citations(out_text, mode="annotate")
            rejected = len(getattr(rep, "rejected", []) or [])
            checked = rejected + len(getattr(rep, "verified", []) or [])
            if checked:
                phi = max(0.0, 1.0 - 2.0 * (rejected / checked))
        except Exception as e:
            log.debug(f"phi_ze citation check failed: {e}")

    U = 0.4 * c + 0.3 * phi + 0.3 * (1.0 - I_after)
    return _ZeMetrics(I_before, I_after, c, phi, U)


def _to_metrics(s) -> _ZeMetrics:
    """Convert kernel.ScoringResult → _ZeMetrics shape used in header."""
    return _ZeMetrics(
        impedance_before=s.impedance_before,
        impedance_after=s.impedance_after,
        instant_c=s.instant_c,
        phi_ze=s.phi_ze,
        utility=s.utility,
    )


# ── Ze-verify: routine sceptic stage ────────────────────────────────────────

# Match `path/with/segments.ext:NNN`. Stops at whitespace or punctuation that
# isn't a valid path char. Excludes URLs by requiring the path NOT to start
# with http(s):// or ://.
_FILE_LINE_RE = re.compile(
    r"(?<![:/])"                                # not preceded by : or /
    r"([\w./\-]+\.[A-Za-z]{1,8}):(\d{1,7})"
    r"(?!\d)"
)

# How many candidates to verify per output (cap to keep it cheap).
_MAX_REFS_TO_VERIFY = 30


_RESOLVE_SUBDIRS = ("agents", "tools", "tests", "scripts", "web", "cli",
                    "DiffDiagnosis", "SSA", "deploy", "export", "migrations")


def _resolve_path(p: str, base_dirs: list[Path]) -> Optional[Path]:
    """Resolve a relative-or-bare-basename file ref.

    Order of attempts:
      1. Absolute path verbatim.
      2. <base>/<p> for each base in base_dirs (covers paths like
         "agents/orchestrator.py" relative to AIM root).
      3. <base>/<subdir>/<p> for known runtime subdirs (covers bare
         basenames like "orchestrator.py" → agents/orchestrator.py).

    Bare-basename search is bounded to a fixed list of known subdirs to
    keep the cost predictable; we deliberately do NOT do an unbounded
    rglob over the whole tree.
    """
    raw = Path(p).expanduser()
    if raw.is_absolute():
        return raw if raw.is_file() else None
    # 2) verbatim under each base
    for base in base_dirs:
        cand = base / raw
        if cand.is_file():
            return cand
    # 3) bare-basename under known subdirs (only when input has no slashes)
    if raw.parent == Path(".") or str(raw.parent) == "":
        for base in base_dirs:
            for sub in _RESOLVE_SUBDIRS:
                cand = base / sub / raw.name
                if cand.is_file():
                    return cand
    return None


@dataclass
class _VerifyReport:
    total: int
    ok: int
    bad: list[str]   # human-readable failure lines


def _ze_verify_output(output: str) -> _VerifyReport:
    """Scan output for `path:line` refs and check each one mechanically.

    Failure modes recorded:
      • file does not exist
      • line number > total lines in file
    All refs are deduped before checking.
    """
    seen: set[tuple[str, int]] = set()
    pairs: list[tuple[str, int]] = []
    for m in _FILE_LINE_RE.finditer(output):
        path, ln_s = m.group(1), m.group(2)
        try:
            ln = int(ln_s)
        except ValueError:
            continue
        key = (path, ln)
        if key in seen:
            continue
        seen.add(key)
        pairs.append(key)
        if len(pairs) >= _MAX_REFS_TO_VERIFY:
            break

    if not pairs:
        return _VerifyReport(total=0, ok=0, bad=[])

    aim_root = Path(__file__).resolve().parent.parent  # …/AIM
    bases = [aim_root, aim_root.parent]  # AIM/ and LongevityCommon/

    bad: list[str] = []
    ok = 0
    for path, ln in pairs:
        resolved = _resolve_path(path, bases)
        if resolved is None:
            bad.append(f"{path}:{ln} (file not found)")
            continue
        try:
            total = sum(1 for _ in resolved.open("rb"))
        except Exception as e:
            bad.append(f"{path}:{ln} (read error: {type(e).__name__})")
            continue
        if ln < 1 or ln > total:
            bad.append(f"{path}:{ln} (out of range; file has {total} lines)")
            continue
        ok += 1
    return _VerifyReport(total=len(pairs), ok=ok, bad=bad)


def _persist_ze_event(decision: Decision, *, blocked_at: Optional[str] = None,
                      metrics: Optional[_ZeMetrics] = None,
                      output_chars: int = 0) -> None:
    """Write one row to ze_events. Best-effort; never raises."""
    try:
        from datetime import datetime
        from db import _conn, init_db
        init_db()
        with _conn() as c:
            c.execute(
                "INSERT INTO ze_events (ts, decision_id, action_type, "
                "blocked_at, impedance_before, impedance_after, instant_c, "
                "phi_ze, utility, payload_chars, output_chars) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    datetime.utcnow().isoformat(timespec="seconds"),
                    decision.id,
                    decision.action_type,
                    blocked_at,
                    metrics.impedance_before if metrics else None,
                    metrics.impedance_after if metrics else None,
                    metrics.instant_c if metrics else None,
                    metrics.phi_ze if metrics else None,
                    metrics.utility if metrics else None,
                    _payload_chars(decision.payload),
                    output_chars,
                ),
            )
    except Exception as e:
        log.debug(f"_persist_ze_event failed: {e}")


def _format_ze_header(m: _ZeMetrics) -> str:
    warns: list[str] = []
    if m.impedance_after > m.impedance_before:
        warns.append(f"impedance ↑ ({m.impedance_before:.2f}→{m.impedance_after:.2f}): "
                     "decision raises uncertainty")
    if m.instant_c < 0:
        warns.append(f"𝒞<0 ({m.instant_c:.3f}): clarity loss")
    if m.utility < 0:
        warns.append(f"U<0 ({m.utility:.3f}): net-negative")
    header = (f"[Ze] I_before={m.impedance_before:.2f} "
              f"I_after={m.impedance_after:.2f} "
              f"𝒞={m.instant_c:.3f} Φ={m.phi_ze:.3f} "
              f"U={m.utility:.3f}")
    if warns:
        header += "  ⚠ " + "; ".join(warns)
    return header


def orchestrate(
    decision: Decision,
    service_fn: Callable[..., Any],
    *,
    patient: Optional[dict] = None,
    context: Optional[dict] = None,
    args: Optional[Iterable[Any]] = None,
    kwargs: Optional[dict] = None,
    skip_ze: bool = False,
    extract_text_for_verifiability: Callable[[Any], str] = str,
) -> str:
    """Route a decision through the kernel pipeline, then call service_fn.

    Pipeline: L0-L3 (PRE) → L_PRIVACY (PRE) → L_CONSENT (PRE) → service_fn
              → L_VERIFIABILITY (POST) → Ze scoring (POST) → header + out.

    Returns a string. On any law violation the string starts with ``ERROR:``.
    Ze metrics are advisory — never block on Ze.
    """
    patient = patient or {}
    context = context or {}
    args = tuple(args or ())
    kwargs = kwargs or {}

    # 1) L0–L3 (Asimov hard laws) — PRE
    laws = evaluate_laws(decision, patient=patient, context=context)
    if not laws.passed:
        joined = " | ".join(r for r in laws.reasons if r)
        _persist_ze_event(decision, blocked_at="L0-3")
        return f"ERROR:KERNEL:Asimov laws blocked {decision.id} — {joined}"

    # 2) L_PRIVACY — PRE (only for action_types with PII egress)
    if decision.action_type in _PRIVACY_ACTIONS:
        ok, reason = evaluate_l_privacy(decision, patient, context)
        if not ok:
            _persist_ze_event(decision, blocked_at="L_PRIVACY")
            return f"ERROR:KERNEL:{reason}"

    # 3) L_CONSENT — PRE (only for action_types with external blast radius)
    if decision.action_type in _CONSENT_ACTIONS:
        ok, reason = evaluate_l_consent(decision, patient, context)
        if not ok:
            _persist_ze_event(decision, blocked_at="L_CONSENT")
            return f"ERROR:KERNEL:{reason}"

    # 3.5) Reflexion hints — F1 (2026-05-03). When AIM_REFLEXION_AUTO=1
    # we attach recent verbal-failure notes for this task class into
    # kwargs["_aim_reflexion_hints"]. Service_fn can read them or ignore;
    # downstream prompt-building wraps see them via `kwargs.get(...)`.
    if _reflexion_auto_enabled():
        hints = _gather_reflexion_hints(decision)
        if hints:
            kwargs = dict(kwargs)
            kwargs["_aim_reflexion_hints"] = hints

    # 4) Dispatch to the actual service.
    try:
        out = service_fn(*args, **kwargs)
    except TypeError as e:
        # The service likely doesn't accept _aim_reflexion_hints. Drop the
        # hint and retry once — never let reflexion break a real call.
        if "_aim_reflexion_hints" in kwargs and "_aim_reflexion_hints" in str(e):
            kwargs = {k: v for k, v in kwargs.items()
                      if k != "_aim_reflexion_hints"}
            try:
                out = service_fn(*args, **kwargs)
            except Exception as e2:
                _persist_ze_event(decision, blocked_at=f"INTERNAL:{type(e2).__name__}")
                return f"ERROR:INTERNAL:{decision.id}: {e2}"
        else:
            _persist_ze_event(decision, blocked_at=f"INTERNAL:{type(e).__name__}")
            return f"ERROR:INTERNAL:{decision.id}: {e}"
    except Exception as e:
        _persist_ze_event(decision, blocked_at=f"INTERNAL:{type(e).__name__}")
        return f"ERROR:INTERNAL:{decision.id}: {e}"

    # 5) L_VERIFIABILITY — POST (block emitted bad citations).
    if decision.action_type in _VERIFIABILITY_ACTIONS:
        text = extract_text_for_verifiability(out)
        if text:
            verif_decision = Decision(
                id=f"{decision.id}.verify",
                description=f"verify {decision.action_type}",
                action_type=decision.action_type,
                payload={"text": text},
            )
            ok, reason = evaluate_l_verifiability(
                verif_decision, patient, context)
            if not ok:
                _persist_ze_event(decision, blocked_at="L_VERIFIABILITY")
                return (f"ERROR:VERIFIABILITY:{reason}\n\n"
                        f"--- raw service output (suppressed) ---\n"
                        f"{text[:4000]}")

    # 6) Ze-verify (auto sceptic) — POST, runs on every orchestrate call,
    # regardless of skip_ze. Cannot be skipped by the agent.
    out_text = extract_text_for_verifiability(out) if out else ""
    verify_header = ""
    try:
        report = _ze_verify_output(out_text)
        if report.bad:
            joined = "; ".join(report.bad[:10])
            extra = "" if len(report.bad) <= 10 else f"; +{len(report.bad)-10} more"
            verify_header = (
                f"[Ze-verify] {report.ok}/{report.total} refs OK; "
                f"BROKEN ({len(report.bad)}): {joined}{extra}"
            )
            # Persist as a calibration event so trends are queryable.
            _persist_ze_event(
                Decision(id=f"{decision.id}.verify",
                         description="auto Ze-verify",
                         action_type="ze_verify_auto",
                         payload={"total_refs": report.total,
                                  "bad_refs": report.bad[:20]}),
                blocked_at="REFS_BROKEN",
                output_chars=len(out_text),
            )
    except Exception as e:
        log.debug(f"_ze_verify_output failed: {e}")

    # 6b) Ze-AST verify — semantic check of symbol-at-line and negative-call
    # claims. Catches what regex auto-verify cannot (file exists + line exists,
    # but the symbol on that line is something else; or "no callers" claim
    # while AST shows real callers).
    ast_header = ""
    try:
        from agents.ast_verify import verify_claims as _ast_verify_claims
        aim_root = Path(__file__).resolve().parent.parent
        ast_rep = _ast_verify_claims(out_text, search_root=aim_root)
        if ast_rep.bad:
            joined = "; ".join(ast_rep.bad[:5])
            extra = "" if len(ast_rep.bad) <= 5 else f"; +{len(ast_rep.bad)-5} more"
            ast_header = (
                f"[Ze-AST] {ast_rep.ok}/{ast_rep.total} claims OK; "
                f"WRONG ({len(ast_rep.bad)}): {joined}{extra}"
            )
            _persist_ze_event(
                Decision(id=f"{decision.id}.ast",
                         description="auto Ze-AST verify",
                         action_type="ze_ast_auto",
                         payload={"total_claims": ast_rep.total,
                                  "bad_claims": ast_rep.bad[:10]}),
                blocked_at="AST_WRONG",
                output_chars=len(out_text),
            )
    except Exception as e:
        log.debug(f"AST verify failed: {e}")

    # 7) Ze scoring — POST, advisory only.
    ze_header = ""
    metrics: Optional[_ZeMetrics] = None
    if not skip_ze:
        try:
            if decision.action_type in _CLINICAL_ACTIONS:
                metrics = _to_metrics(score_decision(decision, patient=patient,
                                                     context=context))
            else:
                metrics = _score_nonclinical(decision, out_text)
            ze_header = _format_ze_header(metrics)
        except Exception as e:
            log.debug(f"Ze scoring failed for {decision.id}: {e}")

    # 8) Persist + return. Verify-warnings, if any, lead the header stack.
    _persist_ze_event(decision, blocked_at=None, metrics=metrics,
                      output_chars=len(out_text))
    headers = [h for h in (verify_header, ast_header, ze_header) if h]
    if headers:
        return "\n".join(headers) + f"\n\n{out}"
    return str(out)
