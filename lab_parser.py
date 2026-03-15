#!/usr/bin/env python3
"""
Parser for lab results from text and PDF files.
Extracts parameter name + value + unit from free-text.
Supports Russian, Georgian, English formats.
"""

import re
import os
from typing import List, Dict, Tuple, Optional

try:
    import pdfplumber
    HAS_PDF = True
except ImportError:
    HAS_PDF = False

from lab_reference import resolve_param, evaluate, LabResult


# ─────────────────────────────────────────────────────────────
# Extraction patterns
# Examples:
#   "Гемоглобин  12.5  g/L"
#   "WBC  5.2  10^9/L  (4.0-10.0)"
#   "Глюкоза: 5.6 ммоль/л"
#   "HbA1c 5.9%"
# ─────────────────────────────────────────────────────────────

# Number: "12.5" or "12,5" or "< 0.05" or ">100"
NUM_RE = r'[<>]?\s*(\d+[.,]\d+|\d+)'

# Unit chars (inner, no grouping): letters, /, ^, %, ⁹, etc.
UNIT_INNER = r'[\w/%µμ×⁹¹²³·\-\.]+'
# Unit group (optional capturing group)
UNIT_RE = r'(' + UNIT_INNER + r')?'

# Main extraction pattern: NAME [: = space] NUMBER [UNIT]
LAB_PATTERN = re.compile(
    r'([А-ЯЁа-яёA-Za-z][А-ЯЁа-яёA-Za-zა-ჿ0-9\-\s\(\)\.]{1,40}?)'  # name
    r'\s*[:=\s]\s*'
    r'(?:<\s*|>\s*)?(\d+[.,]\d+|\d+)'                                # value
    r'\s*' + UNIT_RE,
    re.UNICODE
)

# Pattern for tabular format: value in column after name on same line
TABLE_PATTERN = re.compile(
    r'^([А-ЯЁа-яёA-Za-zა-ჿ][^\t\n]{2,35})\s{2,}(\d+[.,]\d+|\d+)\s*(' + UNIT_INNER + r')?',
    re.MULTILINE | re.UNICODE
)


def _clean_num(s: str) -> float:
    return float(s.replace(',', '.').lstrip('<>').strip())


def extract_from_text(text: str, sex: str = "*",
                      age_group: str = "adult") -> List[LabResult]:
    """Extract and evaluate lab results from free text."""
    results: List[LabResult] = []
    seen: set = set()

    def _process(name_raw: str, value_raw: str, unit_raw: str = ""):
        param_id = resolve_param(name_raw.strip())
        if param_id and param_id not in seen:
            try:
                value = _clean_num(value_raw)
                result = evaluate(param_id, value, sex, age_group)
                if unit_raw:
                    result.unit = unit_raw
                results.append(result)
                seen.add(param_id)
            except (ValueError, ZeroDivisionError):
                pass

    # Try table pattern first (tabular lab reports)
    for m in TABLE_PATTERN.finditer(text):
        _process(m.group(1), m.group(2), m.group(3) or "")

    # Then general pattern
    for m in LAB_PATTERN.finditer(text):
        _process(m.group(1), m.group(2), m.group(3) or "")

    return results


def extract_from_pdf(pdf_path: str, sex: str = "*",
                     age_group: str = "adult") -> List[LabResult]:
    """Extract lab results from a PDF file."""
    if not HAS_PDF:
        return []
    try:
        all_text = []
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    all_text.append(t)
                # Also try table extraction
                tables = page.extract_tables()
                for table in tables:
                    for row in table:
                        if row:
                            all_text.append("  ".join(str(c) for c in row if c))
        combined = "\n".join(all_text)
        return extract_from_text(combined, sex, age_group)
    except Exception as e:
        return []


def extract_from_folder(folder_path: str, sex: str = "*",
                        age_group: str = "adult") -> Dict[str, List[LabResult]]:
    """
    Scan a patient folder for all lab data.
    Returns {filename: [LabResult, ...]}
    """
    results: Dict[str, List[LabResult]] = {}

    for fname in os.listdir(folder_path):
        fpath = os.path.join(folder_path, fname)
        items: List[LabResult] = []

        if fname.endswith(".pdf"):
            items = extract_from_pdf(fpath, sex, age_group)
        elif fname.endswith((".txt", "")) and os.path.isfile(fpath):
            try:
                text = open(fpath, "r", encoding="utf-8", errors="replace").read()
                items = extract_from_text(text, sex, age_group)
            except Exception:
                pass

        if items:
            results[fname] = items

    return results


def merge_results(results_by_file: Dict[str, List[LabResult]]) -> List[LabResult]:
    """Flatten and deduplicate (latest wins)."""
    seen: Dict[str, LabResult] = {}
    for fname, items in results_by_file.items():
        for r in items:
            seen[r.param_id] = r  # later files override
    return list(seen.values())


def format_results(results: List[LabResult]) -> str:
    """Human-readable table."""
    if not results:
        return "  Лабораторных данных не найдено"

    lines = [f"{'Параметр':<35} {'Значение':>10}  {'Ед.':>12}  {'Норма':>18}  {'Статус'}"]
    lines.append("─" * 95)

    for r in sorted(results, key=lambda x: x.status not in ("critical_low", "critical_high")):
        from lab_reference import STATUS_EMOJI
        ref_str = ""
        if r.ref:
            ref_str = f"{r.ref.low}–{r.ref.high}"
        dev_str = f" ({r.deviation_pct:+.0f}%)" if r.deviation_pct else ""
        status_str = STATUS_EMOJI.get(r.status, r.status)
        lines.append(
            f"{r.name:<35} {r.value:>10.2f}  {r.unit:>12}  {ref_str:>18}  "
            f"{status_str}{dev_str}"
        )

    return "\n".join(lines)
