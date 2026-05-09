# aim-journal-watcher

NDJSON experiment journal poller. Workers (Claude Code in `/overnight` mode driving the microscope) append events to `~/.cache/aim/microscopy/sessions/<run_id>.ndjson` — one JSON object per line. This crate scans those files and computes uptime / decisions-per-hour / contamination counters that `aim-experiment-owner` uses for KPI tracking.

Pure-stdlib polling — no inotify dependency. Designed for `serve_daemon` tick (every minute). Files are append-only so re-reading is cheap.

## Expected event shape

```json
{"ts":"2026-05-06T22:14:00Z","kind":"decision","detail":"adjust_focus","outcome":"ok"}
{"ts":"2026-05-06T22:15:00Z","kind":"observation","detail":"contamination_suspected"}
{"ts":"2026-05-06T22:16:00Z","kind":"alert","detail":"interlock_tripped"}
```

Loose parsing — unknown fields ignored, malformed lines skipped.

## Public API

- `Event` struct + `Stats` aggregator (n_events, n_decisions, n_alerts, n_contaminations, first/last timestamps)
- `Stats::span_hours` / `Stats::decisions_per_hour`
- `scan(root, older_than_hours?) -> Result<Stats>` — walk all `.ndjson` under `root`
- `default_journal_root` — `$AIM_HOME/microscopy/sessions/` or `~/.cache/aim/microscopy/sessions/`

## Phase

B (HW1, 2026-05-06).
