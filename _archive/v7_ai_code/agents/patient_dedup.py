"""agents/patient_dedup.py — patient encounter dedup detector (DD1, 2026-05-03).

Walk Patients/<Surname_Name_DOB>/ and flag folder pairs that look like
the same person under different spellings:

  * NFC normalisation + lowercase + strip non-letters from name
  * mixed-script lookalikes (Cyrillic 'о' vs Latin 'o') treated as same
  * exact DOB match → strong signal
  * absent/sentinel DOB (`2000_01_01`) → tiebreak by name only

Returns clusters of likely duplicates so the user can manually merge.
We never auto-merge — this module is read-only.

Public API:
    fingerprint(folder_name) -> str
    duplicates(today=None) -> list[Cluster]
    summary() -> str
"""
from __future__ import annotations

import collections
import dataclasses
import logging
import os
import re
import unicodedata
from pathlib import Path
from typing import Optional

log = logging.getLogger("aim.patient_dedup")


def patients_dir() -> Path:
    env = os.environ.get("AIM_PATIENTS_DIR")
    if env:
        return Path(env).expanduser()
    here = Path(__file__).resolve().parent.parent
    return here / "Patients"


# ── data ─────────────────────────────────────────────────────────


@dataclasses.dataclass
class Cluster:
    fingerprint: str
    folders: list[str]
    likely_dob: Optional[str] = None

    @property
    def n_folders(self) -> int:
        return len(self.folders)


# ── fingerprint ──────────────────────────────────────────────────


# Latin → Cyrillic homograph map for common confusables.
_LATIN_TO_CYRILLIC = {
    "a": "а", "c": "с", "e": "е", "o": "о", "p": "р",
    "x": "х", "y": "у", "h": "н", "k": "к", "i": "і",
}


def _normalise_name(name: str) -> str:
    """Coerce 'Иванoв' (homograph mix) into a stable form, but leave
    purely-Latin or purely-Cyrillic names alone.

    Strategy:
      1. NFC + lowercase, drop non-letter chars.
      2. Detect dominant script.
      3. If both scripts appear, fold the minority's lookalikes into
         the majority via the homograph map.
    """
    s = unicodedata.normalize("NFC", name).lower()
    s = re.sub(r"[^a-zа-яёҐґії-]", "", s)
    if not s:
        return s
    cyr = sum(1 for ch in s if "а" <= ch <= "я" or ch in "ёії")
    lat = sum(1 for ch in s if "a" <= ch <= "z")
    if cyr and lat:
        if cyr >= lat:
            s = "".join(_LATIN_TO_CYRILLIC.get(ch, ch) for ch in s)
        else:
            inv = {v: k for k, v in _LATIN_TO_CYRILLIC.items()}
            s = "".join(inv.get(ch, ch) for ch in s)
    return s[:30]


def fingerprint(folder_name: str) -> tuple[str, str, Optional[str]]:
    """Decompose `Surname_Name_YYYY_MM_DD` into a normalised fingerprint.

    Returns (canonical, name_only_canonical, dob_iso) where:
      * canonical:   "{name_canon}|{dob}"
      * name_only:   "{name_canon}|"   (dob ignored, useful when dob unknown)
      * dob_iso:     "YYYY-MM-DD" or None
    """
    parts = folder_name.split("_")
    dob: Optional[str] = None
    if len(parts) >= 5 and re.match(r"^\d{4}$", parts[-3]) \
            and re.match(r"^\d{2}$", parts[-2]) \
            and re.match(r"^\d{2}$", parts[-1]):
        dob = f"{parts[-3]}-{parts[-2]}-{parts[-1]}"
        name_parts = parts[:-3]
    else:
        name_parts = parts
    name_canon = "_".join(_normalise_name(p) for p in name_parts if p)
    return f"{name_canon}|{dob or ''}", f"{name_canon}|", dob


# ── duplicate scan ──────────────────────────────────────────────


def duplicates(scope: Optional[Path] = None) -> list[Cluster]:
    base = scope or patients_dir()
    if not base.exists():
        return []
    folders = [p.name for p in base.iterdir()
               if p.is_dir() and p.name != "INBOX"]

    by_canonical: dict[str, list[str]] = collections.defaultdict(list)
    by_name_only: dict[str, list[str]] = collections.defaultdict(list)
    dob_for: dict[str, Optional[str]] = {}

    for f in folders:
        canon, name_only, dob = fingerprint(f)
        by_canonical[canon].append(f)
        by_name_only[name_only].append(f)
        dob_for[f] = dob

    out: list[Cluster] = []
    seen_folders: set[str] = set()

    # Strong matches: same canonical key (name + dob)
    for canon, group in by_canonical.items():
        if len(group) < 2:
            continue
        out.append(Cluster(fingerprint=canon, folders=sorted(group),
                            likely_dob=dob_for[group[0]]))
        seen_folders.update(group)

    # Soft matches: same name canon, different DOB (one likely sentinel)
    for name_only, group in by_name_only.items():
        if len(group) < 2:
            continue
        # Skip groups already covered as strong matches.
        already_strong = any(set(group) <= set(c.folders) for c in out)
        if already_strong:
            continue
        # Only flag if at least one folder has the sentinel 2000_01_01
        # (i.e. unknown DOB collapsing into another encounter).
        dobs = {dob_for[f] for f in group}
        if "2000-01-01" not in dobs and len(dobs) > 1:
            # Distinct known DOBs → probably truly different patients.
            continue
        out.append(Cluster(fingerprint=name_only,
                            folders=sorted(group),
                            likely_dob=None))
    return out


def summary() -> str:
    clusters = duplicates()
    if not clusters:
        return "(no duplicate patient folders detected)"
    parts = [f"👥 Duplicate patient folders ({len(clusters)} clusters)"]
    for c in clusters[:8]:
        parts.append(f"  • {c.n_folders} folders share fingerprint "
                     f"{c.fingerprint!r}")
        for f in c.folders:
            parts.append(f"    - {f}")
    return "\n".join(parts)
