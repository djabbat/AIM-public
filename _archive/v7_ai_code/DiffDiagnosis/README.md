# DiffDiagnosis — AIM internal microservice (Rust + REST :8765)

Полная архитектура / theory / evidence / open problems → `docs/diffdiagnosis/`.

| Документ | Где |
|---|---|
| Концепция | `docs/diffdiagnosis/CONCEPT.md` |
| Дизайн / алгоритмы | `docs/diffdiagnosis/DESIGN.md` |
| Эмпирические evidence | `docs/diffdiagnosis/EVIDENCE.md` |
| Открытые проблемы | `docs/diffdiagnosis/OPEN_PROBLEMS.md` |
| Параметры / config | `docs/diffdiagnosis/PARAMETERS.md` |
| Текущий statе runtime | `docs/diffdiagnosis/STATE.md` |
| Theory PV | `docs/diffdiagnosis/THEORY.md` |
| Operational руководство для AI | `docs/diffdiagnosis/CLAUDE.md` |

## Запуск backend

```bash
cd backend
cargo build --release
AIM_DIFFDX_URL=http://127.0.0.1:8765 ./target/release/diffdx-server
```

Caller: `rust-core/crates/aim-doctor/src/main.rs:43` (`AIM_DIFFDX_URL` env).

См. также: `MAP.md` § 2.5 (Internal microservices).
