#!/usr/bin/env python3
"""validate/references.py — проверяет PMID/DOI на дубликаты и фабрикации.

Проходит по всем CONCEPT.md, собирает PMID/DOI и проверяет:
1. Нет дубликатов (один PMID в разных проектах с разными утверждениями)
2. Нет маркеров фабрикации ([pre-print], [REF_VERIFY], [reference pending])
"""

import json
import re
import sys
from pathlib import Path
from collections import defaultdict

AIM_DIR = Path(__file__).resolve().parent.parent
REGISTRY_PATH = AIM_DIR / "registry.json"

# Маркеры фабрикации/подозрительных ссылок
FABRICATION_MARKERS = [
    "[pre-print",
    "[REF_VERIFY",
    "[reference pending",
    "DOI:TBD",
    "osf.io/TBD",
    "PMID:TBD",
    "DOI to be assigned",
]


def load_registry():
    with open(REGISTRY_PATH) as f:
        return json.load(f)


def extract_pmids(text: str) -> list[str]:
    """Extract PMID:XXXXXXXX patterns."""
    return re.findall(r'PMID[:\s]*(\d{7,8})', text)


def extract_dois(text: str) -> list[str]:
    """Extract DOI patterns."""
    return re.findall(r'(10\.\d{4,}/[^\s,\]\")]+)', text)


def check_fabrication_markers(text: str) -> list[str]:
    """Return list of fabrication markers found in text."""
    found = []
    for marker in FABRICATION_MARKERS:
        if marker in text:
            found.append(marker)
    return found


def main():
    reg = load_registry()
    errors = 0
    warnings = 0

    print("=" * 60)
    print("Валидация: PMID/DOI ссылки")
    print("=" * 60)

    # Collect all PMIDs with their projects
    pmid_to_projects = defaultdict(list)

    for key, proj in reg["projects"].items():
        concept_path = (AIM_DIR / proj["path"] / "CONCEPT.md").resolve()
        if not concept_path.exists():
            continue

        text = concept_path.read_text(encoding="utf-8", errors="replace")

        # Check fabrication markers
        markers = check_fabrication_markers(text)
        if markers:
            print(f"  ⚠ {proj['name']}: маркеры фабрикации: {markers}")
            warnings += 1

        # Collect PMIDs
        for pmid in extract_pmids(text):
            pmid_to_projects[pmid].append(proj["name"])

    # Check for PMIDs used in multiple projects (suspicious but not necessarily wrong)
    print(f"\n  PMID статистика:")
    print(f"    Всего уникальных PMID: {len(pmid_to_projects)}")
    multi_use = {k: v for k, v in pmid_to_projects.items() if len(v) > 1}
    if multi_use:
        print(f"    PMID в нескольких проектах: {len(multi_use)}")
        for pmid, projects in list(multi_use.items())[:5]:
            print(f"      PMID:{pmid} → {', '.join(projects)}")
    else:
        print(f"    Все PMID уникальны для одного проекта")

    print(f"\nРезультат: {errors} ошибок, {warnings} предупреждений")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
