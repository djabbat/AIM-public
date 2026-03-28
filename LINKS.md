# AIM v6.0 — LINKS (Экосистемные связи)

---

## AIM ↔ CDATA

**Путь:** `~/Desktop/CDATA/`
**GitHub:** `djabbat/CDATA-private` / `djabbat/CDATA-public`

| Тип связи | Описание |
|-----------|---------|
| Ze-теория | CDATA содержит полную теорию Ze. AIM использует для диагностики |
| Клинические данные | CDATA — база клинических исходов; AIM обучается на них |
| Публикации | Статьи из CDATA цитируются в AIM-документах |
| Horizon | `CDATA/Horizon/` — Horizon Europe грант; AIM входит в рамки |

**Ключевые файлы CDATA для AIM:**
- `CDATA/Ze-theory/` — теория Ze в медицине
- `CDATA/clinical_data/` — клинические данные (деиндентифицированные)
- Zenodo DOI: https://doi.org/10.5281/zenodo.19174506

---

## AIM ↔ ZeAnastasis

**Путь:** `~/Desktop/ZeAnastasis/`
**Zenodo DOI:** https://doi.org/10.5281/zenodo.19174630

| Тип связи | Описание |
|-----------|---------|
| Ze-терапия | ZeAnastasis содержит протоколы Ze-терапии |
| EEG/HRV данные | Результаты из ZeAnastasis поступают в AIM-диагностику |
| Пациенты | Один и тот же пациент может быть в обеих системах |

**Интеграционные точки:**
- Ze-HRV статус → `diagnosis_engine.py`
- Ze-протоколы → `treatment_recommender.py`

---

## AIM ↔ Regenesis

**Путь:** `~/Desktop/Regenesis/`

| Тип связи | Описание |
|-----------|---------|
| Протоколы | Regenesis содержит регенеративные протоколы |
| Лечение | AIM `treatment_recommender.py` включает Regenesis-протоколы |
| Пациенты | Общие пациенты (регенеративная + интегративная медицина) |

**Интеграция:**
- Regenesis-протоколы импортируются в `treatment_recommender.py`
- AIM отслеживает ответ на Regenesis-лечение

---

## AIM ↔ DrJaba

**Путь:** `~/Desktop/DrJaba/`
**Домен:** `drjaba.com`

| Тип связи | Описание |
|-----------|---------|
| Публичный сайт | drjaba.com — витрина практики |
| Запись пациентов | Через drjaba.com → AIM |
| Блог/публикации | Контент из AIM-знаний → drjaba.com |

**Доменная карта:**
- `drjaba.com` — главный сайт
- `aim.drjaba.com` — AIM веб-интерфейс
- `ze.drjaba.com` — Ze-терапия

---

## AIM ↔ BioSense

**Путь:** `~/Desktop/BioSense/`
**Контекст:** `~/Desktop/BioSense/ze_eeg_validation/results/`

| Тип связи | Описание |
|-----------|---------|
| EEG данные | BioSense собирает EEG → AIM анализирует |
| HRV | Данные HRV → Ze-статус → диагностика |
| Валидация | ze_eeg_validation — валидация Ze-теории |

**Интеграция:**
- BioSense → EEG/HRV → `db.py` (таблица `biosense_readings`)
- `diagnosis_engine.py` использует biosense_readings

---

## AIM ↔ WLRAbastumani

**Описание:** Санаторий Абастумани / Wellness & Longevity Resort

| Тип связи | Описание |
|-----------|---------|
| Тенант | WLRAbastumani — отдельный тенант в AIM multi-tenant |
| Пациенты | Пациенты санатория — в AIM системе |
| Протоколы | Санаторные протоколы → Regenesis → AIM |

**Тенант ID:** `wlr_abastumani` (в production)

---

## AIM ↔ FCLC

**Путь:** `~/Desktop/FCLC/` (ex-FedClinAI)
**Описание:** Федеральная клиническая сеть

| Тип связи | Описание |
|-----------|---------|
| Тенант | FCLC — тенант в AIM (ENTERPRISE план) |
| Сеть клиник | Несколько клиник под одним тенантом |
| Данные | Агрегированные (анонимизированные) данные для аналитики |

**Тенант ID:** `fclc` (в production)

---

## Доменная карта (production)

| Домен | Назначение |
|-------|-----------|
| `drjaba.com` | Сайт практики (DrJaba) |
| `aim.drjaba.com` | AIM веб-интерфейс |
| `ze.drjaba.com` | ZeAnastasis |
| `spellcheckerka.drjaba.com` | SpellCheckerKa |
| `ksystem.drjaba.com` | kSystem лексикон |
| `cdata.drjaba.com` | CDATA портал |
| `space.drjaba.com` | Space упражнения |

---

## Ключевые публикации (self-citation)

1. **PMID 36583780** — Tkemaladze J. *Mol Biol Reports* 2023
   https://pubmed.ncbi.nlm.nih.gov/36583780/

2. **PMID 20480236** — Lezhava T. et al. (incl. Tkemaladze) *Biogerontology* 2011

3. **Zenodo CDATA** — DOI: https://doi.org/10.5281/zenodo.19174506

4. **Zenodo Ze** — DOI: https://doi.org/10.5281/zenodo.19174630

5. **Preprints.org** — DOI: 10.20944/* (любые версии)
