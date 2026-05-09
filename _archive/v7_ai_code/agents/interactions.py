"""agents/interactions.py — thin Python shim over the
`aim-interactions` Rust binary (Phase 8 Week 2, 2026-05-07).

Drug-drug interaction lookup. The static table (~30 hardcoded pairs
with PMIDs / mechanisms / recommendations from peer-reviewed sources)
lives in `rust-core/crates/aim-interactions`. This module exists only
to give Python callers (regimen_validator, doctor.py, lab agent) a
Pythonic API and to preserve the public surface (`check_interaction`,
`check_regimen`, `format_regimen_report`, `Interaction`, `DISCLAIMER`)
so existing imports keep working.

If you find yourself adding a new drug pair or editing a mechanism —
STOP and edit the Rust crate's `_TABLE`, then rebuild the binary.
"""
from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

log = logging.getLogger("aim.interactions")

DISCLAIMER = (
    "AIM drug-interaction database is a curated stub (~30 high-impact "
    "pairs). NOT a replacement for RxNav / DrugBank / FDA DailyMed. "
    "Always cross-check before prescribing. AIM v0.1, 2026-04-21."
)

SEVERITY_ORDER = {
    "contraindicated": 0,
    "major":           1,
    "moderate":        2,
    "minor":           3,
    "no_known":        4,
}


@dataclass(frozen=True)
class Interaction:
    """Result of a pair check. Immutable so it can be cached freely."""
    drug_a: str
    drug_b: str
    severity: str
    mechanism: str
    recommendation: str
    source: str
    disclaimer: str = DISCLAIMER

    def to_dict(self) -> dict:
        return asdict(self)


def _binary_path() -> Path:
    return (
        Path(__file__).resolve().parent.parent
        / "rust-core" / "target" / "release" / "aim-interactions"
    )


def _run(args: list[str]) -> str:
    bin_path = _binary_path()
    if not bin_path.exists():
        raise FileNotFoundError(
            f"aim-interactions binary not built at {bin_path}; "
            "run `cargo build -p aim-interactions --release` in rust-core/"
        )
    proc = subprocess.run(
        [str(bin_path), *args],
        capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"aim-interactions {args[0]} failed: {proc.stderr.strip()}"
        )
    return proc.stdout


def _interaction_from_json(j: dict) -> Interaction:
    return Interaction(
        drug_a=j["drug_a"],
        drug_b=j["drug_b"],
        severity=j["severity"],
        mechanism=j["mechanism"],
        recommendation=j["recommendation"],
        source=j["source"],
    )


def check_interaction(drug_a: str, drug_b: str) -> Interaction:
    """Return an Interaction record for the pair (drug_a, drug_b).

    If the pair is not in the static table, severity='no_known' is
    returned (we never fabricate). Same drug passed twice → 'no_known'
    with a note.
    """
    out = _run(["check", drug_a, drug_b])
    return _interaction_from_json(json.loads(out))


def check_regimen(drugs: list[str]) -> list[Interaction]:
    """Return Interaction records for every unordered pair, sorted from
    most severe to least severe."""
    if not drugs or len(drugs) < 2:
        return []
    out = _run(["regimen", *drugs])
    return [_interaction_from_json(json.loads(line))
            for line in out.splitlines() if line.strip()]


def format_regimen_report(
    interactions: list[Interaction],
    lang: str = "en",
    include_no_known: bool = False,
) -> str:
    """Human-readable summary of a regimen check.

    Note: this shim reconstructs the regimen from the supplied
    interactions list and asks the Rust binary to format. If the
    caller built `interactions` by hand (rare), it must be a valid
    output of `check_regimen` — otherwise pass `drugs` to
    `_format_via_drugs` directly.
    """
    drugs: list[str] = []
    for ix in interactions:
        if ix.drug_a not in drugs:
            drugs.append(ix.drug_a)
        if ix.drug_b not in drugs:
            drugs.append(ix.drug_b)
    args = ["format", "--lang", lang]
    if include_no_known:
        args.append("--include-no-known")
    args.extend(drugs)
    return _run(args).rstrip("\n")


def known_drugs() -> list[str]:
    """Canonical names of all drugs/supplements known to AIM."""
    return [d.strip() for d in _run(["known-drugs"]).splitlines() if d.strip()]


# ── Lazy `_TABLE` dict for diagnostic tests ─────────────────────────────────
# The Python implementation used to expose `_TABLE: dict[frozenset, dict]`
# directly. The shim populates it on first access by calling
# `aim-interactions dump-table`.

class _LazyTable:
    """`{frozenset({drug_a, drug_b}): {severity, mechanism, recommendation,
    source}}` — populated on first read."""
    _data: dict[frozenset[str], dict] | None = None

    @classmethod
    def _load(cls) -> dict[frozenset[str], dict]:
        if cls._data is None:
            cls._data = {}
            for line in _run(["dump-table"]).splitlines():
                line = line.strip()
                if not line:
                    continue
                j = json.loads(line)
                cls._data[frozenset({j["drug_a"], j["drug_b"]})] = {
                    "severity": j["severity"],
                    "mechanism": j["mechanism"],
                    "recommendation": j["recommendation"],
                    "source": j["source"],
                }
        return cls._data

    def __getitem__(self, k):
        return self._load()[k]

    def get(self, k, default=None):
        return self._load().get(k, default)

    def items(self):
        return self._load().items()

    def keys(self):
        return self._load().keys()

    def values(self):
        return self._load().values()

    def __iter__(self):
        return iter(self._load())

    def __len__(self):
        return len(self._load())

    def __contains__(self, k):
        return k in self._load()


_TABLE: _LazyTable = _LazyTable()


__all__ = [
    "Interaction",
    "check_interaction",
    "check_regimen",
    "format_regimen_report",
    "known_drugs",
    "DISCLAIMER",
    "SEVERITY_ORDER",
]
