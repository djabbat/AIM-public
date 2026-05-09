"""agents/project_state_machine.py — phase transitions (P5, 2026-05-02).

Each project YAML carries a `phase`. This module formalises the legal
transitions, suggests the next concrete actions for the current phase,
and logs every transition into a JSONL audit so we can replay the
project's life-cycle later.

The model targets the Tkemaladze workflow vocabulary (grants & papers):

    DRAFT       — initial conception / writing
    REVIEW      — internal peer review (FCLC v10-style)
    SUBMITTED   — awaiting external decision (eLife, Nature, EIC)
    ACCEPTED    — accepted but not yet public
    PUBLISHED   — public / DOI minted / funded
    REJECTED    — terminal failure; can fork into a new DRAFT
    ARCHIVED    — no longer active

Allowed graph:

    DRAFT     → REVIEW, SUBMITTED, ARCHIVED
    REVIEW    → DRAFT, SUBMITTED, ARCHIVED
    SUBMITTED → ACCEPTED, REJECTED, REVIEW (revisions), ARCHIVED
    ACCEPTED  → PUBLISHED, ARCHIVED
    PUBLISHED → ARCHIVED
    REJECTED  → DRAFT, ARCHIVED
    ARCHIVED  → (terminal)

Public API:
    PHASES                                 — frozenset of valid phase names
    is_legal(src, dst)                     -> bool
    next_actions(phase)                    -> list[str]   (advice for today)
    transition(project, dst, *, reason)    -> ProjectState   (writes YAML + audit)
    history(project)                       -> list[dict]
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
from pathlib import Path
from typing import Optional

log = logging.getLogger("aim.state_machine")

PHASES: frozenset[str] = frozenset({
    "DRAFT", "REVIEW", "SUBMITTED", "ACCEPTED",
    "PUBLISHED", "REJECTED", "ARCHIVED",
})

_TRANSITIONS: dict[str, frozenset[str]] = {
    "DRAFT":     frozenset({"REVIEW", "SUBMITTED", "ARCHIVED"}),
    "REVIEW":    frozenset({"DRAFT", "SUBMITTED", "ARCHIVED"}),
    "SUBMITTED": frozenset({"ACCEPTED", "REJECTED", "REVIEW", "ARCHIVED"}),
    "ACCEPTED":  frozenset({"PUBLISHED", "ARCHIVED"}),
    "PUBLISHED": frozenset({"ARCHIVED"}),
    "REJECTED":  frozenset({"DRAFT", "ARCHIVED"}),
    "ARCHIVED":  frozenset(),
}

# Per-phase advice. Surfaced in morning_brief() as "next phase action".
_PHASE_ACTIONS: dict[str, list[str]] = {
    "DRAFT": [
        "Lock the scope: which milestone makes this submittable?",
        "Identify the target venue / call (deadline, scope match)",
        "Draft the core outline before filling sections",
    ],
    "REVIEW": [
        "Run the peer-review rubric — note every blocker as a milestone",
        "Triage blockers into Fix / Defer / Cut",
        "Decide: back to DRAFT for revision, or push to SUBMITTED?",
    ],
    "SUBMITTED": [
        "Track expected decision date; set it as a stakeholder follow-up",
        "Prep response-to-reviewers template in advance",
        "Don't start downstream work that assumes acceptance",
    ],
    "ACCEPTED": [
        "Confirm DOI / contract terms in writing",
        "Schedule announcement (memory NEEDTOWRITE entry)",
        "Update STATE.md with acceptance date",
    ],
    "PUBLISHED": [
        "Add to publications list (memory: publications.md)",
        "Announce to stakeholders + Telegram + GLA news",
        "Move project to maintenance / new follow-up",
    ],
    "REJECTED": [
        "Capture reviewer feedback as DRAFT memory",
        "Decide within 7 days: re-target venue or shelve",
        "If re-target: open new DRAFT phase with the salvageable parts",
    ],
    "ARCHIVED": [
        "(no actions — project closed)",
    ],
}


def is_legal(src: str, dst: str) -> bool:
    src = src.upper()
    dst = dst.upper()
    if dst not in PHASES:
        return False
    return dst in _TRANSITIONS.get(src, frozenset())


def next_actions(phase: str) -> list[str]:
    return list(_PHASE_ACTIONS.get(phase.upper(), []))


# ── persistence ──────────────────────────────────────────────────


def _audit_path() -> Path:
    base = os.environ.get("AIM_HOME") or str(Path.home() / ".cache" / "aim")
    p = Path(base).expanduser() / "phase_history.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _audit_write(record: dict) -> None:
    try:
        with _audit_path().open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as e:
        log.warning("phase audit write failed: %s", e)


def history(project: Optional[str] = None) -> list[dict]:
    p = _audit_path()
    if not p.exists():
        return []
    out: list[dict] = []
    with p.open(encoding="utf-8") as f:
        for line in f:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if project and row.get("project") != project:
                continue
            out.append(row)
    return out


# ── transition ───────────────────────────────────────────────────


def transition(project: str, dst: str, *, reason: str = "",
               actor: str = "human") -> dict:
    """Move `project` to phase `dst`. Persists YAML + appends audit row.

    Raises ValueError if transition is illegal. Returns the audit record.
    """
    from agents import project_owner as po
    import yaml

    state = po.load(project)
    src = state.phase.upper()
    dst_u = dst.upper()
    if not is_legal(src, dst_u):
        legal = sorted(_TRANSITIONS.get(src, frozenset()))
        raise ValueError(
            f"illegal transition {src!r} → {dst_u!r}; legal moves: {legal}")

    yaml_path = po.projects_dir() / f"{project}.yaml"
    raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    raw["phase"] = dst_u
    yaml_path.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True),
                         encoding="utf-8")

    record = {
        "ts": dt.datetime.now().replace(microsecond=0).isoformat(),
        "project": state.name,
        "from": src,
        "to": dst_u,
        "reason": reason,
        "actor": actor,
    }
    _audit_write(record)
    return record


# ── brief integration helper ────────────────────────────────────


def phase_advisory(project: str) -> str:
    """One-liner + bulleted next-actions block for use inside morning_brief.

    Used by project_owner.morning_brief() when state.phase is set.
    """
    from agents import project_owner as po
    state = po.load(project)
    actions = next_actions(state.phase)
    if not actions:
        return f"phase: {state.phase} — no actions"
    out = [f"📐 phase {state.phase} — next actions:"]
    for a in actions:
        out.append(f"  • {a}")
    return "\n".join(out)


# ── CLI ──────────────────────────────────────────────────────────


def _main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Project phase machine")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("transition", help="move a project to a new phase")
    g.add_argument("project")
    g.add_argument("dst", choices=sorted(PHASES))
    g.add_argument("--reason", default="")
    g = sub.add_parser("actions", help="suggest next actions for a project")
    g.add_argument("project")
    g = sub.add_parser("history", help="show transition history")
    g.add_argument("project", nargs="?")
    args = ap.parse_args()
    if args.cmd == "transition":
        rec = transition(args.project, args.dst, reason=args.reason)
        print(json.dumps(rec, ensure_ascii=False))
    elif args.cmd == "actions":
        print(phase_advisory(args.project))
    elif args.cmd == "history":
        for r in history(args.project):
            print(json.dumps(r, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
