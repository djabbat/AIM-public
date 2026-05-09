# AIM Phase 3 — журнал этапов (autonomously)

Каждый этап = один git commit на `main`. Регенерируется
`_journal/regenerate.sh` из `git log`.

Последнее обновление: **2026-05-05 21:39**.

Workspace: **178 крейтов**.

## Phase 3 commits (newest first)

| sha | message |
|-----|---------|
| 64bb2e3 | eco-inject v=60: fix theme toggle on subdomains (undefined injectLangBar() threw before wireThemeToggle) |
| 42dce78 | AIM root.html.heex: bump eco-inject.js to v=59 |
| e126fec | eco-inject v=59: theme toggle re-binds via wireThemeToggle(); remove Annals link from eco-bar + GLA injected nav |
| e5122bf | AIM/aim_web: add GET /health JSON endpoint for monitoring |
| 3ea6792 | deploy/server-state: snapshot of live server.longevity.ge config |
| 197f7f8 | AIM favicon: pre-encoded SVG (URI.encode skipped # which broke browsers) |
| 43fd210 | eco-inject v=58 + AIM concentric favicon |
| fa81074 | eco-inject v=57: indigo on FCLC's Tailwind hero in dark mode |
| bf63cd1 | eco-inject v=56 + DESIGN_CONCEPT canon: persistent injection across LiveView |
| 0c383a2 | eco-inject v=55: lang switcher works on FCLC (and any subdomain) |
| 1bb2943 | eco-inject v=54: lang switcher INSIDE own-header (under hero), not bottom |
| ef82a4b | AIM: native lang switcher in layout (server-rendered, LiveView-safe) |
| d94b7ea | AIM CSP: allow longevity.ge origin so eco-inject.js loads |
| b3403a7 | AIM home: own-header BETWEEN hero and content (no LiveView flicker) |
| 70ad263 | eco-inject v=52 + AIM layout: own-header above inner_content |
| e6ca904 | eco-inject v=51: fix relocateOwnHeader for AIM (was skipping it) |
| 1b0aa08 | eco-inject v=50: own-header UNDER hero on every subdomain (incl. home/mcoa/cdata) |
| 1c468ad | eco-inject v=49: unified layout — header on top, hero under it, lang at bottom |
| 622bde1 | eco-inject v=48: bottom language switcher on every subdomain (like AIM) |
| d90ee0b | eco-inject v=47: unify own-header style across all subdomains |
| bf7862f | eco-inject v=46: unify own-header inner width to 1100px across subdomains |
| 8656db9 | eco-inject v=45: hero-stats tiles + hero-pill + donate-options bg fix |
| ddc4a40 | eco-inject v=44: .page-hero (team/grants etc) + AIM subnav under hero |
| 34bd328 | eco-inject v=43: hero background stays indigo in dark — root cause fix |
| 7eae434 | eco-inject v=42: hide hive's native hero + walk all .hero descendants |
| d53ac1a | home: bake inline indigo hero into HTML so GLA stays blue in dark |
| fa92422 | eco-inject v=41: indigo hero on hive too + JS-forced home brand |
| 036d880 | eco-inject v=39: indigo hero on every subdomain page + GLA stays white |
| 8dc9c16 | eco-inject v=38: don't break Hive's hero, fix home GLA title in dark |
| df0c8c1 | eco-inject v=36: hero stays indigo-blue in dark mode |
| 47f9a42 | eco-inject v=35: full home-style for all subdomains (Annals excluded) |
| 737c1f4 | phoenix: AIM web matches longevity.ge home — light/dark, hero, theme toggle |
| d49f439 | phoenix: AIM header pixel-identical to eco-inject.js v=31 |
| 69a9f1b | phoenix: native ecosystem bar in AIM topbar (no eco-inject conflict) |
| 292a2b5 | phoenix: real AIM web — landing + 7 langs + live RPC + theme |
| be2c520 | server-patch: ensure AIM nav button reaches every *.longevity.ge vhost |
| 3d6198f | eco-inject: add AIM button to shared longevity.ge nav header |
| 40aa241 | deploy-server.sh: production-ready after server-2 rollout |
| 170a9ce | phoenix: server:true in runtime.exs so release boots HTTP listener |
| f3e7859 | phoenix: releases config + Orchestrator stubs for new LiveViews |
| db3587e | AIM Phase 4 finale — UI + installers + warning cleanup |
| 1a57d7f | core Phase 4 — aim-cli (top-level subcommand parser) |
| ae78615 | core Phase 4 — aim-web-api + aim-telegram-bot |
| bbceaaf | core Phase 4 — db + user-keys + lab-reference + llm-router |
| d1dd8f1 | core Phase 4 — aim-config + aim-rate-limit + aim-webhooks |
| 5170e89 | scripts Phase 3 — aim-import-claude-memory + aim-user-admin |
| c31f1e0 | scripts Phase 3 — aim-backup-system + aim-analyze-claude-memory |
| 05284c1 | scripts Phase 3 — aim-weekly-digest + aim-check-docs-consistency |
| 59fb3f3 | scripts Phase 3 — aim-auto-eval + aim-daily-brief |
| fc68bb6 | agents Phase 3 — aim-patient-inbox-watcher + aim-disk-monitor |
| 7715ccd | agents Phase 3 — aim-resilient-llm + aim-session-visualiser |
| c89564e | agents Phase 3 — aim-recall-cli + aim-router-ab-test |
| 942b3d9 | agents Phase 3 — aim-complexity-classifier + aim-async-reindex |
| 9a64c29 | agents Phase 3 — aim-serve-daemon + aim-embed-daemon |
| 2ace2fb | agents Phase 3 — aim-embed-cache + aim-graphrag-cache |
| 1d8074c | agents Phase 3 — aim-graphrag + aim-memory-index |
| b9e71ef | agents Phase 3 — aim-ui-theme + aim-telegram-extras |
| bc3c426 | agents Phase 3 — aim-project-graph + aim-auth |
| 3843f77 | agents Phase 3 — aim-project-export + aim-project-pdf-export |
| cc49922 | agents Phase 3 — aim-kpi-auto-updater + aim-readme-generator |
| 4eac9bf | agents Phase 3 — aim-patient-dedup + aim-patient-memory |
| 5634b30 | agents Phase 3 — aim-diff-analyser + aim-labs |
| b164310 | agents Phase 3 — aim-prompt-evolver + aim-interactions |
| edba551 | agents Phase 3 — aim-pi-agent + aim-self-health |
| 022861f | agents Phase 3 — aim-routines + aim-job-queue |
| 6db1ce1 | agents Phase 3 — aim-doctor-dry-run + aim-escalation-engine |
| 3cc50d4 | agents Phase 3 — aim-doctor-calibration + aim-doctor-consult |
| 3ff2725 | agents Phase 3 — aim-tree-planner + aim-module-registry |
| 0d78769 | agents Phase 3 — aim-pairing + aim-cli-completion |
| 1e10724 | agents Phase 3 — aim-aider-tool + aim-speculative-prefetch |
| f4fb724 | agents Phase 3 — aim-context-compressor + aim-session-manager |
| b3091f6 | agents Phase 3 — aim-chat (kernel-powered multilingual chat companion) |
| af03354 | agents Phase 3 — aim-mcp-loader (MCP-style runtime tool registry) |
| fcb6230 | agents Phase 3 — aim-metrics + aim-slash-commands |
| c83a0f4 | agents Phase 3 — aim-hooks + aim-tracing (event registry + tracing abstraction) |
| 231d839 | agents Phase 3 — aim-graph (planner/executor/reviewer state machine) |
| d82ecd5 | agents Phase 3 — aim-email-agent (Gmail with kernel-enforced gates) |
| 546ee01 | agents Phase 3 — aim-kernel (Asimov laws + Ze-formula scoring) |
| e7b333a | agents Phase 3 — aim-intake (OCR / PDF / WhatsApp ingest) |
| fd5f352 | agents Phase 3 — aim-doctor-agent (diagnosis / treatment / labs / chat) |
| cbc5c07 | agents Phase 3 — aim-lang (translate / detect / explain / simplify) |
| 0bea3e9 | agents Phase 3 — aim-writer + aim-researcher (LLM-backed scientific writing) |
| 362ce27 | agents Phase 3 — aim-orchestrator (kernel pipeline + Ze-verify) |
| 329b0fd | agents Phase 3 — aim-coder (closed-loop edit→test agent) |
| b8792dc | agents Phase 3 — aim-memory-tui (TUI state machine, no curses dep) |
| f036f22 | agents Phase 3 — aim-memory-cli (subcommand orchestration library) |
| 646cb76 | agents Phase 3 — aim-memory-date-correction (TTL/expires_at auto-fixer) |
| a7ba9d5 | agents Phase 3 — aim-memory-store (cross-session fact persistence) |
| 59f2f8b | agents Phase 3 — aim-memory-prefetch (predictive entity NER + TTL/LRU cache) |
| 5283ef2 | agents Phase 3 — aim-memory-monitor (M1 hygiene scanner) |
| 6d099fe | agents Phase 3 — aim-memory-remediator (RM1 broken-path suggester) |
| 360ebe6 | agents Phase 3 — aim-memory-versioning (git-like memory snapshots) |
| 21ff946 | agents Phase 3 — aim-memory-priority (priority + TTL for memory facts) |
| 2ca7701 | agents Phase 3 — aim-project-archive (A1 auto-archive flow) |
| ffecce8 | AIM/.gitignore — restore content I clobbered in eadb321 |
| eadb321 | AIM/_journal — bash orchestrator (9s) + per-stage journal |
| 5785695 | agents Phase 3 — aim-memory-deduplicate (find + merge near-dups) |
| 1526162 | agents Phase 3 — aim-profile (multi-tenant profile isolation) |
| 40f2ebc | agents Phase 3 — aim-health-extended (G9 full system snapshot) |
| 1490b8e | agents Phase 3 — aim-memory-health (healthcheck framework) |

## Текущая ветка

```
## main...origin/main
 M _journal/STAGES.md
```
