#!/usr/bin/env python3
"""validate/ze_vstar.py — проверяет согласованность v* во всех проектах.

v* (fixed point Ze Theory) должен быть одинаковым в:
- Ze/CONCEPT.md
- BioSense/CONCEPT.md
- Poincaré/CONCEPT.md
- registry.json
"""

import json
import re
import sys
from pathlib import Path

AIM_DIR = Path(__file__).resolve().parent.parent
REGISTRY_PATH = AIM_DIR / "registry.json"

# Projects that should mention v*
VSTAR_PROJECTS = ["ze_theory", "biosense", "poincare"]

# Regex patterns for v* values
VSTAR_PATTERNS = [
    (r'v\*\s*=\s*(-?[\d.]+)', "v* = X.XX"),
    (r'v\s*\\\^\{\\ast\}\s*=\s*(-?[\d.]+)', "v^* = X.XX (LaTeX)"),
    (r'v\*\s*=\s*(-?[\d.]+)', "v* = X.XX"),
]


def load_registry():
    with open(REGISTRY_PATH) as f:
        return json.load(f)


def find_vstar_in_file(path: Path) -> list[float]:
    """Find all v* values in a file."""
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    values = []
    for pat, _ in VSTAR_PATTERNS:
        for m in re.finditer(pat, text):
            val = float(m.group(1))
            values.append(val)
    return values


def main():
    reg = load_registry()
    errors = 0

    print("=" * 60)
    print("Валидация: v* (Ze fixed point)")
    print("=" * 60)

    # Expected from registry
    expected_python = reg["projects"]["ze_theory"]["key_params"].get("v_star")
    expected_article = reg["projects"]["ze_theory"]["key_params"].get("v_star_article_form")

    print(f"  Эталон (реестр):")
    print(f"    v* Python form  = {expected_python}")
    print(f"    v* Article form = {expected_article}")
    print()

    for proj_key in VSTAR_PROJECTS:
        proj = reg["projects"][proj_key]
        concept_path = (AIM_DIR / proj["path"] / "CONCEPT.md").resolve()
        values = find_vstar_in_file(concept_path)

        if not values:
            print(f"  ⚠ {proj['name']}: v* не найден в CONCEPT.md")
            continue

        # Check if expected_python is in values (allow small float differences)
        found_expected = False
        for v in values:
            if abs(v - expected_python) < 0.001 or abs(v - expected_article) < 0.001:
                found_expected = True
                break

        if found_expected:
            print(f"  ✓ {proj['name']}: v* = {values} — OK")
        else:
            print(f"  ✗ {proj['name']}: v* = {values}, ожидается {expected_python} или {expected_article}")
            errors += 1

    print(f"\nРезультат: {errors} ошибок")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
