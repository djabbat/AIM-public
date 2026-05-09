#!/usr/bin/env python3
"""
tools/lab_evaluate.py — thin CLI shim around `lab_reference.py::evaluate`.

Used by `aim-patient-workspace` Labs tab (Phoenix LiveView).

Stage 1 in this overnight session — Rust port of LAB_RANGES is deferred
(P3 closure of `lab_reference.py` per STACK.md frozen-Python rule). Until
then this CLI is the single calling surface from Rust binaries / Phoenix.

USAGE:
    echo '[{"analyte_key":"hemoglobin","value":13.7}, ...]' \
        | python3 tools/lab_evaluate.py evaluate --sex F

OUTPUT:
    JSON array on stdout, one entry per input. Each entry adds:
        - status: normal / low / high / critical_low / critical_high / unknown
        - reference: "low–high" string (in default unit)
        - display: human label
        - notes: optional caveat
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

# Allow running from anywhere — add repo root to path.
REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from lab_reference import evaluate, LAB_RANGES  # noqa: E402


def _aim_lab_units_bin() -> Path | None:
    """Locate the aim-lab-units Rust binary; returns None if not built."""
    candidates = [
        REPO / "rust-core" / "target" / "release" / "aim-lab-units",
        REPO / "rust-core" / "target" / "debug" / "aim-lab-units",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def batch_convert(items: list[dict]) -> list[dict]:
    """Batch-convert a list of {analyte_key, value, source_unit, target_unit}.

    Returns Conversion records. Falls back to passthrough (value unchanged,
    was_converted=False) if the binary isn't built — caller must surface
    a unit-mismatch warning rather than silently mis-evaluate.
    """
    if not items:
        return []

    bin_path = _aim_lab_units_bin()
    if bin_path is None:
        return [
            {
                "value": it["value"],
                "source_unit_raw": it.get("source_unit", ""),
                "target_unit": it.get("target_unit", ""),
                "was_converted": False,
            }
            for it in items
        ]

    proc = subprocess.run(
        [str(bin_path), "batch"],
        input=json.dumps(items),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return [
            {
                "value": it["value"],
                "source_unit_raw": it.get("source_unit", ""),
                "target_unit": it.get("target_unit", ""),
                "was_converted": False,
            }
            for it in items
        ]
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return [
            {
                "value": it["value"],
                "source_unit_raw": it.get("source_unit", ""),
                "target_unit": it.get("target_unit", ""),
                "was_converted": False,
            }
            for it in items
        ]


def resolve_sex_specific(analyte_key: str, sex: str | None) -> str:
    """`hemoglobin` → `hemoglobin_m` or `hemoglobin_f` based on sex.

    Falls back to the generic key (which won't exist in LAB_RANGES — that
    triggers `status: unknown`, which is honest behaviour).
    """
    if not sex:
        return analyte_key
    s = sex.strip().lower()
    suffix = "_m" if s in {"m", "male"} else ("_f" if s in {"f", "female"} else "")
    if not suffix:
        return analyte_key
    candidate = f"{analyte_key}{suffix}"
    if candidate in LAB_RANGES:
        return candidate
    return analyte_key


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("evaluate", help="evaluate ParsedLab JSON list from stdin")
    e.add_argument("--sex", default=None, help="patient sex M/F (for sex-specific ranges)")
    args = p.parse_args()

    if args.cmd != "evaluate":
        print("unknown subcommand", file=sys.stderr)
        return 2

    raw = sys.stdin.read()
    if not raw.strip():
        print("[]")
        return 0

    try:
        items = json.loads(raw)
    except json.JSONDecodeError as ex:
        print(f"bad input json: {ex}", file=sys.stderr)
        return 2

    # Step 1: build conversion batch (only items with non-empty unit_raw).
    conv_inputs: list[dict] = []
    conv_meta: list[tuple[int, str]] = []  # (item_idx, resolved_key)
    for idx, item in enumerate(items):
        analyte_key = item.get("analyte_key", "")
        value = item.get("value", None)
        if not analyte_key or value is None:
            continue
        try:
            value = float(value)
        except (TypeError, ValueError):
            continue
        resolved_key = resolve_sex_specific(analyte_key, args.sex)
        ref_unit = LAB_RANGES.get(resolved_key, {}).get("unit", "")
        unit_raw = item.get("unit_raw", "") or ""
        if ref_unit and unit_raw:
            conv_inputs.append({
                "analyte_key": analyte_key,
                "value": value,
                "source_unit": unit_raw,
                "target_unit": ref_unit,
            })
            conv_meta.append((idx, resolved_key))

    conversions = batch_convert(conv_inputs) if conv_inputs else []
    conv_by_idx: dict[int, dict] = {}
    for c, (idx, _key) in zip(conversions, conv_meta):
        conv_by_idx[idx] = c

    # Step 2: evaluate against reference range (using converted value if available).
    out = []
    for idx, item in enumerate(items):
        analyte_key = item.get("analyte_key", "")
        value = item.get("value", None)
        if not analyte_key or value is None:
            continue
        try:
            value = float(value)
        except (TypeError, ValueError):
            continue
        resolved_key = resolve_sex_specific(analyte_key, args.sex)

        conv = conv_by_idx.get(idx)
        eval_value = conv["value"] if conv and conv["was_converted"] else value
        result = evaluate(resolved_key, eval_value)

        # Surface conversion + raw value to UI for transparency.
        result["raw_value"] = value
        if conv:
            result["was_unit_converted"] = conv["was_converted"]
            result["converted_value"] = conv["value"] if conv["was_converted"] else None
        else:
            result["was_unit_converted"] = False
            result["converted_value"] = None

        # Carry over abbreviation / line_no / unit_raw from input for UI traceability.
        for passthrough in ("abbreviation", "line_no", "unit_raw"):
            if passthrough in item:
                result[passthrough] = item[passthrough]
        out.append(result)

    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
