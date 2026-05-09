#!/usr/bin/env python3
"""validate/counter_numbering.py — проверяет согласованность номеров счётчиков MCOA.

Читает registry.json, затем CONCEPT.md каждого counter-проекта и сверяет,
что номер счётчика везде один и тот же.
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


def find_concept_md(project_path: str) -> Path:
    """Resolve project path relative to AIM dir."""
    p = (AIM_DIR / project_path / "CONCEPT.md").resolve()
    if not p.exists():
        print(f"  ⚠ CONCEPT.md не найден: {p}")
    return p


def extract_counter_from_concept(path: Path) -> set[int]:
    """Extract counter number(s) mentioned in CONCEPT.md."""
    if not path.exists():
        return set()
    text = path.read_text(encoding="utf-8", errors="replace")
    # Look for patterns like "Counter #N" or "Counter N" or "C#N"
    patterns = [
        r'Counter\s*#?\s*(\d+)',
        r'C#(\d+)',
        r'counter\s*#?\s*(\d+)',
        r'счётчик\s*#?\s*(\d+)',
        r'Counter\s+#(\d+)',
    ]
    found = set()
    for pat in patterns:
        for m in re.finditer(pat, text, re.IGNORECASE):
            found.add(int(m.group(1)))
    return found


def main():
    reg = load_registry()
    errors = 0
    warnings = 0

    print("=" * 60)
    print("Валидация: номера счётчиков MCOA")
    print("=" * 60)

    for key, proj in reg["projects"].items():
        counter_num = proj.get("counter")
        if counter_num is None:
            continue  # не счётчик

        concept_path = find_concept_md(proj["path"])
        found_in_concept = extract_counter_from_concept(concept_path)

        label = proj["counter_label"]
        name = proj["name"]

        if not found_in_concept:
            print(f"  ⚠ {name}: счётчик #{counter_num} в реестре, но номер не найден в CONCEPT.md")
            warnings += 1
        elif counter_num not in found_in_concept:
            print(f"  ✗ {name}: реестр говорит #{counter_num} ({label}), CONCEPT.md содержит {found_in_concept}")
            errors += 1
        else:
            print(f"  ✓ {name}: #{counter_num} — OK")

    # Check for duplicates
    counters_seen = {}
    for key, proj in reg["projects"].items():
        c = proj.get("counter")
        if c is None:
            continue
        if c in counters_seen:
            print(f"  ✗ ДУБЛИКАТ: #{c} у {counters_seen[c]} и {proj['name']}")
            errors += 1
        counters_seen[c] = proj["name"]

    print(f"\nРезультат: {errors} ошибок, {warnings} предупреждений")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
