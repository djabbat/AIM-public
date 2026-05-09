# aim-mcp-lab-runner

Config helpers for hardware-experiment MCP runners.

AIM does NOT drive hardware directly — it sends structured tasks to an external worker (Claude Code in headless mode, a custom Rust binary, or anything that speaks the Model Context Protocol). This crate is the configuration layer: it generates / validates the TOML config that lives at `~/.aim/mcp/<name>.toml` for `agents/mcp_loader.py` to consume.

It deliberately does NOT implement the JSON-RPC client — that lives in `agents/mcp_loader.py` already. We just produce well-formed TOML.

## Default Claude-Code runner config

```rust
let cfg = LabRunnerConfig::claude_code_default(
 "E0",
 Path::new("/home/oem/Desktop/PhD/E0"),
);
let p = cfg.write_to_dir(&LabRunnerConfig::default_dir)?;
// → ~/.aim/mcp/E0.toml
```

Generates a TOML with:
- `[server]` — `claude --mcp-mode --project <path>`
- `[[tools]]` — `queue_imaging_run`, `request_calibration`, `fire_laser` (require_consent), `abort_run` (require_consent)

## Public API

- `LabRunnerConfig::claude_code_default(name, project_root)`
- `LabRunnerConfig::to_toml` / `write_to_dir(dir)`
- `LabRunnerConfig::default_dir` — `~/.aim/mcp/`

## Phase

B (HW1, 2026-05-06).
