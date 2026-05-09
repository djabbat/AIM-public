# aim-patient-comms

Patient communication tracker — sister to `aim-stakeholder-tracker` (which serves Co-PI / external collaborators). This crate is for *patient*-side communications: WhatsApp, SMS, email, clinic visits.

Different schema and different privacy posture (PII redaction at egress; patient PII never mixed with Co-PI work emails).

## Schema

```
patient_messages — raw inbound/outbound message log
patient_followups — open follow-up items per (patient_id, topic)
```

## Storage

`$AIM_HOME/patient_comms.db` (defaults to `~/.cache/aim/patient_comms.db`). Bundled SQLite via `rusqlite` — no system dep.

## Public API

- `CommsStore::new(db_path)` / `from_env`
- `record_message(pid, channel, direction, body, ts)` — direction ∈ {in, out}
- `last_messages(pid, limit)` / `last_contact(pid)`
- `upsert_followup(pid, topic, expected_by?)` — idempotent
- `close_followup(pid, topic)`
- `list_followups(pid?)` — all if pid is None
- `overdue_followups(today)`

## CLI binary

```
aim-patient-comms list [<patient_id>]
aim-patient-comms overdue [<YYYY-MM-DD>]
aim-patient-comms add-followup <pid> <topic> [<YYYY-MM-DD>]
aim-patient-comms close-followup <pid> <topic>
aim-patient-comms record <pid> <channel> <in|out> <body...>
```

Used by Python `scripts/daily_brief.py` and `scripts/weekly_project_digest.py` via subprocess. Also surfaces overdue counts to `agents/pattern_miner.py:_mine_patient_followup_drift` for cross-system signals.

## Phase

D (HW1, 2026-05-06).
