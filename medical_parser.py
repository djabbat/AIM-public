#!/usr/bin/env python3
"""
Parser for patient case history folders.
Format: ~/Desktop/AIM/Patients/LastName_FirstName_YYYY_MM_DD/
Inside: text file (same name) with dated entries.
"""

import os
import re
from datetime import date, datetime
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional, Dict


from config import PATIENTS_DIR as DOCUMENTS_DIR, INBOX_DIR, get_logger

# Regex: YYYY_MM_DD or YYYYMM_DD_DD variants at start of line
DATE_PATTERN = re.compile(r'^\s*(\d{4})[_\-\./](\d{2})[_\-\./](\d{2})\s*$')
FOLDER_PATTERN = re.compile(r'^([A-Za-zА-Яа-яЁёა-ჿ]+)_([A-Za-zА-Яа-яЁёა-ჿ]+)_(\d{4})_(\d{2})_(\d{2})$')


@dataclass
class DateEntry:
    date: date
    text: str
    entry_type: str = "unknown"   # "history" | "prescription" | "mixed"
    prescriptions: List[str] = field(default_factory=list)
    history_notes: List[str] = field(default_factory=list)


@dataclass
class PatientRecord:
    last_name: str
    first_name: str
    opened_date: date
    folder_path: str
    entries: List[DateEntry] = field(default_factory=list)
    raw_text: str = ""

    @property
    def full_name(self) -> str:
        return f"{self.last_name} {self.first_name}"

    @property
    def patient_id(self) -> str:
        return f"{self.last_name}_{self.first_name}_{self.opened_date.strftime('%Y_%m_%d')}"


def _classify_entry(text: str) -> tuple[str, list, list]:
    """Classify entry as history/prescription/mixed, extract prescriptions."""
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    prescriptions = []
    history_notes = []

    # Numbered prescription lines start with digit + dot
    rx_pattern = re.compile(r'^\d+[.\)]\s+.+')

    for line in lines:
        if rx_pattern.match(line):
            prescriptions.append(line)
        else:
            history_notes.append(line)

    if prescriptions and not history_notes:
        entry_type = "prescription"
    elif history_notes and not prescriptions:
        entry_type = "history"
    else:
        entry_type = "mixed"

    return entry_type, prescriptions, history_notes


def parse_patient_file(file_path: str) -> List[DateEntry]:
    """Parse a patient text file into dated entries."""
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except Exception:
        return []

    entries = []
    current_date = None
    current_lines = []

    for line in content.splitlines():
        m = DATE_PATTERN.match(line)
        if m:
            # Save previous block
            if current_date and current_lines:
                text = "\n".join(current_lines).strip()
                if text:
                    etype, rxs, notes = _classify_entry(text)
                    entries.append(DateEntry(
                        date=current_date,
                        text=text,
                        entry_type=etype,
                        prescriptions=rxs,
                        history_notes=notes,
                    ))
            try:
                current_date = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                current_date = None
            current_lines = []
        else:
            current_lines.append(line)

    # Last block
    if current_date and current_lines:
        text = "\n".join(current_lines).strip()
        if text:
            etype, rxs, notes = _classify_entry(text)
            entries.append(DateEntry(
                date=current_date,
                text=text,
                entry_type=etype,
                prescriptions=rxs,
                history_notes=notes,
            ))

    entries.sort(key=lambda e: e.date)
    return entries


def load_all_patients(documents_dir: str = DOCUMENTS_DIR) -> List[PatientRecord]:
    """Scan ~/Desktop/AIM/Patients and load all patient records."""
    patients = []

    if not os.path.isdir(documents_dir):
        return patients

    for folder_name in sorted(os.listdir(documents_dir)):
        folder_path = os.path.join(documents_dir, folder_name)
        if not os.path.isdir(folder_path):
            continue

        m = FOLDER_PATTERN.match(folder_name)
        if not m:
            continue

        last_name = m.group(1)
        first_name = m.group(2)
        try:
            opened = date(int(m.group(3)), int(m.group(4)), int(m.group(5)))
        except ValueError:
            continue

        # Find the main text file (same name as folder, no extension)
        patient_file = os.path.join(folder_path, folder_name)
        entries = []
        raw_text = ""

        if os.path.isfile(patient_file):
            try:
                with open(patient_file, "r", encoding="utf-8", errors="replace") as f:
                    raw_text = f.read()
            except Exception:
                pass
            entries = parse_patient_file(patient_file)

        record = PatientRecord(
            last_name=last_name,
            first_name=first_name,
            opened_date=opened,
            folder_path=folder_path,
            entries=entries,
            raw_text=raw_text,
        )
        patients.append(record)

    return patients


if __name__ == "__main__":
    patients = load_all_patients()
    print(f"Loaded {len(patients)} patients:")
    for p in patients:
        print(f"\n  {p.full_name} (opened {p.opened_date})")
        for e in p.entries:
            print(f"    [{e.date}] type={e.entry_type}  "
                  f"rxs={len(e.prescriptions)}  notes={len(e.history_notes)}")
