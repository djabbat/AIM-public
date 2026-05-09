# AIM Onboarding — guided project / patient creation

Дата: 2026-05-08 
Статус: DRAFT (часть AIM_FS v11 SPEC, post-MVP §B "guided onboarding")

## Цель

Заменить "пустой scaffold + AI заполнит позже" на интерактивный опрос
пользователя при создании любой сущности уровня 2 / 3:

| Тип | Кто инициирует | Что создаётся |
|-----|----------------|---------------|
| User-defined project (Tier 2) | user | 11-file core + первичные `feedback_v1` записи |
| Patient (Tier 3.a) | doctor | `Patients/<key>/` + `ANAMNESIS.md` + initial visit + consent |
| Self-dev proposal (Tier 3.c) | AIM (с user approval) | proposal в `_self_dev/proposals/pending/` |
| Service folder (Tier 3.b) | AIM | без вопросов — рутина |

## Формат шаблона (`templates/<name>.yaml`)

```yaml
id: research_project
title: "Создание исследовательского проекта"
version: 1
intent: "User описал идею; AIM собирает структурированные ответы и
 генерирует 11-file core + memory-записи."

# Вопросы. Идут последовательно, пропускаются по depends_on.
questions:
 - id: slug
 prompt: "Slug проекта (snake_case, без пробелов)"
 type: text
 required: true
 validate_regex: '^[a-z0-9_]+$'

 - id: title
 prompt: "Полное название"
 type: text
 required: true

 - id: description
 prompt: "Опиши проект 1-2 фразами (для CONCEPT.md)"
 type: text
 required: true
 multiline: true

 - id: domain
 prompt: "Область"
 type: choice
 options: [biology, software, clinical, theoretical, mixed]

 - id: stack
 prompt: "Стек — что используем (если код)"
 type: multichoice
 options: [rust, phoenix, python_legacy, none]
 depends_on:
 - field: domain
 not_in: [theoretical, clinical]

 - id: parameters
 prompt: "Перечисли ключевые параметры (если есть): name=value, по строке"
 type: list
 multiline: true

 - id: knowledge_anchor_pmids
 prompt: "PMID или DOI верифицированных публикаций-якорей (опц., через запятую)"
 type: list
 optional: true
 validate_regex: '^[\d., A-Za-z./\-:]*$'

 - id: feedback_rules
 prompt: "Правила работы для AI (по строке): 'Не делать X', 'Всегда Y'"
 type: list
 optional: true
 multiline: true

# Какие файлы создать в `<aim_root>/users/<uid>/projects/<slug>/`.
# Тело — Tera-style {{placeholder}}.
file_targets:
 - path: CONCEPT.md
 template: |
 # {{title}}

 **Slug:** `{{slug}}`
 **Domain:** {{domain}}
 **Created:** {{created_at}}

 ## Описание

 {{description}}

 {% if stack %}
 ## Стек

 {{stack}}
 {% endif %}

 - path: THEORY.md
 template: |
 # {{title}} — Theory

 <!-- immutable; теоретическое обоснование -->
 <!-- Заполнить вручную или через follow-up onboarding-step -->

 - path: PARAMETERS.md
 template: |
 # {{title}} — Parameters

 {% if parameters %}
 | name | value |
 |------|-------|
 {% for kv in parameters %}
 | {{kv.name}} | {{kv.value}} |
 {% endfor %}
 {% else %}
 _Параметры пока не определены._
 {% endif %}

 - path: KNOWLEDGE.md
 template: |
 # {{title}} — Knowledge

 {% if knowledge_anchor_pmids %}
 Anchor publications:
 {% for ref in knowledge_anchor_pmids %}
 - {{ref}} <!-- TODO: verify через PubMed/Crossref -->
 {% endfor %}
 {% else %}
 _Якорные публикации не указаны при создании._
 {% endif %}

 - path: README.md
 template: "# {{title}}\n\n{{description}}\n"

 - path: STATE.md
 template: |
 # State

 status: draft
 created_at: {{created_at}}
 created_by: {{user_id}}

 - path: TODO.md
 template: "# TODO\n\n- [ ] Заполнить THEORY.md\n- [ ] Уточнить PARAMETERS.md\n- [ ] Добавить EVIDENCE\n"

 - path: UPGRADE.md
 template: "# Upgrade plan\n\n_Будет заполнено по мере развития проекта._\n"

 - path: MAP.md
 template: "# Project file map\n\nСтандартный 11-file core; деталь при необходимости.\n"

 - path: CLAUDE.md
 template: |
 # Instructions for AI agents

 Project **{{title}}** ({{slug}}). Domain: {{domain}}.

 Source of truth: `CONCEPT.md`.

 - path: EVIDENCE.md
 template: "# Evidence base\n\n_Empty at creation; populate after literature review._\n"

# Какие memory-записи (через AIM_FS propose) предложить как pending в inbox.
memory_proposals:
 - schema: feedback_v1
 title_template: "Project rule: {{rule}}"
 body_template: |
 **Why:** Specified during onboarding for project {{slug}}.
 **How to apply:** When working on `{{slug}}` files.
 tags: [onboarding, project_rule]
 scope_project_ids: ["{{slug}}"]
 iterate_over: feedback_rules

 - schema: project_state_v1
 title_template: "Project {{slug}} created"
 body_template: |
 Project `{{slug}}` ({{title}}) created on {{created_at}} via guided
 onboarding template `research_project`. Domain: {{domain}}.
 tags: [project, onboarding]
```

## CLI flow

```
$ aim-onboard --template research_project --tenant-id <uuid> --aim-root ~/.aim_fs

? Slug проекта (snake_case): zheleznov_hsc_simulator
? Полное название: HSC Simulator (Илья Железнов)
? Опиши проект 1-2 фразами:
> Python симулятор гемопоэза с центриольным наследованием…
>.
? Область [1=biology …]: 1
? Стек (множественный выбор) [a=rust,b=phoenix,…]: a c
? Параметры (name=value по строке, пустая строка — конец):
> alpha=0.0082
> beta=0.005
>
? PMID/DOI якоря (опц., через запятую):
> 36583780, 28792876
? Правила для AI (по строке, пустая — конец):
> Self-citation ≤ 15 % при публикации.
> Проверять PMID через PubMed.
>

→ Scaffold projects/zheleznov_hsc_simulator/ … done (11 files).
→ Propose 2 feedback_v1 entries to inbox … done.
→ Propose 1 project_state_v1 entry … done (auto-approved per policy).
```

## Patient registration template (отдельный)

`templates/patient.yaml` — короткий поток:

| Question | Type | Stored in |
|----------|------|-----------|
| Surname | text | identity.toml |
| Name | text | identity.toml |
| DOB (YYYY_MM_DD) | date | identity.toml + folder name |
| Phone | text | identity.toml |
| Allergies | list | ANAMNESIS.md |
| Chronic conditions | list | ANAMNESIS.md |
| Current medications| list | ANAMNESIS.md |
| Consent: TG comms | bool | consent.json |
| Consent: data store| bool | consent.json |
| Initial complaint | text | visits/<ts>/intake.md |

Создаётся в `users/<doctor_id>/patients/<surname>_<name>_<dob>/` с
`_inbox/` для AI-генерируемых diagnoses/recipes (см. AIM_FS SPEC §3.a).

## Self-dev proposal template (для AI)

`templates/self_dev_proposal.yaml` — заполняется не пользователем,
а AIM-агентом, но проходит через approval queue в `_self_dev/proposals/pending/`.

Поля per SPEC §3.c: type, priority, rationale, blast_radius, rollback,
sections (Что предлагаю / Доказательства / Риски).

## Реализация

`rust-core/crates/aim-onboarding/`:

- `template.rs` — `Template`, `Question`, `FileTarget`, `MemoryProposal`
- `session.rs` — `Session`, `Answers`, walking through questions
- `cli.rs` — terminal interview (rustyline)
- `render.rs` — простой Tera-style placeholder rendering (без полного Tera dep)
- `bin/aim_onboard.rs` — CLI entry
- Integration: `aim_fs.scaffold_project` + `aim_fs.propose(..)` per question/proposal

`apps/aim_web/lib/aim_web_web/live/onboard_live.ex` — multi-step LiveView,
шаги соответствуют questions массиву в template.
