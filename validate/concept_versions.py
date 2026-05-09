#!/usr/bin/env python3
"""validate/concept_versions.py — проверяет версии CONCEPT.md во всех проектах.

Сверяет версии из registry.json с тем, что реально написано в CONCEPT.md файлах.
"""

import json
import re
import sys
from pathlib import Path

AIM_DIR = Path(__file__).resolve().parent.parent
REGISTRY_PATH = AIM_DIR / "registry.json"


def load_registry():
    with open(REGISTRY_PATH) as f:
        return json.load(f)


def extract_version_from_concept(path: Path) -> str | None:
    """Extract version string from CONCEPT.md."""
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8", errors="replace")

    # Try multiple patterns
    patterns = [
        r'\*\*Версия:\*\*\s*v?([\d.]+)',
        r'\*\*Version:\*\*\s*v?([\d.]+)',
        r'Версия:\*\*\s*v?([\d.]+)',
        r'Version:\*\*\s*v?([\d.]+)',
        r'версия[:\s]*v?([\d.]+)',
        r'version[:\s]*v?([\d.]+)',
        r'# .+ v([\d.]+)',
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(1)
    return None


def main():
    reg = load_registry()
    errors = 0
    warnings = 0
    missing = 0

    print("=" * 60)
    print("Валидация: версии CONCEPT.md")
    print("=" * 60)

    for key, proj in reg["projects"].items():
        concept_path = (AIM_DIR / proj["path"] / "CONCEPT.md").resolve()
        reg_version = proj.get("version", "?")
        file_version = extract_version_from_concept(concept_path)

        if not concept_path.exists():
            print(f"  ✗ {proj['name']}: CONCEPT.md не найден: {concept_path}")
            missing += 1
            continue

        if file_version is None:
            print(f"  ⚠ {proj['name']}: версия не найдена в CONCEPT.md (реестр: v{reg_version})")
            warnings += 1
        elif file_version != reg_version:
            print(f"  ✗ {proj['name']}: CONCEPT.md = v{file_version}, реестр = v{reg_version}")
            errors += 1
        else:
            print(f"  ✓ {proj['name']}: v{reg_version} — OK")

    print(f"\nРезультат: {errors} ошибок, {warnings} предупреждений, {missing} не найден")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
