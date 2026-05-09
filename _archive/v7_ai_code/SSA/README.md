# SSA — Systemic Syndrome Analysis (AIM internal microservice, Rust + REST :8766)

Полная архитектура / theory / evidence / open problems → `docs/ssa/`.

| Документ | Где |
|---|---|
| Концепция | `docs/ssa/CONCEPT.md` |
| Дизайн / алгоритмы | `docs/ssa/DESIGN.md` |
| Эмпирические evidence | `docs/ssa/EVIDENCE.md` |
| Открытые проблемы | `docs/ssa/OPEN_PROBLEMS.md` |
| Параметры / config | `docs/ssa/PARAMETERS.md` |
| Текущий state runtime | `docs/ssa/STATE.md` |
| Theory | `docs/ssa/THEORY.md` |
| Operational руководство для AI | `docs/ssa/CLAUDE.md` |

## Запуск backend

```bash
cd backend
cargo build --release
AIM_SSA_URL=http://127.0.0.1:8766 ./target/release/ssa-server
```

`_build_kernel.py` (этот subproject) — генератор Rust-патtern из Excel; запуск
как build step перед `cargo build`.

Caller: `rust-core/crates/aim-doctor/src/main.rs:44` (`AIM_SSA_URL` env).

См. также: `MAP.md` § 2.5 (Internal microservices).
