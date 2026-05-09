# AI — отдельный подпроект внутри AIM

## Identity

**Project:** AI (AIM/AI)
**Status:** v0.1.0 — bootstrap (2026-05-03)
**Location:** `~/Desktop/LongevityCommon/AIM/AI/`
**Parent project:** AIM (operational AI runtime)

## Цель

AIM сам по себе — operational layer (project ownership, brief, doctor,
escalation). AI — dedicated subproject где живёт *capability development*:
все модули, чья единственная задача — сделать AIM умнее, и где
эксперименты можно запускать без риска поломать operational stack.

## Scope (что лежит здесь)

- **eval_synthesiser** — генерирует новые eval cases из session
 reflexions + failure logs (закрывает цикл S4 pattern_miner → S1 evals)
- **(planned) self_modify** — S6 code self-modification: после ≥4 weeks
 of accumulated baselines, AI proposes patches к `agents/`, тестирует
 их в worktree, мерджит при стат-значимом улучшении
- **(planned) distillation_tracker** — measure performance того же eval
 suite на разных tier моделях (DS-pro, Sonnet, Haiku, qwen2.5:7b);
 surface когда меньшая модель догнала бигтайра
- **(planned) reflexion_clusterer** — group recurring failure patterns
 into themes, propose targeted prompt patches per theme

## Out of scope (что НЕ здесь)

- Project ownership, daily brief, escalation → `agents/`
- Doctor diagnostics, regimen validation → `agents/doctor*.py`
- Notification multiplexing, cost ledger, memory monitor → `agents/`
- Анализ сторонних публикаций, OCR пациентских INBOX → `agents/`

## Зависимости

```
AI/ → agents/ (одностороннее)
agents/ ↛ AI/ (НИКОГДА — AI is opt-in experimentation)
```

Если убрать AI/ целиком — операционный AIM не должен заметить.
Это правило позволяет нам ставить AI-эксперименты под feature-flag
и rollback одним `rm -rf AI/`.

## Коды модулей

| ID | Модуль | Закрывает | Status |
|-----|---------------------------------|------------------------------------------|--------|
| S8 | `ai/eval_synthesiser.py` | reflexions → eval cases (real run: 63) | ✅ |
| S9 | `ai/distillation_tracker.py` | per-tier downgrade-safe matrix | ✅ |
| S10 | `ai/reflexion_cluster.py` | failure clusters → prompt-patch hints | ✅ |
| S11 | `ai/gap_detector.py` | "I cannot X" → capability-gap clusters | ✅ |
| SD1 | `ai/self_diagnostic.py` | 9-phase prompt builder | ✅ |
| S12 | `ai/meta_evaluator.py` | reproducibility metrics + line_compliance| ✅ |
| S13 | `ai/stable_run.py` | N-run consolidator (signal vs noise) | ✅ |
| S14 | `ai/fix_planner.py` | shared findings → file:line fix plan | ✅ |
| DG1 | `ai/diagnostic_ledger.py` | SQLite ledger каждого diagnostic run + prune_phantom | ✅ |
| RD1 | `ai/regression_detector.py` | diff между двумя последними ledger rows | ✅ |
| RA1 | `ai/regression_alert.py` | RD1 → notify (Telegram/email/dedup) | ✅ |
| FE1 | `ai/findings_to_evals.py` | file:line → yaml regression eval cases | ✅ |
| DB1 | `ai/dashboard.py` | 9-section consolidated AI/ view + JSON | ✅ |
| DR2 | `ai/doctor.py` | smoke-test AI/ wiring + direction rule | ✅ |
| CV1 | `ai/case_validator.py` | yaml schema check FE1-emitted cases | ✅ |
| CA1 | `ai/case_archiver.py` | stale FE1 cases → `_archived/` | ✅ |
| MB1 | `ai/morning_brief.py` | wake-up brief: doctor + regression + trend | ✅ |
| PV1 | `ai/prompt_versions.py` | sha256 fingerprint trail SELF_DIAGNOSTIC_PROMPT.md | ✅ |
| PI1 | `ai/prompt_impact.py` | correlate prompt revisions × ledger metrics | ✅ |
| AS1 | `ai/auto_sweep.py` | 6-step periodic maintenance | ✅ |
| HS1 | `ai/health_score.py` | 0-100 score + history + info_line | ✅ |
| SG1 | `ai/safety_gate.py` | cooldown + budget pre-flight для run_self_diagnostic | ✅ |
| BK1 | `ai/backup.py` | JSON dump/restore всех DB | ✅ |
| S6 | `ai/self_modify.py` | framework only (gate closed until baseline mature) | 🟡 |

## Запуск

```bash
cd ~/Desktop/LongevityCommon/AIM
# Тесты подпроекта (через корневой pytest):
~/Desktop/LongevityCommon/AIM/venv/bin/python -m pytest AI/tests/ -q

# Конкретный модуль:
~/Desktop/LongevityCommon/AIM/venv/bin/python -m AI.ai.eval_synthesiser

# CLI-связки через aim_cli:
aim diag --doctor # smoke-test wiring (DR2)
aim diag --dashboard # 9-section consolidated state (DB1)
aim diag --dashboard --json # machine-readable
aim diag --score # 0-100 health (HS1) + trend
aim diag --info # one-line for cron logs (HS1)
aim diag --morning # human wake-up brief (MB1)
aim diag --trend # ledger trend (DG1)
aim diag --regress # last-vs-prev diff (RD1)
aim diag --history 10 # N most recent runs (DG1)
aim diag --gen-cases # findings → regression evals (FE1)
aim diag --validate-cases # yaml schema check (CV1)
aim diag --archive-cases # retire stale (CA1)
aim diag --prune-phantom # cleanup test-leftovers (DG1)
aim diag --sweep # 6-step periodic maintenance (AS1)
aim diag --save # write fix plan markdown (S14)
```

## Closed-loop pipeline

```
SD1 build_prompt
 ↓
run_self_diagnostic (auto-retry on low compliance)
 ↓
DG1 ledger record
 ↓
RD1 detect → RA1 notify
 ↓
S13 stable_run consolidate
 ↓
S14 fix_planner advice
 ↓
FE1 findings_to_evals → AIM_EVAL_CASES_DIR
 ↓
S1 eval harness (regression gate)

DB1 dashboard reads everything; DR2 doctor smoke-tests wiring.
```

## Правила разработки

- **Каждый AI-модуль = closed loop.** Должен иметь measurable signal
 (eval delta, reflexion count, model comparison) — без метрик не
 мерджим.
- **Eval-gated changes only.** Прежде чем модифицировать промпты или
 код в operational stack — прогон через S1 eval harness, p ≤ 0.05,
 Δscore ≥ 0.05.
- **Worktree isolation.** Любой code-modification flow обязан
 использовать `agents.worktree.isolate` чтобы никогда не трогать
 main checkout.
- **L_VERIFIABILITY enforced.** Цитаты в любом сгенерированном тексте
 проходят `agents.citation_guard.verify(strict=True)`.

## Связь с canonical AIM ROADMAP

Этот подпроект является преемником S6/S7-волн из roadmap
`~/Desktop/LongevityCommon/AIM/ROADMAP_SURPASS_ClaudeCode_2026-05-02.md`.
S6 был отложен до тех пор, пока eval baseline не накопится; AI/ — место
где S6+ будет жить когда время придёт.
