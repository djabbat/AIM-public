"""agents/coach.py — Python shim over `aim-coach` Rust binary
(P2.1, 2026-05-07).

Motivational-interviewing assistant for the L3 cornerstone. The
deterministic core (utterance classification, OARS move selection,
goal management, system prompt building) lives in Rust
(`rust-core/crates/aim-coach`). The LLM-driven generation step
(produce a coach turn given the patient utterance + suggested move)
stays Python because it routes through `llm.py` / `agents/llm_client.py`
just like the rest of the chat loop.

Public API:
    classify(utterance: str) -> str
        — change_talk / sustain_talk / neutral / resistance
    next_move(kind: str, activation_level: int) -> str
        — open_question / affirmation / reflection / summary /
          roll_with_resistance / build_rapport
    system_prompt(lang: str = "en") -> str
        — MI coach system prompt (OARS rules)
    coach_reply(patient_id, utterance, *, activation_level=None,
                lang="en", tier="default") -> dict
        — End-to-end: classify utterance → pick move → build LLM
          prompt → call llm.ask (or llm_client) → log co-design
          event if patient agreed/modified.

Logging policy: this module never auto-creates a "consulted" event
itself; that's the caller's responsibility. But if `coach_reply`
detects an explicit "I agree" / "Я согласен" / "I'll try" /
"Попробую" pattern in the patient utterance, it records an "agreed"
event in `aim-codesign` so L_AGENCY can pass on the next treatment
recommendation. Strict pattern match — false-positive risk is
non-zero, so the L_AGENCY gate still requires explicit clinician
confirmation downstream.

If you find yourself adding scoring or move logic here — STOP and
put it in the Rust crate, then expose a new subcommand. Adding the
LLM-prompt template is fine here (it's tier policy + Python LLM
client orchestration).
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
from pathlib import Path

log = logging.getLogger("aim.coach")


def _binary_path() -> Path:
    return (
        Path(__file__).resolve().parent.parent
        / "rust-core" / "target" / "release" / "aim-coach"
    )


def _run(args: list[str]) -> str:
    bin_path = _binary_path()
    if not bin_path.exists():
        raise FileNotFoundError(
            f"aim-coach binary not built at {bin_path}; "
            "run `cargo build -p aim-coach --release` in rust-core/"
        )
    proc = subprocess.run(
        [str(bin_path), *args],
        capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"aim-coach {args[0]} failed: {proc.stderr.strip()}")
    return proc.stdout


def classify(utterance: str) -> str:
    """One of: change_talk / sustain_talk / neutral / resistance."""
    if not utterance or not utterance.strip():
        return "neutral"
    return _run(["classify", utterance]).strip() or "neutral"


def next_move(kind: str, activation_level: int) -> str:
    """Pick OARS move given utterance kind + PAM-13 level (0-4)."""
    return _run(["next-move", kind, str(int(activation_level))]).strip()


def system_prompt(lang: str = "en") -> str:
    """MI coach system prompt with OARS rules."""
    return _run(["system-prompt", "--lang", lang])


# ── Co-design auto-detection (heuristic) ────────────────────────────────────

# Strict patterns. These intentionally over-match — the L_AGENCY gate
# downstream still requires the clinician to confirm via explicit
# `context.patient_codesigned=True` or an event written via
# `agents.codesign_log.record(...)`.
_AGREEMENT_PATTERNS = [
    r"\bя согласен\b", r"\bя согласна\b", r"\bсогласен\b", r"\bсогласна\b",
    r"\bдавайте попробуем\b", r"\bпопробую\b", r"\bдоговорились\b",
    r"\bокей\b", r"\bok\b", r"\bокей\b",
    r"\bi agree\b", r"\bi'll try\b", r"\bi will try\b",
    r"\blet's do it\b", r"\bdeal\b", r"\bsounds good\b",
    r"\bi accept\b", r"\bgo ahead\b",
]

_MODIFICATION_PATTERNS = [
    r"\bно если\b", r"\bbut if\b", r"\bcan we instead\b",
    r"\bдавай вместо этого\b", r"\bwhat if i\b",
    r"\bлучше я\b", r"\binstead i\b",
]


def detect_codesign_intent(utterance: str) -> str | None:
    """Return 'agreed' / 'modified' / None.

    Heuristic — false positives possible. Caller must still gate the
    next L_AGENCY decision on an explicit codesign_log event.
    """
    if not utterance:
        return None
    lc = utterance.lower()
    for p in _MODIFICATION_PATTERNS:
        if re.search(p, lc):
            return "modified"
    for p in _AGREEMENT_PATTERNS:
        if re.search(p, lc):
            return "agreed"
    return None


# ── End-to-end coach reply ──────────────────────────────────────────────────


def coach_reply(
    patient_id: str,
    utterance: str,
    *,
    activation_level: int | None = None,
    lang: str = "en",
    tier: str = "default",
    record_codesign: bool = True,
) -> dict:
    """Full coach turn:
        classify utterance → pick OARS move → build LLM prompt →
        call llm.ask_fast (or shim) → optionally record codesign event.

    Returns:
        {
            "kind":       "change_talk" | "sustain_talk" | "neutral" | "resistance",
            "move":       "open_question" | "affirmation" | "reflection" | ...,
            "reply":      str — the coach turn for the patient (≤80 words),
            "codesign":   "agreed" | "modified" | None — auto-detected intent,
            "level":      int — patient activation level used,
        }

    Args:
        patient_id:        canonical patient id (e.g. SMITH_John_2000_01_01).
                           Empty string → coach without persistent codesign.
        utterance:         what the patient just said.
        activation_level:  PAM-13 level; if None, fetched from pam_tracker.
        lang:              "en" / "ru" — affects MI system prompt.
        tier:              LLM tier (default fast for short turns).
        record_codesign:   if True, write an event to aim-codesign when
                           an "agreed"/"modified" pattern is detected.
    """
    if activation_level is None:
        try:
            from agents import pam_tracker
            activation_level = pam_tracker.current_activation_level(patient_id) if patient_id else 0
        except Exception:
            activation_level = 0
    activation_level = max(0, min(4, int(activation_level)))

    kind = classify(utterance)
    move = next_move(kind, activation_level)
    sysprompt = system_prompt(lang)

    # Build the user prompt — concrete + bounded.
    move_label = move.replace("_", " ")
    user_prompt = (
        f"Patient utterance:\n{utterance.strip()[:600]}\n\n"
        f"Patient PAM-13 activation level: {activation_level} "
        f"({_LEVEL_LABEL.get(activation_level, '?')}).\n\n"
        f"Suggested OARS move: {move_label}.\n"
        f"Reply to the patient with exactly ONE coach turn that "
        f"applies this move. Keep it under 80 words. Stay in {lang}."
    )

    reply_text = _ask_llm(user_prompt, system=sysprompt, tier=tier)

    codesign = detect_codesign_intent(utterance)
    if codesign and record_codesign and patient_id:
        try:
            from agents import codesign_log
            # decision_id is not yet known here; caller can pass it via
            # the topic field if they have one. Defaults to "coaching turn".
            codesign_log.record(
                patient_id, codesign,
                topic=f"auto-detected from utterance: {utterance.strip()[:60]}",
                by="patient",
                notes="auto-detected by agents/coach.py heuristic",
            )
        except Exception as e:
            log.debug(f"codesign auto-record failed (non-fatal): {e}")

    return {
        "kind": kind,
        "move": move,
        "reply": reply_text,
        "codesign": codesign,
        "level": activation_level,
    }


# ── Internal helpers ────────────────────────────────────────────────────────


_LEVEL_LABEL = {
    0: "unknown / no PAM-13 yet",
    1: "disengaged",
    2: "becoming aware",
    3: "taking action",
    4: "maintaining",
}


def _ask_llm(prompt: str, *, system: str = "", tier: str = "default") -> str:
    """Route LLM call through `agents/llm_client.py` (HTTP shim) when
    `AIM_LLM_HTTP_URL` is set, else through legacy `llm.py`. Both have
    the same `ask_fast / ask / ask_deep / ask_long / ask_critical`
    surface.
    """
    try:
        from agents import llm_client
        if llm_client.is_enabled():
            fn = {
                "fast": llm_client.ask_fast,
                "default": llm_client.ask,
                "deep": llm_client.ask_deep,
                "long": llm_client.ask_long,
                "critical": llm_client.ask_critical,
            }.get(tier, llm_client.ask)
            return fn(prompt, system=system)
    except Exception:
        pass
    # Fallback to legacy Python implementation.
    import llm
    fn = {
        "fast": llm.ask_fast,
        "default": llm.ask,
        "deep": llm.ask_deep,
        "long": llm.ask_long,
        "critical": llm.ask_critical,
    }.get(tier, llm.ask)
    return fn(prompt, system=system)
