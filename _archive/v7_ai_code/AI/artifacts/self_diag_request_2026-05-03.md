# AIM/AI Self-Diagnostic — Run-time Snapshot

_captured_at:_ 2026-05-03T05:10:03
_ai_root:_ /home/oem/Desktop/LongevityCommon/AIM/AI
_n_modules:_ 5
_direction_rule_clean:_ True
_agents_imports:_ 0

## Inventory (ground truth — do NOT recompute, USE this)

```json
{
 "captured_at": "2026-05-03T05:10:03",
 "ai_root": "/home/oem/Desktop/LongevityCommon/AIM/AI",
 "n_modules": 5,
 "modules": [
 {
 "path": "/home/oem/Desktop/LongevityCommon/AIM/AI/ai/distillation_tracker.py",
 "loc": 231,
 "public_functions": [
 "db_path",
 "record",
 "run_tier",
 "run_all_tiers",
 "latest_per_tier_per_case",
 "compare_tiers",
 "downgrade_candidates",
 "summary",
 "reset_db_for_tests"
 ],
 "public_classes": [
 "Tier",
 "DowngradeRecommendation"
 ],
 "imports": [
 "__future__",
 "dataclasses",
 "datetime",
 "json",
 "logging",
 "os",
 "sqlite3",
 "threading",
 "pathlib",
 "typing"
 ],
 "tests": [
 {
 "path": "/home/oem/Desktop/LongevityCommon/AIM/AI/tests/test_distillation_tracker.py",
 "loc": 161,
 "test_count": 13
 }
 ]
 },
 {
 "path": "/home/oem/Desktop/LongevityCommon/AIM/AI/ai/eval_synthesiser.py",
 "loc": 375,
 "public_functions": [
 "cases_dir",
 "audit_path",
 "synthesise_from_reflexion",
 "synthesise",
 "audit"
 ],
 "public_classes": [
 "CaseSpec"
 ],
 "imports": [
 "__future__",
 "dataclasses",
 "datetime",
 "hashlib",
 "json",
 "logging",
 "os",
 "re",
 "pathlib",
 "typing"
 ],
 "tests": [
 {
 "path": "/home/oem/Desktop/LongevityCommon/AIM/AI/tests/test_eval_synthesiser.py",
 "loc": 246,
 "test_count": 22
 }
 ]
 },
 {
 "path": "/home/oem/Desktop/LongevityCommon/AIM/AI/ai/gap_detector.py",
 "loc": 247,
 "public_functions": [
 "sessions_dir",
 "surrenders",
 "gaps",
 "summary"
 ],
 "public_classes": [
 "Surrender",
 "Gap"
 ],
 "imports": [
 "__future__",
 "collections",
 "dataclasses",
 "datetime",
 "json",
 "logging",
 "os",
 "re",
 "pathlib",
 "typing"
 ],
 "tests": [
 {
 "path": "/home/oem/Desktop/LongevityCommon/AIM/AI/tests/test_gap_detector.py",
 "loc": 191,
 "test_count": 16
 }
 ]
 },
 {
 "path": "/home/oem/Desktop/LongevityCommon/AIM/AI/ai/reflexion_cluster.py",
 "loc": 223,
 "public_functions": [
 "cluster",
 "clusters_from_memory",
 "summary"
 ],
 "public_classes": [
 "Cluster"
 ],
 "imports": [
 "__future__",
 "dataclasses",
 "datetime",
 "logging",
 "re",
 "pathlib",
 "typing"
 ],
 "tests": [
 {
 "path": "/home/oem/Desktop/LongevityCommon/AIM/AI/tests/test_reflexion_cluster.py",
 "loc": 185,
 "test_count": 16
 }
 ]
 },
 {
 "path": "/home/oem/Desktop/LongevityCommon/AIM/AI/ai/self_diagnostic.py",
 "loc": 212,
 "public_functions": [
 "project_root",
 "ai_root",
 "prompt_path",
 "inventory",
 "build_prompt",
 "write_prompt"
 ],
 "public_classes": [],
 "imports": [
 "__future__",
 "datetime",
 "json",
 "logging",
 "pathlib",
 "typing"
 ],
 "tests": [
 {
 "path": "/home/oem/Desktop/LongevityCommon/AIM/AI/tests/test_self_diagnostic.py",
 "loc": 194,
 "test_count": 15
 }
 ]
 }
 ],
 "agents_imports": [],
 "direction_rule": {
 "clean": true,
 "violations": []
 }
}
```

---

## Instructions to the auditing model

1. Read the inventory JSON above first. Treat it as ground truth — do not rescan the filesystem yourself.
2. Then read every numbered phase below and produce a single markdown report covering ALL 9 phases.
3. Return your report in the exact section order. Each finding must reference `path:line` from the inventory. Inventions (non-existent files, fictional functions) auto-fail the report at L_VERIFIABILITY.
4. Run in adversarial mode: your goal is to FIND defects, not to confirm health. If a phase produces zero findings, lower your threshold and try again before declaring it clean.
5. End with the aggregate summary block (totals + grade) per the rubric in the prompt body.

---

# AIM/AI — Self-Diagnostic Prompt v1.0

**Назначение:** запустить максимально глубокую и беспощадную
самодиагностику AI-подпроекта (`~/Desktop/LongevityCommon/AIM/AI/` плюс
зависимости из `agents/`). Prompt разделён на 9 фаз; каждая фаза
обязательна, имеет measurable deliverable, и закрыта L_VERIFIABILITY
gate (никаких выдуманных PMID/DOI/имён файлов/строк кода).

**Аудитория:** Claude / DeepSeek-V4-pro / Gemini 2.5 Pro / Sonnet — любая
модель, способная читать ≥30K context и держать многошаговую логику.

**Output format:** один markdown отчёт `~/Desktop/LongevityCommon/AIM/AI/artifacts/self_diag_<YYYY-MM-DD>.md`
со всеми 9 секциями, каждая с findings + severity + actionable fix.

---

## Метаправила (применяются ко всем фазам)

1. **Никаких "вероятно", "обычно", "должно работать".** Каждая фраза —
 утверждение, которое можно проверить на коде. Нет проверки = строка
 удаляется.
2. **Привязка к строкам.** Каждый baseline-finding ссылается на
 `path:line` или `module:fn`. Нет ссылки = finding не считается.
3. **Adversarial mode по умолчанию.** Цель — НАЙТИ дефект, а не
 подтвердить, что всё хорошо. Если фаза заканчивается без findings —
 повторить с понижением порога подозрений.
4. **Severity scale:** `crit` (роняет prod / portability / privacy),
 `high` (rotts within month), `med` (technical debt, потеря readability),
 `low` (косметика / документация).
5. **No silent retries.** Если фаза не может завершиться (impossible
 to read file, missing dep), записать это явно как `BLOCKER` и
 продолжить остальные фазы. Финальный отчёт всегда полный.

---

## Phase 0 — Surface scan & inventory

**Цель:** построить ground-truth список того, ЧТО мы аудируем.
Без этой опоры остальные фазы плавают.

**Действия:**

1. Прочитать `AI/CLAUDE.md` (scope + правила) и `AI/README.md`.
2. Для каждого `*.py` под `AI/ai/`:
 - имя модуля, путь, размер (LoC), последняя дата модификации
 - публичные функции / классы (через `agents.module_registry`
 или AST вручную)
 - imports (особо: что приходит из `agents/`)
 - наличие тестов в `AI/tests/test_<module>.py` (yes/no, count)
3. Для каждого `agents/*.py`, на которое `AI/` опирается, тот же
 inventory.
4. Проверить **direction-rule** из CLAUDE.md: `agents/ ↛ AI/`. Любой
 импорт `from AI...` или `import AI` внутри `agents/` или `scripts/`
 — это **CRIT** finding ("dependency leak").

**Deliverable:** таблица `module | LoC | tests | imports_from_agents`,
плюс boolean флаг `direction_rule_clean`.

---

## Phase 1 — Algorithmic correctness (per module)

**Для каждого модуля в `AI/ai/`** (S8 eval_synthesiser, S9
distillation_tracker, S10 reflexion_cluster, S11 gap_detector,
будущие):

**Действия:**

1. Прочитать docstring + код целиком.
2. Восстановить **invariants** — что модуль обещает.
3. Для каждого invariant найти КОНТР-кейс: вход, который invariant
 нарушает. Cases ≥3 на модуль:
 - boundary inputs (empty, single-element, very long)
 - encoding edge cases (mixed unicode, NFC vs NFD)
 - timing edge cases (timestamp at exactly the cutoff)
 - concurrency (если модуль stateful — что если две цепочки одновременно)
4. Сопоставить контр-кейсы с существующими тестами:
 `AI/tests/test_<module>.py`. Какие НЕ покрыты?
5. Прогнать каждый существующий test случайно дважды —
 non-determinism = **CRIT**.

**Deliverable:** per-module список:
- `invariants:` — явный bullet list
- `failing_or_uncovered_cases:` — каждое с входом и ожидаемым output
- `recommended_test_additions:` — точные тесты для добавления

**Severity rule:** uncovered boundary в публичной функции с side-effect
(write to disk / DB) = `high`; pure function uncovered = `med`.

---

## Phase 2 — Logic / control-flow

**Цель:** найти неразумные ветки, dead code, недостижимые else.

**Действия:**

1. Для каждого модуля построить call graph (по AST или мысленно):
 `entrypoint → fn1 → fn2 → ...`.
2. Найти **dead branches**: `if cond: ... else:` где else никогда не
 достигается на наших входах.
3. Найти **silent failure paths**: try/except без re-raise и без
 logging.warning ниже level=DEBUG.
4. Найти **non-idempotent side effects**: вызов A.B.A производит
 разный результат от первого A.B.
5. Проверить **exit codes**: каждый `_main` должен возвращать 0/1/2
 осмысленно.

**Deliverable:** per-module список с привязкой к строкам:
- `dead_branch: <file>:<line>` + объяснение
- `silent_failure: <file>:<line>`
- `non_idempotent: <fn>(<args>)` + reproducer

---

## Phase 3 — Type / data-shape integrity

**Цель:** найти ситуации, когда функция получает / возвращает данные не
той формы, на которую полагаются последующие шаги.

**Действия:**

1. Для каждой публичной фукции с return type — проверить, действительно
 ли все return-paths соответствуют этому типу. Особо: `Optional[...]`
 возвращающие None в одном branch и dataclass в другом — учесть это.
2. Для `dataclasses` — проверить, что `__post_init__` (если есть)
 не противоречит `from_dict` / load YAML.
3. Для функций принимающих `Iterable[X]` — что если передать generator
 и потребить его дважды? (anti-pattern для S8/S10/S11 которые читают
 findings + reflexions последовательно.)
4. Для всех JSONL writers — что если пишем dict с не-JSON-serialisable
 value (datetime, set, Path)? Падение или silent corruption?

**Deliverable:**
- список несоответствий (`fn` → expected → actually)
- recommended `assert isinstance(...)` или TypedDict / Protocol

---

## Phase 4 — Code quality (без мнения, только метрики)

**Действия:**

1. Cyclomatic complexity (CC) per function. Use radon или ручной
 подсчёт. Любая fn с CC ≥ 10 = `med`. CC ≥ 15 = `high`.
2. **Duplication:** найти 8+-строчные блоки, появляющиеся ≥2 раза.
3. **Naming consistency:** функции в одном модуле должны следовать
 одному стилю (`snake_case`); смесь = `low`.
4. **Docstrings:** публичные функции без docstring = `low`.
5. **Magic numbers:** literal константы > 1 раза в коде = вынести в
 `const = ...`.

**Deliverable:** одна таблица с колонками
`module | function | cc | dup_block | missing_docstring | magic_count`,
отфильтрованная по `cc >= 10 OR dup_block OR missing_docstring`.

---

## Phase 5 — Integration & dependency surface

**Цель:** убедиться, что AI/ → agents/ зависимости не устаревают.

**Действия:**

1. Каждый импорт из `agents.*` в `AI/ai/*` — проверить, что в
 `agents/<module>.py` действительно есть символ. Сломанный импорт
 = **CRIT**.
2. Каждая упомянутая в коде функция из `agents.*` (через
 `from agents.X import f`) — проверить совместимость сигнатуры.
 Если `agents.X.f(a, b, c)` ожидает 3 аргумента, а AI вызывает
 `agents.X.f(a, b)` — **CRIT**.
3. Reverse: убедиться, что `agents/` НЕ импортирует из `AI/` —
 формальная проверка direction-rule.
4. Cross-check на `agents.module_registry.registry` — каждый модуль,
 на который ссылается AI/, должен быть зарегистрирован там.

**Deliverable:**
- `broken_imports:` (если есть)
- `signature_mismatches:` (если есть)
- `direction_rule_violations:` (must be empty)

---

## Phase 6 — Test suite quality

**Цель:** найти тесты-зомби (ничего не проверяют) и пропуски.

**Действия:**

1. Для каждого `AI/tests/test_*.py`:
 - **Coverage:** % строк модуля, прокрытых тестами. <60% = `med`.
 - **Negative paths:** есть ли тесты на `pytest.raises(...)`?
 Отсутствие = `med` для модулей с user-facing API.
 - **Determinism:** тест использует `dt.date.today` без monkeypatch?
 Тест зависит от текущего timezone? Тест читает реальный
 `~/.cache/aim/`? Любой = `high`.
 - **Mocking depth:** если тест прокидывает stub для `_internal`,
 это запах — лучше тестировать публичный API.
2. Прогнать тесты с `pytest -q --tb=no -p no:cacheprovider --basetemp=tmp`
 дважды подряд. Любые flake = `crit`.
3. Sanity: тест файл существует, но `class Test*` пуст или `def test_*`
 ничего не assert'ит = `med`.

**Deliverable:** per-test-file:
- `coverage: <pct>`
- `negative_paths: <bool>`
- `flaky: <bool>`
- `dead_tests: list of names`

---

## Phase 7 — Safety / privacy / verifiability

Эта фаза — критичная. Любой finding ≥ `high` блокирует merge.

**Действия:**

1. **L_PRIVACY:** ни один модуль AI/ не должен читать `Patients/`.
 `grep -r "Patients" AI/` — ожидаемый результат пустой (упоминания
 допустимы только в комментариях).
2. **L_VERIFIABILITY:** все строки, генерируемые модулем S8 для eval
 cases, не содержат фабрикованных PMID/DOI. Проверить через
 `agents.citation_guard.verify(strict=True)` на всех файлах в
 `AI/cases/auto_*.yaml`.
3. **No outbound network without explicit gate.** AI-модули НЕ должны
 делать `httpx.get(...)` к внешним сервисам без `_gate_external` /
 notify cooldown. Сейчас S9 потенциально гоняет model-runner — это
 ОК, но runner должен прийти от caller, а не быть hard-coded внутри
 модуля.
4. **Bash sandbox:** AI-модули не запускают bash/subprocess для
 произвольных команд. Допускается только `git worktree` через
 `agents.worktree`.
5. **Secrets / env:** ни один AI-модуль не читает `~/.aim_env`,
 `~/.ssh/`, или `~/.aws/`. Проверить через `agents.citation_linter`
 подобный grep.

**Deliverable:**
- `patient_path_leaks:` (must be empty)
- `unverified_emit:` (must be empty)
- `unsanctioned_network:` (each entry = file:line + recommended gate)
- `bash_subprocess:` (if any — re-route through worktree)
- `secret_path_reads:` (must be empty)

---

## Phase 8 — Closed-loop signal integrity

**Цель:** убедиться, что 4 модуля AI образуют РАБОТАЮЩУЮ петлю
обратной связи, а не 4 независимых утилиты.

**Действия:**

1. Симулировать реальный цикл:
 - feed `agents.pattern_miner.mine` фейковые findings (5 sequential_pair, 3 tool_failure_rate, 2 slow_tool)
 - запустить `S8.synthesise(pattern_findings=findings, dry_run=True)`. Сколько кейсов?
 - feed reflexion-like notes в `S10.cluster(...)`. Сколько кластеров?
 - feed `surrenders=...` в `S11.gaps(...)`. Сколько gaps?
 - запустить `S9.run_tier(stub_runner)` против сгенерированных в S8 кейсов.
2. Зафиксировать **end-to-end время** этого цикла (s).
3. Проверить, что **vocabulary совпадает**: ID ключей, имена tier'ов,
 case ID prefix-ы — единый namespace? `auto-rfx-*` / `auto-pair-*` /
 `auto-fail-*` — соответствует ли prefix реальному источнику?
4. Проверить **idempotency:** повторный запуск всего цикла на одних и
 тех же входах не должен порождать новые case ID или дубли в БД.

**Deliverable:**
- `loop_e2e_seconds: <number>`
- `loop_outputs_per_phase: {S8:n, S10:n, S11:n, S9:n}`
- `idempotency: <bool>`
- `vocabulary_aligned: <bool>` + объяснение, если нет

---

## Phase 9 — Failure-mode brainstorm

**Цель:** проактивно представить как AI/ может сломаться через 3 / 30 /
180 дней.

**Действия:** для каждого scenario написать (a) вероятность, (b) impact,
(c) cheapest mitigation.

**Сценарии (минимум):**
1. `agents.pattern_miner` API меняется (например, `Finding.sample`
 становится `Finding.detail`).
2. `agents.reflexion._store_dir` исчезает (текущая реализация
 зависит от приватной функции).
3. SQLite `eval_runs.db` коррумпируется (write at SIGKILL during
 cron).
4. User вручную удаляет `feedback_*.md` массово → S10 cluster станет
 пустым → daily digest перестанет surface improvements.
5. Модель runner для S9 возвращает `None` или валит exception →
 `run_all_tiers` падает на середине.
6. Crossref / PubMed недоступны 24+ часа → `citation_linter` /
 `own_pubs_tracker` начинают флагать всё подряд → digest шумит.
7. Двое cron timer'ов перекрываются (auto_eval + weekly_digest на
 воскресенье) — что происходит с SQLite write contention?
8. Patient privacy leak: AI-experiment случайно индексирует Patients/
 через `memory_index` (если кто-то расширит scope без awareness).

**Deliverable:** таблица `scenario | prob | impact | mitigation`.

---

## Aggregate summary (после всех 9 фаз)

В конце отчёта — agg block:

```
totals:
 crit: N
 high: N
 med: N
 low: N
priority_actions: [top-5 crit/high с одностраничным action plan]
overall_grade: A | B | C | D | F
```

**Grading rubric:**
- A: 0 crit, ≤2 high
- B: 0 crit, ≤5 high
- C: 0 crit, ≤10 high OR 1 crit (medical/safety not implicated)
- D: ≥1 crit с medical/safety implication
- F: ≥3 crit OR direction-rule violation OR patient_path_leak

---

## Запуск (вручную)

```bash
cd ~/Desktop/LongevityCommon/AIM
~/Desktop/LongevityCommon/AIM/venv/bin/python -m AI.ai.eval_synthesiser --dry-run
~/Desktop/LongevityCommon/AIM/venv/bin/python -m pytest AI/tests/ -q
# затем скопировать этот prompt в DeepSeek / Claude и попросить
# выдать заполненный отчёт по 9 фазам.
```

## Запуск (через генератор)

```bash
~/Desktop/LongevityCommon/AIM/venv/bin/python -m AI.ai.self_diagnostic
# (модуль будет добавлен в SD2 — см. roadmap)
```

---

## Версии этого prompt'а

- **v1.0** 2026-05-03 — initial 9-phase scaffold (S8/S9/S10/S11 only).
- **v1.1** (planned, после S6 self_modify) — добавить Phase 10:
 «Self-modification audit trail» — что AI пыталась изменить в свои
 собственных файлах за last 4 weeks.
