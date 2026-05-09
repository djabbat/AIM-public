defmodule AimWeb.AboutLive do
  @moduledoc """
  Comprehensive English description of the AIM system. Static content,
  no Rust binary calls. Route: `/about`.

  Maintained as the single source-of-truth for what AIM is, what it does,
  and how to use it — for clinicians, researchers, and developers.
  Last refresh: 2026-05-07.
  """
  use AimWeb, :live_view

  def mount(_params, _session, socket),
    do: {:ok, assign(socket, :skip_layout_header, false)}

  def render(assigns) do
    ~H"""
    <main class="container about-page">
      <h1>AIM — Assistant of Integrative Medicine</h1>
      <p class="lead">
        AIM is a hybrid medical AI ecosystem that turns the patient
        from a passive data source into an active developmental
        co-manager of their own care. Built in Rust (192 crates) +
        Phoenix LiveView, with strict safety contracts and a
        Patient-Activation-Measure–driven outcome metric instead of
        physician-satisfaction proxies.
      </p>

      <section class="about-section">
        <h2>1. Mission and scope</h2>
        <p>
          AIM is an open-source clinical and longevity-research platform
          designed for a specific theoretical commitment: the patient is
          not an object of intervention but a
          <strong>developmental project</strong>. Every recommendation
          surfaces only after the system has checked that the patient's
          activation level allows it, that the action has been
          co-designed when relevant, and that all citations supporting
          the recommendation actually resolve.
        </p>
        <p>
          The platform is engineered for three audiences:
        </p>
        <ul>
          <li>
            <strong>Clinicians</strong> — diagnostic differentials,
            regimen safety review, lab interpretation, and a
            motivational-interviewing coach loop for non-pharmacological
            care.
          </li>
          <li>
            <strong>Researchers</strong> — auditable Asimov-style
            decision kernel, PAM-13 trajectories per cohort,
            disagreement-zone classifier (Blumenthal-Lee), patient
            co-design event log.
          </li>
          <li>
            <strong>Developers</strong> — 192 Rust crates, 14 Phoenix
            routes, native systemd deployment (no Docker), local-first
            privacy model.
          </li>
        </ul>
      </section>

      <section class="about-section">
        <h2>2. The "Patient as a Project" cornerstone</h2>
        <p>
          AIM is built around a three-level framework, derived from
          Tao et al. (Nat Med 2026, n = 2069 RCT) and the manuscript
          "Patient as a Project" (Tkemaladze 2026,
          <em>Longevity Horizon</em> 2(5), DOI
          <a href="https://doi.org/10.65649/qqwva850">10.65649/qqwva850</a>):
        </p>
        <table class="about-table">
          <thead>
            <tr><th>Level</th><th>Patient role</th><th>AI role</th><th>Status</th></tr>
          </thead>
          <tbody>
            <tr><td>L1</td><td>Object — passive data</td><td>Classifier</td><td>Confirmed</td></tr>
            <tr><td>L2</td><td>Narrator — active info provider</td><td>Facilitator</td><td>Confirmed (RCT)</td></tr>
            <tr><td>L3</td><td>Project — active co-manager</td><td>Developmental agent</td><td>AIM is the validation infrastructure</td></tr>
          </tbody>
        </table>
        <p>
          Primary outcome metric for L3 is <strong>PAM-13 trajectory</strong>
          (Patient Activation Measure, MCID = 5.4 points), <em>not</em>
          physician satisfaction.
        </p>
        <p>
          Four architectural principles enforce this commitment:
        </p>
        <ol>
          <li>
            <strong>Co-design over fine-tuning.</strong> The system
            cannot recommend a treatment for an activated patient
            (PAM-13 ≥ level 2) without an explicit co-design event
            ("agreed", "modified") logged in
            <code>aim-codesign</code>.
          </li>
          <li>
            <strong>Performance-based 4-zone HCI</strong>
            (Blumenthal-Lee). UI friction scales with both AI confidence
            and clinician confidence. When both are confident and
            disagree, the system forces multidisciplinary review
            instead of letting either side rubber-stamp the other.
          </li>
          <li>
            <strong>Developmental ≠ instrumental agency.</strong> The
            coach loop builds patient capacity (motivational
            interviewing OARS pattern) rather than just automating
            clinician tasks.
          </li>
          <li>
            <strong>L_AGENCY law</strong> — a fourth extended kernel
            law sits alongside L_PRIVACY / L_CONSENT /
            L_VERIFIABILITY. It blocks treatment, lifestyle, regimen,
            and behaviour-change actions for activated patients
            without an explicit co-design event.
          </li>
        </ol>
      </section>

      <section class="about-section">
        <h2>3. The decision kernel — Asimov-style safety contract</h2>
        <p>
          Every clinical decision in AIM passes through eight laws,
          implemented in Rust (<code>aim-kernel</code>, 2 105 LoC,
          62 unit tests) and exposed to Python through a PyO3 binding.
          Source-of-truth: <code>rust-core/crates/aim-kernel/src/lib.rs</code>.
        </p>
        <table class="about-table">
          <thead>
            <tr><th>Law</th><th>Function</th><th>Triggers on</th></tr>
          </thead>
          <tbody>
            <tr><td><strong>L0</strong></td><td>Danger signals</td><td>Biohazard / weapon / forge keywords; broad-spectrum ABx for viral indications</td></tr>
            <tr><td><strong>L1</strong></td><td>Patient harm</td><td>Allergy match, contraindicated drug-drug interaction, inaction harm with red flags</td></tr>
            <tr><td><strong>L2</strong></td><td>Physician override</td><td>Action type must match commanded action; hard override never bypasses L0+L1</td></tr>
            <tr><td><strong>L3</strong></td><td>Destructive system mod</td><td><code>system_modification</code> action with <code>destructive: true</code></td></tr>
            <tr><td><strong>L_PRIVACY</strong></td><td>Patient-data egress</td><td>email_send, web_post, git_push_public, telegram_broadcast — blocks payloads containing Patients/ paths, phone, MRN, DoB</td></tr>
            <tr><td><strong>L_CONSENT</strong></td><td>Public blast radius</td><td>email_send, telegram_broadcast, web_publish — requires explicit user_confirmed=true</td></tr>
            <tr><td><strong>L_VERIFIABILITY</strong></td><td>Citation enforcement</td><td>emit_text / write_manuscript / send_letter — blocks unresolvable PMID/DOI</td></tr>
            <tr><td><strong>L_AGENCY</strong></td><td>Developmental agency</td><td>treatment, lifestyle_directive, behavior_change, regimen_change, auto_action — requires patient_codesigned=true for activated patients</td></tr>
          </tbody>
        </table>
        <p>
          The kernel is <strong>immutable</strong>: thresholds and
          action-type sets cannot be loosened without explicit human
          instruction. This rule is enforced at the meta-level via
          <code>CLAUDE.md</code> and a dedicated memory entry,
          preventing AI agents from silently widening safety bypasses.
        </p>
      </section>

      <section class="about-section">
        <h2>4. The L3 cornerstone routes</h2>
        <p>
          The "Patient as a Project" cornerstone is exposed through six
          Phoenix LiveView routes. All UI auto-refreshes every 30 s
          and shells out to the corresponding Rust binary; if the
          binary is missing the page degrades gracefully to an empty
          state with a buildable hint.
        </p>
        <table class="about-table">
          <thead>
            <tr><th>Route</th><th>Purpose</th><th>Backed by</th></tr>
          </thead>
          <tbody>
            <tr><td><a href="/pam">/pam</a></td><td>PAM-13 cohort view: every patient with current activation level (1-4) and latest delta vs MCID/MDC</td><td><code>aim-pam level</code> · <code>aim-pam latest-delta</code></td></tr>
            <tr><td>/pam/:patient_id</td><td>Per-patient PAM-13 trajectory: full JSONL history, score, level evolution</td><td><code>aim-pam history</code></td></tr>
            <tr><td>/codesign/:patient_id</td><td>Co-design event log: consulted / agreed / modified / refused / alternative</td><td><code>aim-codesign events</code></td></tr>
            <tr><td><a href="/disagreement">/disagreement</a></td><td>Interactive Blumenthal-Lee 4-zone classifier — sliders for AI conf + clinician conf + agreement</td><td><code>aim-disagreement classify</code></td></tr>
            <tr><td><a href="/activation">/activation</a></td><td>Cohort funnel: how many patients sit at each PAM-13 level</td><td><code>aim-pam level</code> per patient</td></tr>
            <tr><td>/coaching/:patient_id</td><td>Motivational-interviewing assistant: classify utterance → suggest OARS move</td><td><code>aim-coach classify</code> · <code>aim-coach next-move</code></td></tr>
          </tbody>
        </table>
      </section>

      <section class="about-section">
        <h2>5. Clinical capabilities (L1 + L2)</h2>
        <h3>5.1 Differential diagnosis</h3>
        <p>
          The <code>DiffDiagnosis</code> sub-system provides
          rule-based differential reasoning derived from the
          Vinogradov internal-medicine textbook (7 chapters: chest
          pain, dyspnea/cough/hemoptysis, abdominal pain, jaundice,
          fever of unknown origin, lymphadenopathy/splenomegaly,
          anemia/cytopenias) and Taylor's
          <em>Differential Diagnosis</em>. Symptom intake is
          OCR-parsed, ranked through the kernel, and surfaced with a
          full reasoning trace per differential. The cornerstone
          fields <code>patient_activation_level</code> and
          <code>patient_codesigned</code> are passed through so
          upstream agents can apply L_AGENCY before any treatment
          recommendation.
        </p>
        <h3>5.2 Lab interpretation (CBC syndromal pattern recognition)</h3>
        <p>
          The <code>SSA</code> sub-system digitises a 28-parameter
          complete-blood-count panel into 5 zones (L2/L1/L0/H1/H2)
          per ICSH/NHANES/Wintrobe references, then matches against
          15 paired and 15 triple syndromal patterns
          (anemia microcytic, thrombotic microangiopathy, leuko-erythroblastic
          reaction, etc.). Output is a ranked list of syndromes plus
          red-flag annotations and artifact warnings (cold
          agglutinins, pseudothrombocytopenia). Each pattern has a
          peer-reviewed reference in <code>EVIDENCE.md</code>; LLM is
          never used to generate reference intervals.
        </p>
        <h3>5.3 Drug-drug interaction screen</h3>
        <p>
          A curated database of ≈30 high-impact drug pairs (warfarin
          + NSAID, SSRI + MAOI, dasatinib + quercetin senolytic
          combo, etc.) lives in the <code>aim-interactions</code>
          Rust crate, with severity scored as Contraindicated /
          Major / Moderate / Minor / NoKnown and a peer-reviewed
          source for every flagged pair. The
          <code>aim-regimen-validator</code> wraps this with a
          hard-refusal layer: contraindicated pairs always block;
          major pairs block unless an explicit physician override is
          set; moderate pairs warn.
        </p>
        <h3>5.4 Regimen safety review</h3>
        <p>
          Every doctor-generated treatment passes through
          <code>regimen_validator.annotate()</code>, which appends a
          machine-readable safety footer listing must-drop drugs,
          drugs requiring monitoring, and the applicable
          contraindication / major / moderate findings. The footer
          is part of the audit trail in
          <code>Patients/&lt;id&gt;/AI_LOG.md</code>.
        </p>
      </section>

      <section class="about-section">
        <h2>6. LLM stack and routing</h2>
        <p>
          AIM is multi-LLM by design. The Rust HTTP service
          <code>aim-llm</code> (port 8770) routes every chat call
          through a tier chain that matches the Python-era
          <code>llm.py</code> contract:
        </p>
        <table class="about-table">
          <thead>
            <tr><th>Tier</th><th>Provider chain</th><th>When</th></tr>
          </thead>
          <tbody>
            <tr><td>critical</td><td>Anthropic Claude Opus 4.7 → Gemini 2.5 Pro → DeepSeek-reasoner → Ollama deepseek-r1</td><td>Grants, diagnoses, contracts, anything irreversible</td></tr>
            <tr><td>deep</td><td>DeepSeek-reasoner → Claude Opus → Gemini 2.5 Pro → Ollama deepseek-r1</td><td>Reasoning tasks, analysis, plan synthesis</td></tr>
            <tr><td>long</td><td>DeepSeek-chat (1M ctx) → Gemini 2.5 Pro → Ollama qwen2.5:7b</td><td>Long-context inputs &gt; 30K tokens</td></tr>
            <tr><td>default</td><td>DeepSeek-chat → Gemini Flash → Ollama qwen2.5:7b</td><td>Standard chat / generation</td></tr>
            <tr><td>fast</td><td>Groq llama-3.1-8b-instant → DeepSeek-chat → Ollama qwen2.5:3b</td><td>Triage, classification, ack</td></tr>
          </tbody>
        </table>
        <p>
          Each provider is gated by a per-provider circuit breaker
          (DeepSeek 5/30 s, Groq 3/30 s, Anthropic 3/60 s, Gemini
          3/120 s, Ollama 2/15 s) and a token-bucket rate limiter
          (RPM/burst tuned per provider's free-tier and SLA limits).
          When a provider's circuit is open, the chain skips it
          rather than piling on more failures. A response cache
          keyed on prompt hash + model name avoids duplicate spend
          on identical prompts.
        </p>
        <p>
          A Python HTTP shim (<code>agents/llm_client.py</code>) lets
          legacy Python agents talk to the Rust service via
          <code>AIM_LLM_HTTP_URL</code> opt-in. The legacy Python
          provider chain in <code>llm.py</code> remains as an
          unconditional fallback for the case where the service is
          unreachable.
        </p>
      </section>

      <section class="about-section">
        <h2>7. Privacy and multi-user model</h2>
        <h3>7.1 Local-first by default</h3>
        <p>
          Patient data lives on the local node only.
          <code>L_PRIVACY</code> blocks any payload that contains
          <code>Patients/</code> paths, phone-number patterns,
          birthdate-like patterns, or MRN/passport identifiers from
          being sent to external endpoints (email, Telegram, public
          git, third-party APIs) unless the calling context
          explicitly sets <code>privacy_consent=true</code>.
        </p>
        <h3>7.2 Hub / Node split</h3>
        <p>
          AIM runs in two roles via the <code>AIM_ROLE</code> env
          var:
        </p>
        <ul>
          <li>
            <strong>Hub</strong> (one instance): manages users,
            JWT-signed API tokens, per-user audit log, and 6-digit
            <code>/link</code> codes for Telegram bot binding. The
            hub never sees patient data.
          </li>
          <li>
            <strong>Node</strong> (one per user, default mode):
            hosts the chat loop, patient memory, lab pipeline, LLM
            routing. Validates its <code>AIM_USER_TOKEN</code>
            against the hub on startup with a 24-hour cache and a
            7-day offline grace period.
          </li>
        </ul>
        <p>
          API keys live in <code>~/.aim_env</code> (file mode 600).
          No keys are committed to git; no keys are hard-coded in
          source.
        </p>
      </section>

      <section class="about-section">
        <h2>8. Audit trail and reproducibility</h2>
        <p>
          Every decision the kernel approves writes to two parallel
          stores:
        </p>
        <ul>
          <li>
            <code>ai_events</code> SQLite table — WAL-mode, indexed
            on patient_id and ts, with archive-tier migration for
            rows older than 90 days. Columns include
            <code>alternatives_json</code> (every alternative the
            kernel saw), <code>chosen_id</code>,
            <code>laws_json</code> (L0-L3 verdict + reasons), and
            since 2026-05-07 a new <code>extended_json</code> column
            capturing the L_PRIVACY / L_CONSENT / L_VERIFIABILITY /
            L_AGENCY result.
          </li>
          <li>
            Per-patient <code>Patients/&lt;id&gt;/AI_LOG.md</code> —
            human-greppable Markdown with one section per decision,
            including the impedance trajectory, the chosen action,
            the override (if any), and a per-extended-law tick mark
            (✅/❌) plus any flagged reasons. Designed for clinician
            review and post-hoc auditing.
          </li>
        </ul>
        <p>
          The combined trail makes every recommendation
          reproducible: the inputs, the kernel verdict, the
          alternatives that were rejected, and the cite-checked text
          that left the system are all reconstructible months later.
        </p>
      </section>

      <section class="about-section">
        <h2>9. Architecture overview</h2>
        <h3>9.1 Stack rule</h3>
        <p>
          New code: <strong>Rust</strong> for backend, algorithms,
          agents, CLI, and system services; <strong>Phoenix
          LiveView</strong> for frontend, dashboards, UI. Python
          stays only for legacy where no mature Rust equivalent
          exists yet (OCR/PDF/WhatsApp via tesseract/rapidocr/pymupdf,
          Gmail API, customtkinter desktop GUI, faster-whisper
          speech). No Docker — everything ships as a native systemd
          unit.
        </p>
        <h3>9.2 Workspace layout</h3>
        <ul>
          <li>
            <code>rust-core/crates/</code> — 192 Rust crates. Cores:
            <code>aim-kernel</code> (decision kernel, 2 105 LoC),
            <code>aim-patient-memory</code> (lifecycle + MEMORY.md
            schema, 1 481 LoC),
            <code>aim-llm</code> (HTTP router, 716 LoC, 5 providers).
            Cornerstone:
            <code>aim-pam</code> · <code>aim-disagreement</code> ·
            <code>aim-codesign</code> · <code>aim-coach</code>.
            Lifecycle: <code>aim-project-owner</code> ·
            <code>aim-patient-owner</code> ·
            <code>aim-experiment-owner</code>.
          </li>
          <li>
            <code>phoenix-umbrella/</code> — 4-app umbrella:
            <code>aim_web</code> (LiveView frontend),
            <code>aim_orchestrator</code> (RPC mux to Rust services),
            <code>aim_memory</code> (Ecto SQLite wrapper),
            <code>aim_gateway</code>.
          </li>
          <li>
            <code>agents/</code> — Python agents, increasingly thin
            shims over Rust binaries (Phase 7 + Phase 8 ports
            completed).
            <code>kernel.py</code> · <code>pam_tracker.py</code> ·
            <code>codesign_log.py</code> ·
            <code>automation_bias_detector.py</code> ·
            <code>smart_routing.py</code> ·
            <code>reflexion.py</code> ·
            <code>interactions.py</code> ·
            <code>llm_client.py</code> are shims; the rest are
            either documented Python-legacy exceptions or pending
            Phase 9 ports.
          </li>
          <li>
            <code>DiffDiagnosis/</code> + <code>SSA/</code> —
            sub-projects with their own Rust + Phoenix stacks, ports
            8765 / 8766. Both accept the cornerstone fields
            <code>patient_activation_level</code> and
            <code>patient_codesigned</code> (additive 2026-05-07).
          </li>
          <li>
            <code>Patients/</code> — local patient files. Never
            committed. Format
            <code>SURNAME_NAME_YYYY_MM_DD/</code>. Each folder
            contains <code>MEMORY.md</code> as canonical state plus
            optional <code>_pam_history.jsonl</code> (PAM-13
            administrations), <code>_codesign.jsonl</code> (co-design
            events), <code>AI_LOG.md</code> (kernel audit trail).
          </li>
        </ul>
        <h3>9.3 Lifecycle abstraction</h3>
        <p>
          AIM treats projects, patients, and experiments uniformly
          through the <code>aim-lifecycle</code> trait. Each entity
          type has its own state machine:
        </p>
        <ul>
          <li>
            <strong>Project</strong>: DRAFT → REVIEW → SUBMITTED →
            ACCEPTED → PUBLISHED (or REJECTED) → ARCHIVED
          </li>
          <li>
            <strong>Patient</strong>: INTAKE →
            DIAGNOSTIC_WORKUP → ACTIVE_TREATMENT → MONITORING →
            STABLE → CLOSED, with re-engagement edges
          </li>
          <li>
            <strong>Experiment</strong>: COMMISSIONING →
            CALIBRATING → RUNNING → DATA_PROCESSING → REPORTED →
            ARCHIVED
          </li>
        </ul>
        <p>
          A unified daily / weekly brief (Telegram + console)
          surfaces all three entity types together, ranked by
          urgency.
        </p>
      </section>

      <section class="about-section">
        <h2>10. Languages</h2>
        <p>
          AIM is multilingual end-to-end. Nine languages are
          supported across UI, prompts, OCR, lab reference text, and
          patient communications: English, French, Spanish, Arabic,
          Chinese, Russian (the six UN official languages) plus
          Georgian, Kazakh, and Danish. Translation is the
          responsibility of the <code>aim-i18n</code> crate and
          <code>i18n.py</code> shim; no string is hard-coded in
          production source paths (the cornerstone LiveViews are
          a 2026-05-07 known exception, scheduled for the next
          sprint).
        </p>
      </section>

      <section class="about-section">
        <h2>11. Deployment and operations</h2>
        <p>
          AIM ships as native systemd user units. There are no
          Docker images and no Docker is used in build, dev, or
          CI. A typical node install runs:
        </p>
        <pre><code>bash scripts/install_node.sh         # Linux/macOS — Ollama + venv + ~/.aim_env
    powershell scripts/install_node.ps1  # Windows
    </code></pre>
        <p>
          Service supervisor units include <code>aim-llm.service</code>
          (HTTP LLM router on :8770),
          <code>aim-serve-daemon.service</code> (long-running
          orchestrator),
          <code>aim-daily-brief.service</code> (09:00 patient +
          project digest),
          <code>aim-weekly-project-digest.service</code> (Sunday
          10:00 weekly digest),
          <code>aim-phoenix.service</code> (LiveView frontend on
          :4002).
        </p>
        <p>
          Health, metrics, and provider readiness are exposed via
          <code>/health</code>, <code>/metrics</code>, and
          <code>/v1/providers</code> on each service. There is no
          auto-pushed telemetry; everything is locally inspectable.
        </p>
      </section>

      <section class="about-section">
        <h2>12. Test coverage</h2>
        <p>
          As of 2026-05-07: <strong>1 287</strong> Python tests
          passing (kernel, scenarios, cornerstone integration,
          shims, lab-interactions), <strong>244+</strong> unit tests
          across 10 Rust cornerstone crates (kernel 62, llm-router
          13, pam 10, disagreement 11, codesign 6, coach 17,
          interactions 20, regimen-validator 18, reflexion 12,
          smart-routing 13). The full Rust workspace compiles in
          ≈30 s clean with 19 warnings, all stylistic. Phoenix
          umbrella compiles cleanly with 14 LiveView routes.
        </p>
        <p>
          Outstanding test gaps (tracked in
          <code>AUDIT_DEEP_2026-05-07.md</code>): the
          <code>aim-llm</code> HTTP service has zero unit tests on
          <code>/v1/chat</code> and <code>/v1/ensemble</code> —
          mock-based tests are the next priority.
        </p>
      </section>

      <section class="about-section">
        <h2>13. References</h2>
        <ul>
          <li>
            Tao Y. et al. (2026) — Co-design over fine-tuning RCT
            (n = 2069), <em>Nature Medicine</em>.
          </li>
          <li>
            Hibbard JH et al. (2004) — Patient Activation Measure
            (PAM-13), <em>Health Services Research</em>.
          </li>
          <li>
            Miller WR &amp; Rollnick S (2013) — Motivational
            Interviewing, 3rd ed., Guilford Press.
          </li>
          <li>
            Shinn N et al. (2023) — Reflexion: Language Agents with
            Verbal Reinforcement Learning.
          </li>
          <li>
            Blumenthal-Lee (2024-2025) — Performance-based 4-zone
            HCI for AI-clinician disagreement.
          </li>
          <li>
            Tkemaladze J. (2026) — "Patient as a Project: A
            Theoretical and Empirical Framework",
            <em>Longevity Horizon</em> 2(5), DOI
            <a href="https://doi.org/10.65649/qqwva850">10.65649/qqwva850</a>.
          </li>
        </ul>
      </section>

      <section class="about-section">
        <h2>14. License and contact</h2>
        <p>
          AIM is released under a permissive open-source license
          (see <code>LICENSE</code> in the source tree). Source:
          <code>~/Desktop/LongevityCommon/AIM/</code>.
          Lead maintainer: Jaba Tkemaladze
          (<a href="mailto:djabbat@gmail.com">djabbat@gmail.com</a>).
          Brand portal: <a href="https://longevity.ge">longevity.ge</a>.
        </p>
        <p class="muted">
          This page is the canonical English description of AIM and
          is regenerated whenever the cornerstone, kernel, or
          provider stack changes. Last refresh: 2026-05-07.
        </p>
      </section>

      <p class="back">
        <a href="/">← back to home</a>
      </p>
    </main>
    """
  end
end
