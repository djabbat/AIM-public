# REMINDER.md — AIM v7.0

**Назначение:** напоминания, которые должны срабатывать **на старте каждой
сессии** разработки AIM. Это короткий чеклист, не архив. Конкретные
действия — `STRATEGY.md` P0/P1.

**Создан:** 2026-05-07.
**Convention:** при добавлении нового напоминания — короткая 1-2-строчная
формулировка + ссылка на источник истины (если есть).

---

## Каждую сессию (BLOCKING)

1. **Прочитать `THEORY.md` § 1-5** — особенно если меняется kernel или
 PAM-13 logic. Immutable части править нельзя без явной команды.

2. **Прочитать `STRATEGY.md` P1** — текущий 5-недельный фокус. Не
 распыляться на P2-P3 пока P1 не закрыт.

3. **Проверить `MEMORY.md`** — активные вопросы, которые могли застрять.
 Закрыть expired или назначить owner+дату.

4. **`bash scripts/test_all.sh --quick`** перед любым merge → должно быть
 `ALL 3 BLOCKS PASS`. Если красно — не двигаться вперёд.

## При любом коде / изменении

5. **Patients/ неприкосновенны** — не читать, не изменять, не коммитить
 без явной команды (rule MEMORY-2).

6. **LLM только через `llm.py`** (rule MEMORY-1). Прямые `from openai
 import OpenAI` в `agents/*` запрещены. Известные нарушения:
 `agents/telegram_extras.py:92`, `agents/speculative.py:46`,
 `agents/voice.py:80` — STRATEGY P2-5.

7. **STACK rule** — новый код = Rust + Phoenix. Python только для
 legacy OCR/PDF/WhatsApp (`STACK.md` исключения). При сомнении — спросить.

8. **Kernel laws (`agents/kernel_legacy.py`, `crates/aim-kernel`) —
 immutable без явной команды** (`feedback_no_edit_asimov_laws`). Тесты
 добавлять можно, бесshield пороги/наборы — нельзя.

9. **Меню CLI/GUI — править ОБА файла** (`medical_system.py` +
 `aim_gui.py`) + ключи в `i18n.py` для всех 9 языков (rule MEMORY-4,5).

## При git-операциях

10. **`git push` спрашивать** private (`djabbat/AIM`) или public
 (`djabbat/AIM-public`)? Public **исключает**: `CONCEPT.md`,
 `THEORY.md`, `CLAUDE.md`, `TODO.md`, `PARAMETERS.md`, `STRATEGY.md`,
 `Patients/` (rule MEMORY-6, обновлено 2026-05-07).

11. **Никаких `--no-verify`** — pre-commit hooks существуют, фейл
 разбирать, не bypassить.

## При работе с DeepSeek / любым LLM

12. **Citations НЕ галлюцинируем.** `feedback_deepseek_no_citations` —
 DeepSeek фабрикует DOI/PMID. Любой PMID/DOI в emit_text проходит
 `tools.literature.enforce_citations(strict)` или закон
 `L_VERIFIABILITY` падает.

13. **Reference verification scope** (`feedback_verify_references_scope`):
 проверять только когда ссылка идёт в `KNOWLEDGE.md` / статью /
 grant. Внутренний доклад — не обязательно.

## При работе с пациентом

14. **L_AGENCY:** для пациента с PAM ≥ 2 любое clinical action
 (treatment / lifestyle / regimen) **должно** быть co-designed
 (вызов `aim-codesign record consulted|agreed|modified|..`) или
 `decide` вернёт `KernelViolation`.

15. **Patient folder format:** `SURNAME_NAME_YYYY_MM_DD/` где `YYYY_MM_DD`
 = **дата рождения** (не дата создания, не дата визита). При
 неизвестной ДР — placeholder `2000_01_01` (sentinel). См. CLAUDE.md.

## Известные long-running проблемы

16. **AI/tests/* поломаны** после Phase 9 — STRATEGY P1-2. Регрессия
 цепляет только cornerstone subset.

17. **`web/api.py` 772 LoC FastAPI** = STACK violation. STRATEGY P2-4.

---

## Когда забыл, что делать

→ открой `STRATEGY.md` § "Приоритеты" → бери top P1 пункт.
