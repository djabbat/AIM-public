# UPGRADE.md — AIM (Assistant of Integrative Medicine)

Suggestions for project development from external analysis, literature, and cross-project review.

**Format:**
```
## [YYYY-MM-DD] Title
**Source:** [what triggered this]
**Status:** [ ] proposed | [✓ approved YYYY-MM-DD] | [✓✓ implemented YYYY-MM-DD]
```

---

## [2026-03-29] Push Notification Optimization for Mobile Clients
**Source:** Cross-project analysis of AIM ecosystem; mobile usage patterns in clinical settings
**Status:** [⏸ отложено — после Фаз 2+5+6]

Peer review (2026-03-30): технически корректно, но преждевременно. Зависимости: JWT/RBAC (Фаза 2), REST API (Фаза 5), Flutter-приложения (Фаза 6). Дополнительно: медицинские данные через FCM требуют GDPR-оценки; рекомендован self-hosted ntfy или метаданные без PHI в payload.

---

## [2026-03-29] AI Model Upgrade: маршрутизация по задаче и языку
**Source:** Rapid model release cadence; internal performance review
**Status:** [✓ approved 2026-03-30] [✓✓ implemented 2026-03-30]

Добавлена маршрутизация модели в `llm.py`: task_type="fast"→deepseek-chat, task_type="reason"/"medical"→deepseek-reasoner. Расширена языковая поддержка до 7 языков (ООН-6 + грузинский): добавлены системные промпты FR/ES/AR/ZH. SUPPORTED_LANGS обновлён в config.py. Ollama/llama3.2 — offline fallback без изменений.

---

## [2026-03-29] FHIR R4 Compliance for Medical Data Export
**Source:** International interoperability standards; potential cross-border patient referrals
**Status:** [⏸ отложено — после Фаз 3+5+7]

Peer review (2026-03-30): нет схемы БД для медданных, нет REST API — экспортировать нечего. Технически корректно; реализовать после завершения медицинских модулей и API-слоя.

---

## [2026-03-29] Multilingual Patient-Facing Reports
**Source:** AIM multilingual architecture; patient literacy considerations
**Status:** [⏸ отложено — после Фазы 3]

Peer review (2026-03-30): нет diagnosis_engine.py/treatment_recommender.py — источника данных для отчётов. Реализовать после Фазы 3. Языки теперь ООН-6 + грузинский (7 языков).

---

## [2026-03-29] Integration with External Laboratory Information Systems (LIS)
**Source:** Clinical workflow analysis; redundant manual data entry in lab_parser.py pipeline
**Status:** [⏸ отложено — после Фазы 3 + партнёрских договорённостей]

Peer review (2026-03-30): нет lab_parser.py, нет схемы для лаб. значений. Synevo Georgia / Invitro Kazakhstan — требуются реальные API-договорённости. Реализовать после Фазы 3.
