"""agents/unicode_guard.py — Unicode hygiene utilities (UN1, 2026-05-03).

Three quick utilities used at every boundary where the user (or an
LLM) hands AIM a name / label / project string:

  * `normalise(s)`            — NFC + strip zero-width / control chars
  * `mixed_scripts(s)`        — flag strings that mix Cyrillic + Latin
                                in ways that probably aren't intentional
                                (e.g. "Иванoв" with a Latin 'o')
  * `safe(s, *, allow_mixed=False)` → tuple (normalised, warnings)

The `mixed_scripts` heuristic catches a real attack vector — a single
Latin lookalike letter inside a Cyrillic name silently changes the
patient identifier, breaking dedup / search.

Public API:
    normalise(s) -> str
    mixed_scripts(s) -> dict[script, count]
    is_suspicious(s) -> bool
    safe(s, *, allow_mixed=False) -> tuple[str, list[str]]
"""
from __future__ import annotations

import dataclasses
import logging
import unicodedata
from typing import Optional

log = logging.getLogger("aim.unicode_guard")


# Zero-width / formatting code points we always want to strip.
_INVISIBLE_CHARS = {
    "​", "‌", "‍",          # zero-width space / non-joiner / joiner
    "‎", "‏",                       # LTR/RTL mark
    "⁠",                                 # word-joiner
    "­",                                 # soft hyphen
    "﻿",                                 # BOM
}

# Categories we consider "scripts" of interest. We use the first 4 chars
# of unicodedata.name() as a coarse classifier — fast, no pyicu dep.
_SCRIPT_PREFIXES = {
    "CYRILLIC":  "cyrillic",
    "LATIN":     "latin",
    "GEORGIAN":  "georgian",
    "GREEK":     "greek",
    "ARABIC":    "arabic",
    "HEBREW":    "hebrew",
    "CJK":       "cjk",
    "HIRAGANA":  "japanese",
    "KATAKANA":  "japanese",
    "HANGUL":    "korean",
    "DEVANAGARI":"devanagari",
}


# ── normalise ────────────────────────────────────────────────────


def normalise(s: str) -> str:
    """NFC + strip zero-width and control characters (except \\n / \\t)."""
    if not isinstance(s, str):
        raise TypeError("normalise() needs a str")
    nfc = unicodedata.normalize("NFC", s)
    out = []
    for ch in nfc:
        if ch in _INVISIBLE_CHARS:
            continue
        cat = unicodedata.category(ch)
        if cat.startswith("C") and ch not in ("\n", "\t"):
            continue   # control / format chars
        out.append(ch)
    return "".join(out)


# ── script analysis ─────────────────────────────────────────────


def _script(ch: str) -> Optional[str]:
    if not ch.isalpha():
        return None
    try:
        name = unicodedata.name(ch)
    except ValueError:
        return None
    head = name.split(" ", 1)[0]
    return _SCRIPT_PREFIXES.get(head)


def mixed_scripts(s: str) -> dict[str, int]:
    """Return {script_name: char_count} for letters in `s`."""
    out: dict[str, int] = {}
    for ch in s:
        sc = _script(ch)
        if sc:
            out[sc] = out.get(sc, 0) + 1
    return out


def is_suspicious(s: str) -> bool:
    """Heuristic: more than one script AND the smaller script(s) account
    for fewer than 30% of letters → looks like a lookalike attack."""
    counts = mixed_scripts(s)
    if len(counts) < 2:
        return False
    total = sum(counts.values())
    if total == 0:
        return False
    sorted_counts = sorted(counts.values(), reverse=True)
    minority = sum(sorted_counts[1:])
    return 0 < minority < total * 0.30


# ── high-level safe() ──────────────────────────────────────────


@dataclasses.dataclass
class SafetyResult:
    text: str
    warnings: list[str]


def safe(s: str, *, allow_mixed: bool = False) -> SafetyResult:
    if not isinstance(s, str):
        return SafetyResult(text="", warnings=["non-string input dropped"])
    warnings: list[str] = []
    nfc = unicodedata.normalize("NFC", s)
    if nfc != s:
        warnings.append("normalised to NFC")
    out = normalise(s)
    if out != nfc:
        warnings.append("stripped invisible/control characters")
    if not allow_mixed and is_suspicious(out):
        scripts = mixed_scripts(out)
        warnings.append(
            "mixed scripts " + ", ".join(
                f"{k}={v}" for k, v in sorted(scripts.items(),
                                                key=lambda kv: -kv[1])))
    return SafetyResult(text=out, warnings=warnings)
