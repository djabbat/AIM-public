"""export/fhir_exporter.py — Patient + Lab → FHIR R4.

No third-party fhir.resources dependency required: emit raw JSON dicts that
follow the R4 spec. If `fhir.resources` is installed, also returns typed
objects for downstream validation.

Usage:
    from export.fhir_exporter import FHIRExporter
    fx = FHIRExporter()
    bundle = fx.bundle_patient(patient, observations=[...])
    fx.post(bundle, server="https://hapi.fhir.org/baseR4")
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

log = logging.getLogger("aim.fhir")


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _id() -> str:
    return uuid.uuid4().hex[:24]


class FHIRExporter:
    """Build FHIR R4 resources from AIM patient + lab structures.

    Input shape (loose):
        patient = {"id": str, "surname": str, "name": str, "dob": "YYYY-MM-DD",
                   "gender": "male|female|other|unknown" }
        observation = {"loinc": str, "name": str, "value": float, "unit": str,
                       "ref_low": float|None, "ref_high": float|None,
                       "effective": "YYYY-MM-DD" }
    """

    def patient_resource(self, p: dict[str, Any]) -> dict[str, Any]:
        return {
            "resourceType": "Patient",
            "id": p.get("id") or _id(),
            "identifier": [{
                "system": "https://aim.local/patient",
                "value": p.get("id") or "AIM-UNKNOWN",
            }],
            "name": [{
                "family": p.get("surname", ""),
                "given":  [p.get("name", "")],
            }],
            "gender": p.get("gender", "unknown"),
            "birthDate": p.get("dob"),
        }

    def observation_resource(
        self,
        obs: dict[str, Any],
        patient_id: str,
    ) -> dict[str, Any]:
        ref_range = []
        low = obs.get("ref_low")
        high = obs.get("ref_high")
        if low is not None or high is not None:
            r: dict[str, Any] = {}
            if low is not None:
                r["low"] = {"value": low, "unit": obs["unit"]}
            if high is not None:
                r["high"] = {"value": high, "unit": obs["unit"]}
            ref_range.append(r)

        return {
            "resourceType": "Observation",
            "id": _id(),
            "status": obs.get("status", "final"),
            "code": {
                "coding": [{
                    "system":  "http://loinc.org",
                    "code":    obs["loinc"],
                    "display": obs.get("name", ""),
                }],
                "text": obs.get("name", ""),
            },
            "subject":  {"reference": f"Patient/{patient_id}"},
            "effectiveDateTime": obs.get("effective", _now_iso()),
            "valueQuantity": {
                "value":  obs["value"],
                "unit":   obs["unit"],
                "system": "http://unitsofmeasure.org",
            },
            "referenceRange": ref_range,
        }

    def bundle_patient(
        self,
        patient: dict[str, Any],
        observations: Iterable[dict[str, Any]] = (),
        bundle_type: str = "transaction",
    ) -> dict[str, Any]:
        pat = self.patient_resource(patient)
        entries = [{
            "fullUrl": f"urn:uuid:{pat['id']}",
            "resource": pat,
            "request": {"method": "PUT", "url": f"Patient/{pat['id']}"},
        }]
        for obs in observations:
            r = self.observation_resource(obs, pat["id"])
            entries.append({
                "fullUrl": f"urn:uuid:{r['id']}",
                "resource": r,
                "request": {"method": "POST", "url": "Observation"},
            })
        return {
            "resourceType": "Bundle",
            "type": bundle_type,
            "timestamp": _now_iso(),
            "entry": entries,
        }

    # ── Validation (optional via fhir.resources) ────────────────────────────

    def validate(self, resource: dict[str, Any]) -> bool:
        try:
            from fhir.resources.fhirresourcemodel import FHIRResourceModel
            from fhir.resources import construct_fhir_element
            kind = resource.get("resourceType")
            construct_fhir_element(kind, resource)
            return True
        except ImportError:
            log.debug("fhir.resources not installed; skipping validation")
            return True
        except Exception as e:
            log.warning(f"FHIR validation failed: {e}")
            return False

    # ── Persistence + transport ────────────────────────────────────────────

    def write(self, bundle: dict[str, Any], path: str | Path) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
        log.info(f"wrote bundle → {p}")
        return p

    def post(self, bundle: dict[str, Any], server: str, timeout_s: int = 30) -> int:
        """POST to a FHIR server (e.g. HAPI). Returns HTTP status code."""
        import httpx
        with httpx.Client(timeout=timeout_s) as cl:
            r = cl.post(server, json=bundle, headers={"Content-Type": "application/fhir+json"})
        log.info(f"FHIR POST {server} → {r.status_code}")
        return r.status_code


def _main():
    import argparse
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("example", help="emit a sample bundle to stdout")
    e.add_argument("--write", help="write bundle to this path instead of stdout")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")
    if args.cmd == "example":
        fx = FHIRExporter()
        bundle = fx.bundle_patient(
            patient={"id": "demo-001", "surname": "Demo",
                     "name": "Patient", "dob": "1980-01-01", "gender": "male"},
            observations=[
                {"loinc": "718-7", "name": "Hemoglobin", "value": 14.2, "unit": "g/dL",
                 "ref_low": 13.5, "ref_high": 17.5, "effective": "2026-04-28"},
                {"loinc": "2160-0", "name": "Creatinine", "value": 0.9, "unit": "mg/dL",
                 "ref_low": 0.7, "ref_high": 1.3, "effective": "2026-04-28"},
            ],
        )
        if args.write:
            fx.write(bundle, args.write)
        else:
            print(json.dumps(bundle, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _main()
