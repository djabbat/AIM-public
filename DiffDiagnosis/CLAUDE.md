# CLAUDE.md — DiffDiagnosis

## Расположение
`~/Desktop/AIM/DiffDiagnosis/` — подпроект AIM.
Git: НЕ собственный репозиторий; часть монорепо AIM (`~/Desktop/AIM/`).  
Все коммиты через `git -C ~/Desktop/AIM`.

## Startup (каждая сессия)
1. Прочитать `CONCEPT.md`, `STATE.md`, `OPEN_PROBLEMS.md` (лежат в корне подпроекта).
2. Проверить consistency между 9 core `.md`:
   - `sources/vinogradov_01_chest_pain.md`
   - `sources/vinogradov_02_dyspnea_cough_hemoptysis.md`
   - `sources/vinogradov_03_abdominal_pain.md`
   - `sources/vinogradov_04_jaundice_hepatomegaly.md`
   - `sources/vinogradov_05_fever_FUO.md`
   - `sources/vinogradov_06_lymphadenopathy_splenomegaly.md`
   - `sources/vinogradov_07_anemia_cytopenias.md`
   - `sources/taylor_*.md` (все файлы Taylor)
   - `sources/meta_*.md` (все мета-аналитические обзоры).
3. Если в `STATE.md` есть active TODOs — отчитаться в начале ответа: `[STATE: ...]`.

## LLM правила
- Только через `~/Desktop/AIM/llm.py` (команды `ask_deep` / `ask`).  
- Никаких прямых вызовов DeepSeek API, никаких `curl`, `requests`, `openai`, `anthropic`, `deepseek` и т.д.  
- Если нужен LLM для анализа или генерации текста — вызывать через `llm.py`.

## Источник истины
- `sources/*.md` — knowledge base (авторитетные алгоритмы Виноградов/Taylor, мета-аналитика).  
- `backend/data/algorithms.json` — формализованная детерминированная схема (JSON, эквивалент `.md`).  
- При изменении алгоритма:  
  1. сперва обновить соответствующий `sources/*.md`;  
  2. потом синхронизировать `backend/data/algorithms.json`;  
  3. потом обновить backend-тесты (Rust).  
- `EVIDENCE.md` — подпись для любых LLM-вставок в алгоритмы (указывать источник, дату, версию модели).

## Что НЕ делать
- Не выкидывать главы Виноградова/Taylor (ни одну из 9 core).  
- Не подменять алгоритмы LLM-генерацией без внесения записи в `EVIDENCE.md`.  
- Не коммитить файлы из `Patients/` (это AIM-уровневое правило, пациентские данные не в репозиторий).

## Тесты
- Backend (Rust): `cd ~/Desktop/AIM/DiffDiagnosis/backend && cargo test`  
- Frontend (Phoenix): `cd ~/Desktop/AIM/DiffDiagnosis/frontend && mix test`  
- При изменении `algorithms.json` или любого `sources/*.md` — прогонять оба набора тестов.

## Деплой
TBD (пока не настроен).  
Деплойные скрипты ожидаются в `scripts/deploy.sh` — не запускать вручную без явного указания.