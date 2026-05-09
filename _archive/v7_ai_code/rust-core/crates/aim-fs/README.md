# aim-fs — three-tier filesystem layer for AIM

Rust crate + CLI Port + onboarding bridge for the AIM agent.

Implements **AIM_FS Spec v11** (ACCEPT'ed via 11 cycles of DeepSeek
peer-review — see `~/Desktop/LongevityCommon/AIM/docs/AIM_FS/SPEC.md`).

## Three tiers

```
<aim_root>/
├── users/<user_id>/ # Tier 1: AIM-curated user profile
│ ├── profile/ # identity, role, prefs, history
│ │ ├── identity.yaml # immutable; mutate via guarded proposal
│ │ ├── role.md
│ │ ├── preferences.md
│ │ ├── facts/<fact_id>.md
│ │ └── feedback/<fb_id>.md
│ │
│ ├── projects/<slug>/ # Tier 2: user-defined projects
│ │ ├── CONCEPT.md THEORY.md PARAMETERS.md
│ │ ├── KNOWLEDGE.md README.md STATE.md
│ │ ├── TODO.md UPGRADE.md MAP.md
│ │ ├── CLAUDE.md EVIDENCE.md
│ │ └── _meta/{links,events}.jsonl
│ │
│ └── patients/<surname>_<name>_<dob>/ # Tier 3.a
│ ├── identity.toml # immutable PII
│ ├── ANAMNESIS.md
│ ├── consent.json
│ ├── visits/<ts>/
│ ├── recipes/<id>.md
│ └── _inbox/ # AI-proposed diagnoses/recipes
│
├── _service/ # Tier 3.b
│ ├── db/aim_fs.db # SQLite WAL — single source of metadata
│ ├── inbox/ # Phoenix InboxLive reads from here
│ ├── disputes/ # conflict resolution (SPEC §8)
│ ├── tmp/ # atomic-write staging
│ └── backup/
│
└── _self_dev/ # Tier 3.c — AIM proposes upgrades to itself
 ├── CONCEPT.md INVARIANTS.md UPGRADE.md
 └── proposals/{pending,approved,rejected}/<id>.md
```

## Public Rust API

```rust
use aim_fs::{AimFs, ApprovalPolicy, NewEntity, Source, LinkType, InitialLink};
use aim_fs::search::SearchScope;

let fs = AimFs::open("/var/lib/aim_fs")?;

// Tier 2: scaffold a user-defined project (11-file core).
let project_dir = fs.scaffold_project("user-uuid", "demo", "# Demo project\n\n…")?;

// Tier 3.a: register a new patient.
let dir = fs.ensure_patient("doctor-uuid", "Beridze_Keti_2026_03_12")?;

// Propose / approve / reject (Approval queue — SPEC §4).
let policy = ApprovalPolicy { /* ... */ };
let outcome = fs.propose("user-uuid", new_entity, Some("rationale"), None, &policy)?;
fs.approve_proposal("user-uuid", &outcome.proposal_id, &actor)?;

// Graph (SPEC §6).
fs.add_link("user-uuid", &src, &tgt, LinkType::Refines)?;

// Hybrid search (SPEC §5.2 — MVP: SQL LIKE; FTS5 in Phase 2).
let hits = fs.search("user-uuid", "DeepSeek", &SearchScope::default, 10)?;

// Decay sweeper (called by systemd timer or background tokio task).
let n = aim_fs::sweeper::sweep_once(&fs.pool)?;
```

## Crate features

| Module | Status | What |
|---|---|---|
| `entity` | ✅ | CRUD with optimistic locking |
| `proposal` | ✅ | propose/approve/reject + auto-approve policy + idempotency |
| `events` | ✅ | append-only event log (atomic with each tx) |
| `links` | ✅ | depends_on/refines/supersedes/contradicts (graph) |
| `schemas` | ✅ | per-type validation (feedback/proposal/recipe/...) |
| `search` | ✅ | SQL LIKE search (Phase 2: FTS5 + embeddings) |
| `sweeper` | ✅ | Tokio decay sweeper, 60-s tick |
| `db` | ✅ | SQLite WAL with `BEGIN IMMEDIATE` + r2d2 pool |
| (CAS layer) | ⏳ | Phase 2 |
| (encryption) | ⏳ | Phase B (multi-tenant) |

**18/18 unit tests pass.**

## Binaries

| Binary | Role |
|---|---|
| `aim-fs` | JSON Port (one cmd per stdin line, one reply per stdout line). Consumed by Phoenix `AimMemory.FS.Port`. Ops: `ping`, `propose`, `approve`, `reject`, `list_pending`, `scaffold_project`, `ensure_patient`, `sweep`, `search`, `add_link`, `list_outgoing`. |
| `aim-fs-migrate` | Legacy → AIM_FS importer. See `--help`. |
| `aim-fs-sweep-once`| Wrapper for systemd timer that runs one decay sweep. |

```
$ printf '{"op":"ping"}\n' | aim-fs
{"ok":true,"result":{"pong":true}}

$ aim-fs-migrate --aim-root ~/.aim_fs \
 --tenant-id $(uuidgen) \
 --claude-memory ~/.claude/projects/<proj>/memory \
 --legacy-aim ~/Desktop/LongevityCommon/AIM
```

## Approval policy

```rust
ApprovalPolicy {
 auto_approve_user_commands: true,
 auto_approve_observational_with_confidence_above: 0.95,
 auto_approve_service_events: true,
 require_approval_for: vec!["feedback", "proposal", "recipe", "diagnosis"],
 max_inactivity_days: 30,
}
```

Anything in `require_approval_for` skips auto-approve and lands in the
inbox (UI: `AimWebWeb.InboxLive`, route `/inbox`).

## Schemas

Validators currently check structural rules — body sections, required tags,
patient scope. See `schemas.rs`. Migration to `_schemas/<name>.json` JSON
Schema files is Phase 2.

| schema id | required structure |
|---|---|
| `feedback_v1` | non-empty title, ≥1 tag, body contains `Why:` and `How to apply:` |
| `proposal_v1` | body has `## Что предлагаю`, `## Доказательства`, `## Риски` |
| `patient_anamnesis_v1`| `scope.patient_ids` non-empty |
| `recipe_v1` | `scope.patient_ids` non-empty |
| `contact_v1` | tag `contact` |
| `imported_md_v1` | pass-through (used by `aim-fs-migrate`) |

## Deployment

`deploy/install.sh` builds in release, copies binaries to `/usr/local/bin`,
templates to `/opt/aim/templates`, and enables a `systemd --user`
timer that runs the sweeper every 60 s.

```
$ bash deploy/install.sh
…
✓ aim-fs-sweeper.timer enabled
```

No Docker, no daemonised network service: per the AIM `feedback_no_docker`
rule, deployment is native systemd. Phoenix owns the Port lifecycle directly.

## Phoenix integration

```elixir
# config/config.exs
config :aim_memory, AimMemory.FS.Port,
 binary: System.get_env("AIM_FS_BIN") || "aim-fs",
 root: System.get_env("AIM_FS_ROOT") || Path.expand("~/.aim_fs")

# AimMemory.FS context wraps the Port.
{:ok, outcome} = AimMemory.FS.propose("u", new_entity, rationale: "…")
{:ok, _} = AimMemory.FS.approve("u", outcome["proposal_id"], actor)
```

LiveView surfaces:

- `/inbox` — `AimWebWeb.InboxLive` — pending proposals, approve / reject
- `/onboard` — `AimWebWeb.OnboardLive` — guided creation wizard

## Onboarding (guided creation)

`aim-onboard --template <yaml> --tenant-id <uuid>` walks the user (or LLM)
through a question script and applies the answers to AIM_FS.

Templates ship in `/opt/aim/templates`:

| Template | Creates |
|---|---|
| `research_project.yaml` | 11-file core under `users/<u>/projects/<slug>/` + project_state + N feedback rules in inbox |
| `patient.yaml` | patient folder + identity.toml + ANAMNESIS.md + consent.json + first visit |
| `self_dev_proposal.yaml`| AIM self-dev proposal markdown + `proposal_v1` entity |

See `~/Desktop/LongevityCommon/AIM/docs/AIM_FS/ONBOARDING.md` for the
question/template contract.

## Why "better than Claude memory"

| Axis | Claude auto-memory | aim-fs |
|---|---|---|
| Approval queue | none — auto-saves | inbox + LiveView UI |
| Versioning | none | versions table + sha256 |
| Graph | none | typed links table |
| Provenance | only `originSessionId` | full `created_by` + events log |
| Decay | "verify before use" | TTL + sweeper |
| Scoping | global | global / user / project / patient |
| Schema validation | none | per-type validators |
| Conflict resolution | duplicates silently coexist | `disputed` status + dispute log |
| Multi-tenant | single user | `tenant_id` on every row |
| Index | one heavy MEMORY.md | SQLite indexes, lazy |
| Audit trail / replay | none | events.jsonl-style table, replay-able |
| Schema-driven UI | CLI text edit | LiveView (auto-generated form per schema) |
| Atomicity | best-effort | `BEGIN IMMEDIATE` + idempotency table |

(13 of 15 axes — FTS-search and cascading decay are Phase 2.)
