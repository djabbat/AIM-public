#!/usr/bin/env python3
"""scripts/pilot_cohort_extract.py — cohort-level extraction for PAM-13 pilot.

STRATEGY.md P1-3 / docs/operational/PILOT_PROTOCOL.md §7 implementation.

Walks `Patients/<id>/` and pulls anonymized aggregate metrics for the pilot
cohort:
  - per-patient PAM-13 trajectory (T0 + T1 scores, delta, classification)
  - co-design event counts per patient + per kind
  - disagreement zone distribution
  - kernel violation tally (from `~/.cache/aim/diagnostic_ledger.db`)
  - cost per patient-month (from `~/.cache/aim/cost_ledger.db` if present)

Privacy: all output is **aggregated by patient id only** — no names, no
DOB, no PII fields. Patient id stays as folder name (per AIM convention
SURNAME_NAME_YYYY_MM_DD); for publication, swap to a study code map.

Usage:
    python3 scripts/pilot_cohort_extract.py [--patients-dir DIR] [--out PATH]
    python3 scripts/pilot_cohort_extract.py --json    # machine-readable
    python3 scripts/pilot_cohort_extract.py --csv     # for stats software

Output: human-readable summary on stdout by default; with --json or --csv
emits structured data.
"""
from __future__ import annotations

import argparse
import csv
import dataclasses
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Iterable, Optional


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PATIENTS_DIR_DEFAULT = PROJECT_ROOT / "Patients"
LEDGER_DB_DEFAULT = Path.home() / ".cache" / "aim" / "diagnostic_ledger.db"
COST_DB_DEFAULT = Path.home() / ".cache" / "aim" / "cost_ledger.db"

# PAM-13 thresholds (per THEORY.md §3.3, source: Hibbard 2009).
MCID = 5.4
MDC = 7.2


@dataclasses.dataclass
class PatientRow:
    patient_id: str
    n_pam_admins: int
    pam_t0_score: Optional[float]
    pam_t0_date: Optional[str]
    pam_t0_level: Optional[int]
    pam_t1_score: Optional[float]
    pam_t1_date: Optional[str]
    pam_t1_level: Optional[int]
    delta: Optional[float]
    classification: str   # "improved" | "stable" | "regressed" | "incomplete"
    n_codesign_events: int
    codesign_kinds: dict[str, int]
    n_disagreement_events: int


# ── extraction helpers ──────────────────────────────────────────────────


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _classify_delta(delta: Optional[float]) -> str:
    if delta is None:
        return "incomplete"
    if delta >= MCID:
        return "improved"
    if delta <= -MCID:
        return "regressed"
    return "stable"


def _extract_patient(pdir: Path) -> Optional[PatientRow]:
    pam_log = pdir / "_pam_history.jsonl"
    if not pam_log.exists():
        # Patient with no PAM-13 administration → not enrolled.
        return None
    pam_admins = _read_jsonl(pam_log)
    if not pam_admins:
        return None

    # Sort by `date` — JSONL spec emits ISO date string per row.
    pam_admins.sort(key=lambda r: str(r.get("date", "")))

    t0 = pam_admins[0]
    t1 = pam_admins[-1] if len(pam_admins) >= 2 else None

    delta: Optional[float] = None
    if t1 is not None and t1 is not t0:
        try:
            delta = float(t1["score"]) - float(t0["score"])
        except (KeyError, TypeError, ValueError):
            delta = None

    codesign_events = _read_jsonl(pdir / "_codesign.jsonl")
    codesign_kinds: Counter = Counter()
    for ev in codesign_events:
        kind = ev.get("kind")
        if kind:
            codesign_kinds[kind] += 1

    disagreement_events = _read_jsonl(pdir / "_disagreement.jsonl")

    return PatientRow(
        patient_id=pdir.name,
        n_pam_admins=len(pam_admins),
        pam_t0_score=float(t0.get("score")) if t0.get("score") is not None else None,
        pam_t0_date=str(t0.get("date")) if t0.get("date") else None,
        pam_t0_level=int(t0.get("level")) if t0.get("level") is not None else None,
        pam_t1_score=(float(t1.get("score")) if t1 and t1.get("score") is not None else None),
        pam_t1_date=(str(t1.get("date")) if t1 and t1.get("date") else None),
        pam_t1_level=(int(t1.get("level")) if t1 and t1.get("level") is not None else None),
        delta=delta,
        classification=_classify_delta(delta),
        n_codesign_events=len(codesign_events),
        codesign_kinds=dict(codesign_kinds),
        n_disagreement_events=len(disagreement_events),
    )


def extract_cohort(patients_dir: Path) -> list[PatientRow]:
    """Walk Patients/* — skip INBOX / non-folders / fixtures starting with '_'."""
    if not patients_dir.exists():
        return []
    rows: list[PatientRow] = []
    for entry in sorted(patients_dir.iterdir()):
        if not entry.is_dir():
            continue
        if entry.name in {"INBOX", "_runtime_fixtures"}:
            continue
        if entry.name.startswith("_"):
            continue
        row = _extract_patient(entry)
        if row is not None:
            rows.append(row)
    return rows


# ── ledger-side aggregates (kernel violations + cost) ──────────────────


def kernel_violation_count(db: Path = LEDGER_DB_DEFAULT) -> Optional[int]:
    """Count rows in kernel violations table (best-effort; returns None if
    table absent — schema compatibility check, не failure)."""
    if not db.exists():
        return None
    try:
        with sqlite3.connect(db) as conn:
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
            if "kernel_violations" not in tables:
                return None
            n = conn.execute("SELECT COUNT(*) FROM kernel_violations").fetchone()[0]
            return int(n)
    except sqlite3.Error:
        return None


def cost_total_usd(db: Path = COST_DB_DEFAULT) -> Optional[float]:
    if not db.exists():
        return None
    try:
        with sqlite3.connect(db) as conn:
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
            if "calls" not in tables:
                return None
            total = conn.execute(
                "SELECT COALESCE(SUM(cost_usd), 0) FROM calls"
            ).fetchone()[0]
            return float(total)
    except sqlite3.Error:
        return None


# ── output formatters ───────────────────────────────────────────────────


def _summary_text(rows: list[PatientRow], kv_count: Optional[int],
                   cost_total: Optional[float]) -> str:
    if not rows:
        return "(no enrolled patients found — Patients/ has no _pam_history.jsonl)"

    n = len(rows)
    completed = [r for r in rows if r.delta is not None]
    improved = [r for r in completed if r.classification == "improved"]
    stable = [r for r in completed if r.classification == "stable"]
    regressed = [r for r in completed if r.classification == "regressed"]

    deltas = [r.delta for r in completed if r.delta is not None]
    mean_delta = sum(deltas) / len(deltas) if deltas else None

    parts = [
        f"📊 Pilot cohort summary — {n} enrolled, {len(completed)} completed (T0+T1)",
        "",
        "Primary outcome (PAM-13 trajectory):",
        f"  improved   (Δ ≥ {MCID:.1f}): {len(improved):>3} ({len(improved)/max(1, len(completed)):.0%})",
        f"  stable                   : {len(stable):>3} ({len(stable)/max(1, len(completed)):.0%})",
        f"  regressed (Δ ≤ -{MCID:.1f}): {len(regressed):>3} ({len(regressed)/max(1, len(completed)):.0%})",
    ]
    if mean_delta is not None:
        parts.append(f"  mean Δ                   : {mean_delta:+.2f} points (MCID = {MCID})")
    parts.append("")
    parts.append("Adherence (co-design):")
    n_with_codesign = sum(1 for r in rows if r.n_codesign_events > 0)
    parts.append(f"  patients with ≥1 codesign event: {n_with_codesign}/{n} ({n_with_codesign/max(1, n):.0%})")
    if rows:
        kinds_total: Counter = Counter()
        for r in rows:
            kinds_total.update(r.codesign_kinds)
        if kinds_total:
            parts.append("  events by kind: " + ", ".join(f"{k}={v}" for k, v in kinds_total.most_common()))
    parts.append("")
    parts.append("Safety:")
    if kv_count is None:
        parts.append("  kernel violations: (table not found — fresh install or no telemetry)")
    else:
        parts.append(f"  kernel violations (all-time): {kv_count}")
    if cost_total is None:
        parts.append("  cost ledger: (not present)")
    else:
        per_patient = cost_total / max(1, n)
        parts.append(f"  total LLM cost: ${cost_total:.2f} (~${per_patient:.2f}/patient)")

    parts.append("")
    parts.append("Per-patient detail (use --json/--csv for full export):")
    for r in rows[:10]:
        d = f"{r.delta:+.1f}" if r.delta is not None else " n/a"
        parts.append(
            f"  {r.patient_id[:48]:<48s}  T0={r.pam_t0_score or 0:>5.1f}  "
            f"T1={r.pam_t1_score or 0:>5.1f}  Δ={d:>6s}  {r.classification:<12s}  "
            f"codesign={r.n_codesign_events}"
        )
    if len(rows) > 10:
        parts.append(f"  (+{len(rows) - 10} more — pass --json for all)")
    return "\n".join(parts)


def _json_payload(rows: list[PatientRow], kv_count: Optional[int],
                   cost_total: Optional[float]) -> dict:
    return {
        "n_enrolled": len(rows),
        "thresholds": {"mcid": MCID, "mdc": MDC},
        "kernel_violations": kv_count,
        "cost_total_usd": cost_total,
        "patients": [dataclasses.asdict(r) for r in rows],
    }


def _write_csv(rows: list[PatientRow], path: Path) -> None:
    fieldnames = [
        "patient_id", "n_pam_admins",
        "pam_t0_score", "pam_t0_date", "pam_t0_level",
        "pam_t1_score", "pam_t1_date", "pam_t1_level",
        "delta", "classification",
        "n_codesign_events", "n_disagreement_events",
    ]
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            d = dataclasses.asdict(r)
            d.pop("codesign_kinds", None)
            w.writerow(d)


# ── CLI ─────────────────────────────────────────────────────────────────


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="PAM-13 pilot cohort extractor")
    p.add_argument("--patients-dir", type=Path, default=PATIENTS_DIR_DEFAULT)
    p.add_argument("--ledger-db", type=Path, default=LEDGER_DB_DEFAULT)
    p.add_argument("--cost-db", type=Path, default=COST_DB_DEFAULT)
    p.add_argument("--out", type=Path, help="Write JSON / CSV to this path "
                   "instead of stdout (auto-detect by extension)")
    p.add_argument("--json", action="store_true", help="Emit JSON")
    p.add_argument("--csv", action="store_true", help="Emit CSV (requires --out)")
    args = p.parse_args(argv)

    rows = extract_cohort(args.patients_dir)
    kv = kernel_violation_count(args.ledger_db)
    cost = cost_total_usd(args.cost_db)

    if args.csv:
        if not args.out:
            print("--csv requires --out PATH", file=sys.stderr)
            return 2
        _write_csv(rows, args.out)
        print(f"Wrote {len(rows)} rows → {args.out}", file=sys.stderr)
        return 0

    if args.json:
        payload = _json_payload(rows, kv, cost)
        out = json.dumps(payload, ensure_ascii=False, indent=2)
        if args.out:
            args.out.write_text(out, encoding="utf-8")
            print(f"Wrote payload → {args.out}", file=sys.stderr)
        else:
            print(out)
        return 0

    text = _summary_text(rows, kv, cost)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print(f"Wrote summary → {args.out}", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
