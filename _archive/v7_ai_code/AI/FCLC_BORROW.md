# FCLC → AIM Hive — что переносить

**Дата:** 2026-05-03
**Контекст:** AIM/_archive/queen_deploy_2026-05-07 запущен 2026-05-03 на hive.longevity.ge.
FCLC живёт на сервере `jaba@server:/home/jaba/web/fclc/`, репо
`djabbat/FCLC` (private), CONCEPT v6.2.

FCLC — federated medical infrastructure, AIM Hive — federated agent
intelligence. Архитектурно идентичны (orchestrator + nodes), но FCLC
гораздо зрелее по privacy primitives. Перенести стоит четыре блока,
в порядке приоритета.

## P1 · DP accountant (1-2 дня)

**FCLC source:** `fclc-core/src/dp/mod.rs::LinearDpAccountant`
- `new(budget) → Self`
- `spend(epsilon) → Result<, DpError>` — атомарно списывает
- `remaining`, `fraction_consumed`
- `epsilon_projection(rounds, eps_per_round) → (eps_total, will_exceed)`

**Зачем AIM:** сейчас `hive_telemetry.contribution` шлёт payload
без ε-budget. L_PRIVACY — regex-only. Добавить
`AIM_HIVE_DP_BUDGET=1.0` в `~/.aim_env`; каждый `contribute` бьёт
`spend(eps_per_round)`; на 0 — переключаться в read-only (worker
тянет updates, но не отдаёт сигнал).

**Где разместить:** `AI/ai/dp_accountant.py` (Python port — не тащить
Rust в worker'a). Интегрировать в `hive_telemetry._scrub` как
финальный gate перед POST.

## P2 · Calibrated noise (1 день)

**FCLC source:** `fclc-core/src/dp/mod.rs`
- `gaussian_noise_sigma(sensitivity, epsilon, delta) → f64`
- `gaussian_noise(...)` — sample
- `clip_gradient(grad, max_norm)`

**Зачем AIM:** numeric metrics (compliance %, retry rate, avg crit)
сейчас пишутся точно. Очевидно, что `compliance=0.85` от worker A в
тот же hour, что у B = идентификация. Добавить σ ≈ 0.05–0.1 к каждой
числовой метрике перед send.

**Где:** `AI/ai/hive_telemetry.py::contribution` — после `_scrub`,
перед POST. Только numeric поля, не theme labels.

## P3 · Shapley scoring (P1 нужен сначала)

**FCLC source:** `fclc-core/src/scoring/mod.rs::ShapleyScorer`
- `new(n)` / `with_samples(n, samples)` — Monte-Carlo Shapley
- `compute(performance_fn) → Vec<f64>` — marginal contributions
- `estimation_error(...)` — confidence

**Зачем AIM:** queen сейчас не знает, кто из worker'ов даёт ценный
сигнал. Если 8 worker'ов отослали contributions, и кандидат прошёл
eval, какие worker'ы внесли реальный прирост? ShapleyScorer на
`distill_candidates` → leaderboard worker'ов в `/v1/hive/status`.

**Где:** `AI/ai/hive_queen.py` — новая функция `worker_contributions`
которая берёт последние N raised candidates и computes Shapley.

**Не делать раньше:** до накопления ≥30 distilled candidates Shapley
estimates имеют слишком широкий CI.

## P4 · SecAgg+ (НЕ сейчас)

**FCLC source:** `fclc-core/src/aggregation/secagg.rs` (572 lines)
- `NodeKeypair` (X25519), `derive_pairwise_seed`
- `shamir_split_gf257`, `shamir_reconstruct_gf257`
- `secagg_apply_masks`, `secagg_aggregate`
- `chacha20_pairwise_mask`

**Зачем AIM (теоретически):** queen видит plaintext payloads. SecAgg+
делает каждый отдельный payload бессмысленным — только sum
вычисляется. Защищает от compromised queen.

**Почему отложить:** при <10 worker'ах round-trip pairwise key
exchange + Shamir overhead убивает простоту queen API. Threshold для
эффективности ≈ N>20, мы ещё не там.

**Re-evaluate когда:** в `/v1/hive/status` стабильно ≥20 active
workers за 7-day rolling window.

## Что НЕ переносить

- **OMOP CDM adapter** (`fclc-node/src/adapter/`) — clinical-specific,
 AIM не работает с EHR/HIS.
- **k-anonymity / generalizer** (`privacy/deidentify`) — оверкилл для
 AIM payload (там нет patient records, только aggregate counters).
- **Marketplace + Voucher ROI layer** (`marketplace_layer/`) —
 социальный инструмент для clinics, не нужен для dev workers.
- **mobile_node.rs** — mobile clients не в AIM scope.

## Owner / next step

**Owner:** AIM/AI subproject (см. `AI/CLAUDE.md`).
**Next:** P1 (DP accountant) — `AI/ai/dp_accountant.py` — целевой
sprint когда eval baseline будет достаточно стабилен (~2 weeks
после первых contributions от внешних worker'ов).
