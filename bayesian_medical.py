#!/usr/bin/env python3
"""
Bayesian structures for patient case histories.

For each patient: P(treatment | date, symptom_context)
Combined: aggregate CPTs across all patients.

Structure:
  BayesianNode: symptom/treatment category
  CPT: conditional probability table
  PatientBayesNet: per-patient network
  GlobalBayesNet: integrated network for all patients
"""

import re
import json
import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional
from datetime import date

from medical_parser import PatientRecord, DateEntry


# ─────────────────────────────────────────────
# Symptom / Treatment category keywords
# (Georgian + Russian/Latin)
# ─────────────────────────────────────────────
SYMPTOM_KEYWORDS: Dict[str, List[str]] = {
    "gastrointestinal": [
        "მუცელ", "საჭმ", "ღებინ", "გულ", "omepraz", "ომეპრაზ",
        "მაალ", "maalox", "პანკრ", "gastro", "gast", "ჭამ",
    ],
    "neurological_psychological": [
        "შფოთ", "დერეალ", "ტრავმ", "ანქსი", "panic",
        "5-htp", "ფენიბ", "phenibut", "სიზმარ", "ძილ", "depression",
        "stress", "სტრეს", "ემოც",
    ],
    "hormonal_gynecological": [
        "მენსტ", "menstr", "გინეკ", "gynec", "ჰორმ", "hormon",
        "ტემპ", "კლოტრ", "clotr", "ოვარ",
    ],
    "immunological_allergic": [
        "ალერგ", "allerg", "იმუნ", "immun", "ვობენზ", "wobenz",
        "ნისტ", "nystat",
    ],
    "antiparasitic_antimicrobial": [
        "მეტრ", "metron", "ამოქს", "amoxic", "მებენდ", "mebend",
        "ნისტ", "nystat", "antibiotic", "ანტიბ",
    ],
    "hepatobiliary": [
        "ღვიძ", "liver", "hepat", "ხოფიტ", "chofitol", "cholagog",
        "ბაბუაწვ", "bile",
    ],
    "renal_urinary": [
        "თირკმ", "renal", "urin", "კანეფ", "canefron", "kidney",
    ],
    "phytotherapy_herbal": [
        "ნაყენ", "ჩაი", "tea", "infus", "herb", "თავშავ",
        "ზაფრ", "სელ", "flaxseed", "plant",
    ],
    "trauma_surgical": [
        "ტრავმ", "trauma", "ოპერ", "oper", "საკეის", "caesarean",
        "სახსარ", "joint", "მუხლ",
    ],
    "cardiovascular": [
        "გულ", "cardiac", "cardio", "სისხლ", "pressure", "წნევ",
    ],
}

TREATMENT_KEYWORDS: Dict[str, List[str]] = {
    "proton_pump_inhibitors": ["omepraz", "ომეპრაზ", "pantopraz"],
    "antacids": ["maalox", "მაალ", "almagel", "antacid"],
    "herbal_GI": ["თავშავ", "ზაფრ", "სელ", "ბაბუ", "shepherd"],
    "enzymes": ["პანკრ", "mezim", "მეზ", "creon", "enzyme"],
    "antifungals": ["nystat", "ნისტ", "flucon", "clotrim", "კლოტრ"],
    "antibiotics": ["amoxic", "ამოქს", "metron", "მეტრ", "antibiotic"],
    "antiparasitics": ["mebend", "მებენდ", "albend"],
    "cholagogues": ["xofitol", "ხოფიტ", "chofitol", "კანეფ", "canefron"],
    "immunomodulators": ["wobenz", "ვობენზ", "transfer factor"],
    "neuro_supplements": ["5-htp", "phenibut", "ფენიბ", "magn", "b6"],
    "gynecological": ["gynec", "გინეკ", "clotr", "კლოტრ", "vaginal"],
    "phytotherapy": ["ნაყენ", "infusion", "ჩაი", "herbal"],
}


def _match_categories(text: str, keyword_map: Dict[str, List[str]]) -> List[str]:
    text_lower = text.lower()
    matched = []
    for category, keywords in keyword_map.items():
        if any(kw.lower() in text_lower for kw in keywords):
            matched.append(category)
    return matched


def extract_symptom_categories(entry: DateEntry) -> List[str]:
    return _match_categories(entry.text, SYMPTOM_KEYWORDS)


def extract_treatment_categories(entry: DateEntry) -> List[str]:
    rx_text = "\n".join(entry.prescriptions)
    return _match_categories(rx_text, TREATMENT_KEYWORDS)


# ─────────────────────────────────────────────
# Bayesian structures
# ─────────────────────────────────────────────

@dataclass
class CPTCell:
    """P(treatment_cat | symptom_cat) — count + probability."""
    count: int = 0
    probability: float = 0.0


class ConditionalProbabilityTable:
    """CPT: P(treatment | symptom)."""

    def __init__(self):
        # table[symptom_cat][treatment_cat] = CPTCell
        self.table: Dict[str, Dict[str, CPTCell]] = defaultdict(
            lambda: defaultdict(CPTCell)
        )
        self.symptom_counts: Dict[str, int] = defaultdict(int)

    def observe(self, symptom_cats: List[str], treatment_cats: List[str]):
        """Record one observation: given these symptoms, these treatments were prescribed."""
        for s in symptom_cats:
            self.symptom_counts[s] += 1
            for t in treatment_cats:
                self.table[s][t].count += 1

    def compute_probabilities(self, laplace_alpha: float = 0.5):
        """Compute P(t|s) = (count + alpha) / (total_for_s + alpha * num_treatments)."""
        all_treatments = set()
        for s_dict in self.table.values():
            all_treatments.update(s_dict.keys())
        n_treatments = max(len(all_treatments), 1)

        for s, t_dict in self.table.items():
            total = self.symptom_counts[s]
            for t, cell in t_dict.items():
                cell.probability = (cell.count + laplace_alpha) / (
                    total + laplace_alpha * n_treatments
                )

    def top_treatments(self, symptom_cat: str, n: int = 5) -> List[Tuple[str, float]]:
        """Return top-n treatments for a symptom category by probability."""
        self.compute_probabilities()
        t_dict = self.table.get(symptom_cat, {})
        ranked = sorted(t_dict.items(), key=lambda x: x[1].probability, reverse=True)
        return [(t, cell.probability) for t, cell in ranked[:n]]

    def to_dict(self) -> dict:
        self.compute_probabilities()
        result = {}
        for s, t_dict in self.table.items():
            result[s] = {
                t: {"count": cell.count, "p": round(cell.probability, 4)}
                for t, cell in sorted(t_dict.items(), key=lambda x: -x[1].count)
            }
        return result


@dataclass
class PatientBayesNet:
    """Per-patient Bayesian network."""
    patient_id: str
    full_name: str
    opened_date: date
    cpt: ConditionalProbabilityTable = field(default_factory=ConditionalProbabilityTable)

    # Timeline: list of (date, symptom_cats, treatment_cats)
    timeline: List[dict] = field(default_factory=list)

    # Symptom prior: P(symptom_cat) for this patient
    symptom_prior: Dict[str, float] = field(default_factory=dict)

    def build(self, record: PatientRecord):
        """Build the Bayesian structure from a patient record."""
        symptom_total = defaultdict(int)
        total_entries = 0

        # Group entries: history entries provide symptom context for nearby prescriptions
        history_entries = [e for e in record.entries if e.entry_type in ("history", "mixed")]
        rx_entries = [e for e in record.entries if e.entry_type in ("prescription", "mixed")]

        # Extract symptom context from ALL history entries combined (per patient)
        all_symptoms = []
        for h in history_entries:
            cats = extract_symptom_categories(h)
            all_symptoms.extend(cats)
            for c in cats:
                symptom_total[c] += 1

        # For each prescription entry, pair with symptom context
        for rx in rx_entries:
            treatments = extract_treatment_categories(rx)
            if not treatments:
                continue

            # Also check if prescription entry itself hints at symptoms
            rx_symptoms = extract_symptom_categories(rx)
            combined_symptoms = list(set(all_symptoms + rx_symptoms)) or ["unknown"]

            self.cpt.observe(combined_symptoms, treatments)
            self.timeline.append({
                "date": rx.date.isoformat(),
                "symptoms": combined_symptoms,
                "treatments": treatments,
            })
            total_entries += 1

        # Symptom prior P(symptom)
        total_s = sum(symptom_total.values()) or 1
        self.symptom_prior = {s: c / total_s for s, c in symptom_total.items()}

        self.cpt.compute_probabilities()

    def to_dict(self) -> dict:
        return {
            "patient_id": self.patient_id,
            "full_name": self.full_name,
            "opened_date": self.opened_date.isoformat(),
            "symptom_prior": {k: round(v, 4) for k, v in self.symptom_prior.items()},
            "cpt": self.cpt.to_dict(),
            "timeline": self.timeline,
        }

    def summary(self) -> str:
        lines = [f"Пациент: {self.full_name} (открыта {self.opened_date})"]
        if self.symptom_prior:
            lines.append("  Симптомы (prior):")
            for s, p in sorted(self.symptom_prior.items(), key=lambda x: -x[1]):
                lines.append(f"    {s}: {p:.2%}")
        if self.timeline:
            lines.append(f"  Записей в байесовской структуре: {len(self.timeline)}")
        return "\n".join(lines)


class GlobalBayesNet:
    """Integrated Bayesian network across all patients."""

    def __init__(self):
        self.cpt = ConditionalProbabilityTable()
        self.patient_nets: List[PatientBayesNet] = []
        self.symptom_prevalence: Dict[str, float] = defaultdict(float)
        self.n_patients: int = 0

    def integrate(self, patient_nets: List[PatientBayesNet]):
        """Merge all patient CPTs into global structure."""
        self.patient_nets = patient_nets
        self.n_patients = len(patient_nets)

        symptom_counts: Dict[str, int] = defaultdict(int)

        for pnet in patient_nets:
            # Merge CPT observations
            for s, t_dict in pnet.cpt.table.items():
                for t, cell in t_dict.items():
                    self.cpt.table[s][t].count += cell.count
                self.cpt.symptom_counts[s] += pnet.cpt.symptom_counts.get(s, 0)

            # Symptom prevalence across patients
            for s in pnet.symptom_prior:
                symptom_counts[s] += 1

        # P(symptom_cat appears in a patient)
        for s, cnt in symptom_counts.items():
            self.symptom_prevalence[s] = cnt / max(self.n_patients, 1)

        self.cpt.compute_probabilities()

    def to_dict(self) -> dict:
        return {
            "n_patients": self.n_patients,
            "symptom_prevalence": {
                k: round(v, 4)
                for k, v in sorted(
                    self.symptom_prevalence.items(), key=lambda x: -x[1]
                )
            },
            "cpt": self.cpt.to_dict(),
        }

    def summary(self) -> str:
        lines = [
            f"=== ГЛОБАЛЬНАЯ БАЙЕСОВСКАЯ СЕТЬ ({self.n_patients} пациентов) ===",
            "Частота симптомов по пациентам:",
        ]
        for s, p in sorted(self.symptom_prevalence.items(), key=lambda x: -x[1]):
            lines.append(f"  {s}: {p:.0%} пациентов")

        lines.append("\nТоп-3 лечения для каждого симптома:")
        for s in sorted(self.cpt.table.keys()):
            top = self.cpt.top_treatments(s, n=3)
            if top:
                top_str = ", ".join(f"{t}({p:.0%})" for t, p in top)
                lines.append(f"  [{s}] → {top_str}")

        return "\n".join(lines)


def build_all(documents_dir: str = None) -> Tuple[List[PatientBayesNet], GlobalBayesNet]:
    """Build per-patient and global Bayesian networks from ~/AIM/Patients/."""
    from medical_parser import load_all_patients, DOCUMENTS_DIR
    patients = load_all_patients(documents_dir or DOCUMENTS_DIR)

    patient_nets = []
    for record in patients:
        pnet = PatientBayesNet(
            patient_id=record.patient_id,
            full_name=record.full_name,
            opened_date=record.opened_date,
        )
        pnet.build(record)
        patient_nets.append(pnet)

    global_net = GlobalBayesNet()
    global_net.integrate(patient_nets)

    return patient_nets, global_net


if __name__ == "__main__":
    patient_nets, global_net = build_all()

    for pnet in patient_nets:
        print(pnet.summary())
        print()

    print(global_net.summary())

    # Save JSON
    import json
    import os
    output = {
        "patients": [p.to_dict() for p in patient_nets],
        "global": global_net.to_dict(),
    }
    out_path = os.path.expanduser("~/AIM/medical_bayes.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\nСохранено: {out_path}")
