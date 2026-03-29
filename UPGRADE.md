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
**Status:** [ ] proposed

Current AIM architecture lacks a push notification layer for mobile clients. Implementing a lightweight notification broker (e.g., Firebase Cloud Messaging or a self-hosted alternative like ntfy) would allow timely delivery of lab result alerts, appointment reminders, and critical diagnosis flags to patients and clinicians. Priority should be given to offline-first queuing so notifications are not lost when connectivity is intermittent.

---

## [2026-03-29] AI Model Upgrade: llama3.2 → Newer Foundation Models
**Source:** Rapid model release cadence (Llama 3.3, Mistral Medical, BioMistral); internal performance review
**Status:** [ ] proposed

The current default model (llama3.2) should be evaluated against newer alternatives including Llama 3.3 70B, BioMistral-7B, and OpenBioLLM. A benchmarking harness using real (de-identified) AIM patient cases should be built to compare diagnostic accuracy, multilingual output quality (RU/EN/KA/KZ), and inference speed on local hardware. DeepSeek API (`deepseek-reasoner`) can serve as a high-accuracy reference baseline during evaluation.

---

## [2026-03-29] FHIR R4 Compliance for Medical Data Export
**Source:** International interoperability standards; potential cross-border patient referrals
**Status:** [ ] proposed

Introducing FHIR R4-compliant export endpoints would allow AIM patient records to be shared with partner clinics, EHR systems, and research platforms without custom adapters. A minimal implementation would cover Patient, Observation (lab results), DiagnosticReport, and MedicationRequest resources. This also positions AIM favorably for any future regulatory certification in Georgia or Kazakhstan.

---

## [2026-03-29] Multilingual Patient-Facing Reports
**Source:** AIM multilingual architecture (RU/EN/KA/KZ); patient literacy considerations
**Status:** [ ] proposed

AI-generated diagnostic summaries and treatment plans are currently produced in the language of the input prompt, without a structured translation pipeline. Adding a dedicated report-rendering module that calls DeepSeek for localization into all four supported languages would ensure every patient receives a readable, culturally appropriate summary. Templates should be medically reviewed once and reused to minimize per-report LLM cost.

---

## [2026-03-29] Integration with External Laboratory Information Systems (LIS)
**Source:** Clinical workflow analysis; redundant manual data entry observed in lab_parser.py pipeline
**Status:** [ ] proposed

The current pipeline requires manual upload of PDF lab reports. Establishing HL7 v2.x or FHIR-based inbound feeds from partner laboratories (e.g., Synevo Georgia, Invitro Kazakhstan) would eliminate transcription errors and reduce turnaround time from result receipt to AI analysis. A polling adapter with credential vault (encrypted via AIM's existing config layer) should be implemented as the first step.
