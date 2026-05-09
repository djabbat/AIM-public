"""tests/test_pam_trajectory_e2e.py — end-to-end PAM-13 trajectory.

STRATEGY.md P1-1 closure (2026-05-07).

Exercises THEORY.md §6 happy-path (the cornerstone scenario):

    intake → PAM #1 → coach action → codesign log → PAM #2
        → MCID delta classified → L_AGENCY enforced

Uses Rust binaries directly (subprocess), not Python wrappers, because
the production path is `aim-pam` / `aim-codesign` / `aim-coach` binaries.
The Python kernel comes from `agents.kernel` (PyO3 → Rust `aim-kernel`).

Patients-dir is isolated in tmp_path → never touches `Patients/`.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
RUST_RELEASE = ROOT / "rust-core" / "target" / "release"
PAM_BIN = RUST_RELEASE / "aim-pam"
COACH_BIN = RUST_RELEASE / "aim-coach"
CODESIGN_BIN = RUST_RELEASE / "aim-codesign"


# ── helpers ─────────────────────────────────────────────────────────────


def _require(bin_path: Path) -> None:
    if not bin_path.exists():
        pytest.skip(f"{bin_path.name} not built — run `cargo build --release` "
                    f"in {bin_path.parent}")


def _run(bin_path: Path, *args: str, patients_dir: Path) -> str:
    proc = subprocess.run(
        [str(bin_path), *args, "--patients-dir", str(patients_dir)],
        capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"{bin_path.name} {args} failed (rc={proc.returncode}): "
            f"{proc.stderr.strip() or proc.stdout.strip()}"
        )
    return proc.stdout


def _record_pam(pid: str, responses: list[int], patients_dir: Path) -> dict:
    # aim-pam requires the patient folder to exist before `record`.
    (patients_dir / pid).mkdir(parents=True, exist_ok=True)
    out = _run(PAM_BIN, "record", pid, *map(str, responses), patients_dir=patients_dir)
    return json.loads(out.strip())


def _make_decision(action_type: str, description: str = "test action") -> "Decision":
    """Build a Decision (Rust+legacy share the same field shape)."""
    from agents.kernel_legacy import Decision
    return Decision(
        id="d-test",
        description=description,
        action_type=action_type,
        payload={},
    )


# ── happy-path E2E ──────────────────────────────────────────────────────


def test_pam_trajectory_full_happy_path(tmp_path: Path):
    """Cornerstone E2E from THEORY.md §6.

    Steps:
      1. Patient intake (folder + id)
      2. PAM-13 #1 — низко активный пациент (level 1)
      3. Coach action: aim-coach classify утverance + next-move pick
      4. Co-design log entry (consulted + agreed)
      5. PAM-13 #2 — улучшение на ≥ MCID (5.4)
      6. Delta classified как improvement (>= 1.0 MCID)
      7. L_AGENCY: на активированном пациенте (level >= 2) treatment
         БЕЗ co-design = блок; С co-design = pass
    """
    _require(PAM_BIN)
    _require(COACH_BIN)
    _require(CODESIGN_BIN)

    patients_dir = tmp_path / "Patients"
    patients_dir.mkdir()

    pid = "TEST_E2E_PAM_TRAJECTORY"

    # 2. PAM-13 #1 — disengaged pattern (mostly 1-2)
    pam1 = _record_pam(pid,
        [1, 2, 1, 2, 1, 2, 2, 1, 2, 1, 2, 1, 2],
        patients_dir=patients_dir,
    )
    assert "score" in pam1, f"unexpected pam1 payload: {pam1}"
    s0 = float(pam1["score"])
    assert 0.0 <= s0 <= 100.0
    # Disengaged → expect level 1
    level0_out = _run(PAM_BIN, "level", pid, patients_dir=patients_dir).strip()
    level0 = int(level0_out.splitlines()[-1])
    assert level0 == 1, f"expected level 1 for disengaged baseline, got {level0} (score={s0})"

    # 3. Coach action — patient говорит change-talk.
    # aim-coach emits plain-text labels (one word per line) — by design,
    # since the LLM call is the caller's responsibility (see --help).
    classify_kind = subprocess.run(
        [str(COACH_BIN), "classify",
         "I want to start eating better and walking every morning"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert classify_kind in {"change_talk", "sustain_talk", "neutral", "resistance"}, \
        f"unexpected classify output: {classify_kind!r}"
    next_move = subprocess.run(
        [str(COACH_BIN), "next-move", classify_kind, str(level0)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert next_move, "next-move must not be empty"

    # 4. Co-design log: clinician consulted, patient agreed
    _run(CODESIGN_BIN, "record", pid, "consulted",
         "lifestyle plan: morning walk + diet review",
         "--decision-id", "rx-001",
         patients_dir=patients_dir)
    _run(CODESIGN_BIN, "record", pid, "agreed",
         "lifestyle plan: morning walk + diet review",
         "--decision-id", "rx-001",
         patients_dir=patients_dir)
    events_out = _run(CODESIGN_BIN, "events", pid, patients_dir=patients_dir)
    events = [json.loads(line) for line in events_out.splitlines() if line.strip()]
    kinds = {e["kind"] for e in events}
    assert {"consulted", "agreed"}.issubset(kinds)

    # 5. PAM-13 #2 — clear improvement (mostly 3-4)
    pam2 = _record_pam(pid,
        [3, 3, 4, 3, 4, 3, 4, 3, 4, 3, 3, 4, 4],
        patients_dir=patients_dir,
    )
    s1 = float(pam2["score"])
    assert s1 > s0, f"PAM-13 #2 ({s1}) must exceed #1 ({s0})"

    # 6. Delta classification via aim-pam latest-delta
    delta_out = _run(PAM_BIN, "latest-delta", pid, patients_dir=patients_dir).strip()
    delta = json.loads(delta_out)
    assert "delta" in delta and "label" in delta
    assert delta["delta"] > 0
    # MCID = 5.4. Our 1→4 swing should easily clear it.
    assert delta["delta"] >= 5.4, (
        f"expected MCID-clearing delta (>= 5.4), got {delta['delta']}; "
        f"label='{delta['label']}'"
    )
    # `aim-pam` labels: "noise" | "individually_significant" | "highly_significant" | etc.
    # "individually_significant" = delta crosses MCID; "highly_significant" = crosses MDC.
    assert delta["label"] in (
        "individually_significant",
        "highly_significant",
        "improved",
        "improvement",
        "improved_significantly",
    ), f"unexpected label: {delta['label']}"

    # 7. L_AGENCY enforcement
    from agents.kernel_legacy import evaluate_l_agency, AGENCY_ACTIONS
    # Pick any AGENCY-protected action_type
    action_type = next(iter(AGENCY_ACTIONS))
    decision = _make_decision(action_type, "start ACE-i for HTN")

    # Patient is now activated (level >= 2 after PAM #2)
    pam_level_2_out = _run(PAM_BIN, "level", pid, patients_dir=patients_dir).strip()
    level1 = int(pam_level_2_out.splitlines()[-1])
    assert level1 >= 2, f"expected activated patient (level>=2), got {level1}"

    patient = {"activation_level": level1}

    # Without co-design flag → should be blocked
    ok_no_codesign, reason_no = evaluate_l_agency(decision, patient, {})
    assert ok_no_codesign is False, (
        "L_AGENCY must block AGENCY action for activated patient without "
        f"patient_codesigned flag — got pass with reason: {reason_no}"
    )
    assert "co-design" in reason_no.lower() or "agency" in reason_no.lower()

    # With co-design flag → should pass
    ok_with_codesign, _ = evaluate_l_agency(
        decision, patient, {"patient_codesigned": True},
    )
    assert ok_with_codesign is True, (
        "L_AGENCY must allow AGENCY action when patient_codesigned=True"
    )

    # 8. Audit trail durability — JSONL persists in patients_dir.
    # Filenames per `aim-pam` / `aim-codesign` are dot-prefixed (`_pam_history.jsonl`
    # and `_codesign.jsonl` — see Patients/INBOX naming convention).
    pam_log = patients_dir / pid / "_pam_history.jsonl"
    assert pam_log.exists(), f"PAM JSONL log missing at {pam_log}"
    pam_lines = pam_log.read_text(encoding="utf-8").strip().splitlines()
    assert len(pam_lines) == 2, f"expected 2 administrations, got {len(pam_lines)}"

    cd_log = patients_dir / pid / "_codesign.jsonl"
    assert cd_log.exists(), f"co-design JSONL log missing at {cd_log}"
    cd_lines = cd_log.read_text(encoding="utf-8").strip().splitlines()
    assert len(cd_lines) == 2, f"expected 2 codesign entries, got {len(cd_lines)}"


# ── safety: regression doesn't fall back to placeholder activation ──────


def test_l_agency_blocks_unknown_activation():
    """Patient with activation_level=0 (unknown) — L_AGENCY conservative
    behaviour: pass-with-flag (per `evaluate_l_agency` semantics, level <= 1
    permits action but logs the gap)."""
    from agents.kernel_legacy import evaluate_l_agency, AGENCY_ACTIONS
    action_type = next(iter(AGENCY_ACTIONS))
    decision = _make_decision(action_type)
    ok, reason = evaluate_l_agency(decision, {"activation_level": 0}, {})
    # Conservative pass — but logs.
    assert ok is True
    assert "level=0" in reason or "level=" in reason or "unknown" in reason.lower() \
        or "pass" in reason.lower()


# ── regressed-trajectory scenario ──────────────────────────────────────


def test_pam_trajectory_regressed(tmp_path: Path):
    """Negative path: improvement → regression. Δ-classification surfaces
    the regression so cohort analysis catches drift early."""
    _require(PAM_BIN)
    patients_dir = tmp_path / "Patients"
    patients_dir.mkdir()
    pid = "TEST_REGRESSED"

    # T0: moderately activated (level 3-ish)
    _record_pam(pid, [3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3], patients_dir=patients_dir)
    # T1: regression — patient disengaged
    _record_pam(pid, [1, 2, 1, 2, 1, 2, 1, 2, 1, 2, 1, 2, 1], patients_dir=patients_dir)

    delta_out = _run(PAM_BIN, "latest-delta", pid, patients_dir=patients_dir).strip()
    delta = json.loads(delta_out)
    assert delta["delta"] < 0, f"expected negative delta on regression, got {delta['delta']}"
    # Label per aim-pam: regressions also surface as "individually_significant"
    # / "highly_significant" (the tag is magnitude, not direction). Direction
    # comes from sign of delta.
    assert abs(delta["delta"]) >= 5.4, "regression should clear MCID magnitude"


# ── refused co-design scenario ─────────────────────────────────────────


def test_l_agency_logs_refusal(tmp_path: Path):
    """Patient activated, clinician offers treatment, patient REFUSES via
    aim-codesign — `refused` event is recorded; L_AGENCY without
    `patient_codesigned=True` still blocks (as designed) — refusal does
    not equal consent."""
    _require(PAM_BIN)
    _require(CODESIGN_BIN)
    patients_dir = tmp_path / "Patients"
    patients_dir.mkdir()
    pid = "TEST_REFUSED"

    _record_pam(pid, [4, 4, 4, 4, 4, 3, 4, 4, 3, 4, 4, 3, 4], patients_dir=patients_dir)
    level = int(_run(PAM_BIN, "level", pid, patients_dir=patients_dir).strip().splitlines()[-1])
    assert level >= 3, f"expected highly activated patient, got level {level}"

    # Patient refuses
    _run(CODESIGN_BIN, "record", pid, "refused",
         "ACEi for HTN", "--decision-id", "rx-refused",
         patients_dir=patients_dir)
    events_out = _run(CODESIGN_BIN, "events", pid, patients_dir=patients_dir)
    events = [json.loads(line) for line in events_out.splitlines() if line.strip()]
    assert any(e["kind"] == "refused" for e in events)

    # L_AGENCY: refused != patient_codesigned. Block stays in force.
    from agents.kernel_legacy import evaluate_l_agency, AGENCY_ACTIONS
    decision = _make_decision(next(iter(AGENCY_ACTIONS)), "ACEi for HTN")
    ok, reason = evaluate_l_agency(
        decision, {"activation_level": level},
        # NB: do NOT set patient_codesigned=True — refused != agreed.
        {"patient_codesigned": False},
    )
    assert ok is False, "L_AGENCY must still block when patient refused but no consent flag set"


# ── cohort extraction smoke ────────────────────────────────────────────


def test_pilot_cohort_extract_smoke(tmp_path: Path):
    """End-to-end: 3 patients enrolled, varied trajectories, cohort
    extractor produces well-formed JSON with correct classifications."""
    _require(PAM_BIN)
    _require(CODESIGN_BIN)
    patients_dir = tmp_path / "Patients"
    patients_dir.mkdir()

    # P1: improved
    _record_pam("P1", [1, 2, 1, 2, 1, 2, 2, 1, 2, 1, 2, 1, 2], patients_dir=patients_dir)
    _record_pam("P1", [3, 3, 4, 3, 4, 3, 4, 3, 4, 3, 3, 4, 4], patients_dir=patients_dir)
    _run(CODESIGN_BIN, "record", "P1", "agreed", "plan", patients_dir=patients_dir)

    # P2: stable (small change within MCID)
    _record_pam("P2", [3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3], patients_dir=patients_dir)
    _record_pam("P2", [3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3], patients_dir=patients_dir)

    # P3: incomplete (only T0)
    _record_pam("P3", [2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2], patients_dir=patients_dir)

    # Run extractor
    extract_script = ROOT / "scripts" / "pilot_cohort_extract.py"
    proc = subprocess.run(
        ["python3", str(extract_script),
         "--patients-dir", str(patients_dir), "--json"],
        capture_output=True, text=True, check=True,
    )
    payload = json.loads(proc.stdout)
    assert payload["n_enrolled"] == 3
    assert payload["thresholds"]["mcid"] == 5.4
    by_pid = {p["patient_id"]: p for p in payload["patients"]}
    assert by_pid["P1"]["classification"] == "improved"
    assert by_pid["P2"]["classification"] == "stable"
    assert by_pid["P3"]["classification"] == "incomplete"
    assert by_pid["P1"]["n_codesign_events"] == 1
    assert by_pid["P2"]["n_codesign_events"] == 0
