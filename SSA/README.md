# SSA — Syndromic Hematology Analyzer

**SSA** — это движок системного синдромального анализа (AIM/SSA) полного клинического анализа крови (CBC).  
Назначение: по 28 параметрам CBC, дискретизированным в 5 зон (L2–L0–H2), построить ранжированный список гематологических синдромов для последующей дифференциальной диагностики (DiffDiagnosis).

## Принцип работы

1. **Оцифровка (zonal mapping)**: каждый из 28 параметров CBC преобразуется в одну из 5 зон:
   - L2 (≪ нижний критический)
   - L1 (ниже оптимума)
   - L0 (оптимум)
   - H1 (выше оптимума)
   - H2 (≫ верхний критический)

2. **Сопоставление с паттернами**: вектор зон (длина 28) сравнивается с базой синдромальных паттернов (15 парных + 15 тройных/синдромальных).

3. **Ранжирование**: на выходе — список синдромов, отсортированных по вероятности (основа — таблицы соответствия зональных комбинаций).

Результат SSA передаётся в модуль **DiffDiagnosis** для перехода к нозологическому диагнозу.

## Пример входа / выхода

### Вход (JSON)

```json
{
  "WBC":  2.1,
  "RBC":  3.0,
  "HGB":  85,
  "HCT":  0.25,
  "MCV":  83,
  "MCH":  28,
  "MCHC": 340,
  "RDW":  15.5,
  "PLT":  45,
  "MPV":  9.4,
  "PDW":  14,
  "PCT":  0.05,
  "NEUT_abs": 0.9,
  "NEUT_pct": 42.9,
  "LYMPH_abs": 0.8,
  "LYMPH_pct": 38.1,
  "MONO_abs": 0.3,
  "MONO_pct": 14.3,
  "EOS_abs": 0.1,
  "EOS_pct": 4.8,
  "BASO_abs": 0.0,
  "BASO_pct": 0.0,
  "RETIC": 0.2,
  "ESR":  60,
  "NLR":  1.1,
  "PLR":  56.3,
  "SII":  47,
  "RDW_PLT": 0.34
}
```

### Выход (ранжированные синдромы)

```
TOP-3 SYNDROMES
┌─────────────────────────────────────┬──────────┐
│ Синдром                             │ Score    │
├─────────────────────────────────────┼──────────┤
│ PANCYTOPENIA                        │ 0.92     │
│ BICYTOPENIA_HEM_PLT                 │ 0.87     │
│ BONE_MARROW_FAILURE                 │ 0.81     │
└─────────────────────────────────────┴──────────┘
```

Далее каждый синдром сопровождается дифференциальным рядом (DiffDiagnosis): апластическая анемия, MDS, миелофиброз, ПНГ и т.д.

## Запуск backend / frontend

### Предварительные требования

- Rust (>= 1.75)
- Erlang/OTP (>= 26), Elixir (>= 1.16)
- PostgreSQL (для хранения reference ranges и логов)
- Node.js / npm (для сборки ассетов Phoenix)

### Backend (Rust, Axum)

```bash
cd ~/Desktop/AIM/SSA/backend
cargo build --release
./target/release/ssa-backend --config config.toml
```

Backend слушает порт 8080 (по умолчанию). Эндпоинты описаны ниже.

### Frontend (Phoenix LiveView)

```bash
cd ~/Desktop/AIM/SSA/frontend
mix deps.get
mix phx.server
```

Frontend доступен по адресу `http://localhost:4000`.  
Подключение к backend настраивается через `config/prod.exs`.

### Полный запуск через `docker-compose` (опционально)

```bash
cd ~/Desktop/AIM/SSA
docker-compose up --build
```

## API

### `POST /api/v1/analyze`

**Тело запроса** — JSON с CBC-параметрами (пример выше).  
**Ответ** — ранжированный список синдромов с оценками.

Пример cURL:

```bash
curl -X POST http://localhost:8080/api/v1/analyze \
  -H "Content-Type: application/json" \
  -d '{"WBC":2.1, "HGB":85, "PLT":45, ...}'
```

Пример ответа:

```json
{
  "syndromes": [
    {"name": "PANCYTOPENIA", "score": 0.92},
    {"name": "BICYTOPENIA_HEM_PLT", "score": 0.87},
    {"name": "BONE_MARROW_FAILURE", "score": 0.81}
  ],
  "zonal_vector": [0,0,0,2,1, ...],
  "matched_patterns": ["PANCYTOPENIA", "BICYT_PLT_HGB"]
}
```

### `GET /api/v1/health`

Проверка работоспособности.

### `GET /api/v1/patterns`

Возвращает полный список синдромальных паттернов с описанием зональных conditions (для отладки).

## Источники

| № | Источник | Применение |
|---|----------|------------|
| 1 | Hoffbrand A.V., Moss P.A.H. *Hoffbrand's Essential Haematology*, 8th ed., 2020. | Определение синдромов, reference ranges |
| 2 | Kaushansky K. et al. *Williams Hematology*, 10th ed., 2021. | Пороговые критерии, evidence-based cutoffs |
| 3 | Wintrobe M.M. *Clinical Hematology*, 14th ed., 2018. | Исторические референсы, классификация анемий |
| 4 | ICSH (International Council for Standardization in Haematology) 2014. | Стандарты референсных интервалов, рекомендации по анализаторам |
| 5 | BCSH (British Committee for Standards in Haematology) guidelines. | Диагностические пороги, ведение панцитопении, лейкоцитоза |
| 6 | Bessman J.D. et al. *Am J Clin Pathol* 1983;80:170–173. | Классификация анемий по MCV/RDW |
| 7 | Zahorec R. *Bratisl Lek Listy* 2001;102:5–14. | NLR при сепсисе и стрессе |
| 8 | Hu B. et al. *Oncotarget* 2014;5:5441–5452. | SII в онкологии |
| 9 | Cabitza F. et al. *Diagnostics* 2021;11:345. | ML-модели на CBC, accuracy сравнение с человеком |

## Лицензия

**TBD** (предполагается MIT или Apache 2.0).  
Проект находится в стадии активной разработки. Для коммерческого использования свяжитесь с авторами.

## Структура репозитория

```
~/Desktop/AIM/SSA/
├── backend/               # Rust (Axum) — core engine, zonal mapper, pattern matcher
│   ├── src/
│   │   ├── main.rs
│   │   ├── zonal.rs       # 5-zone discretization
│   │   ├── patterns.rs    # pattern definitions & matching
│   │   └── api.rs         # req/resp handlers
│   ├── config.toml        # user-defined thresholds
│   └── Cargo.toml
├── frontend/              # Phoenix LiveView — UI
│   ├── lib/               # LiveView, templates
│   └── config/
├── models/                # JSON-схемы, reference ranges (ICSH, BCSH)
├── tests/                 # gold dataset из ~200 CBC, validation scripts
└── docker-compose.yml     # удобный запуск
```

## Связь с AIM и DiffDiagnosis

```
CBC → SSA → ranked syndromes → DiffDiagnosis → nosological list
```

SSA — первый этап: цифровой "черновик" синдромов.  
DiffDiagnosis использует этот список как вход для построения нозологического дифференциального ряда (с помощью LLM или стохастического алгоритма).