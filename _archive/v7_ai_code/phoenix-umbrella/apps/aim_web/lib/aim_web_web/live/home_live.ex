defmodule AimWeb.HomeLive do
  @moduledoc """
  Landing page styled to match longevity.ge — light/dark themes, indigo
  hero gradient, white cards, Inter+JetBrains Mono fonts. The structural
  classes (.hero, .container, .grid, .card) are identical to those used
  on longevity.ge so the look is uniform across the ecosystem.
  """
  use AimWeb, :live_view

  # Suppress the layout's own header — HomeLive renders its own header
  # AFTER the hero (between the indigo banner and the quicknav cards).
  def mount(_params, _session, socket),
    do: {:ok, assign(socket, :skip_layout_header, true)}

  def render(assigns) do
    ~H"""
    <section class="hero">
      <div class="hero-inner">
        <div class="hero-pill">Active · 178 crates · 2531 tests</div>
        <h1 class="hero-title"><%= t("home.heading", @locale) %></h1>
        <p class="hero-subtitle"><%= t("home.tagline", @locale) %></p>

        <div class="hero-stats">
          <div class="s"><div class="k">Crates</div><div class="v">178</div></div>
          <div class="s"><div class="k">Tests</div><div class="v">2 531</div></div>
          <div class="s"><div class="k">Warnings</div><div class="v">0</div></div>
          <div class="s"><div class="k">Languages</div><div class="v">7 (UN-6+KA)</div></div>
        </div>

        <div class="hero-cta">
          <a href="/dashboard" class="btn btn-primary">
            <%= t("home.cta.dashboard", @locale) %>
          </a>
          <a href="/chat" class="btn btn-ghost">
            <%= t("home.cta.chat", @locale) %>
          </a>
        </div>
      </div>
    </section>

    <header class="header">
      <div class="header-inner">
        <a href="/" class="brand"><span class="logo">⌬</span>AIM</a>
        <nav>
          <a href="/dashboard"><%= t("home.menu.dashboard", @locale) %></a>
          <a href="/chat"><%= t("nav.chat", @locale) %></a>
          <a href="/intake"><%= t("nav.intake", @locale) %></a>
          <a href="/cases"><%= t("nav.cases", @locale) %></a>
          <a href="/drugs"><%= t("home.menu.drugs", @locale) %></a>
          <a href="/settings"><%= t("home.menu.settings", @locale) %></a>
          <a href="/about">About</a>
          <a href="/status">Status</a>
          <a href="/admin" title="Operator control panel">Admin</a>
        </nav>
        <form method="get" class="lang-switcher">
          <select name="locale" onchange="this.form.submit()" aria-label="Language">
            <%= for loc <- AimWeb.I18n.locales() do %>
              <option value={loc} selected={loc == @locale}><%= AimWeb.I18n.name(loc) %></option>
            <% end %>
          </select>
        </form>
      </div>
    </header>

    <main class="container">
      <h2 class="section-title">Capabilities</h2>
      <p class="section-lead"><%= t("home.feature.diagnostics", @locale) %></p>

      <div class="grid">
        <div class="card">
          <div class="role">🩺 Clinical</div>
          <h3>Differential diagnosis</h3>
          <p>Symptom intake → ranked differentials with reasoning trace, drug interaction check, lab interpretation.</p>
          <div class="badges">
            <span class="badge purple">aim-doctor</span>
            <span class="badge gray">aim-interactions</span>
          </div>
        </div>
        <div class="card">
          <div class="role">🔐 Privacy</div>
          <h3><%= t("home.feature.privacy", @locale) %></h3>
          <p>Per-user provider keys (DeepSeek, Groq, Claude, Gemini, local Ollama). Patient data stays on the local node, hub never sees it.</p>
          <div class="badges">
            <span class="badge green">GDPR-aware</span>
            <span class="badge blue">multi-tenant</span>
          </div>
        </div>
        <div class="card">
          <div class="role">🦀 Stack</div>
          <h3>Native Rust + Phoenix</h3>
          <p>178 Rust crates with 2 531 unit tests, zero warnings. Phoenix LiveView UI. No Docker — native systemd. Native installers for Linux, macOS, Windows.</p>
          <div class="badges">
            <span class="badge purple">Rust 1.78+</span>
            <span class="badge purple">Elixir 1.17</span>
          </div>
        </div>
      </div>

      <h2 class="section-title">Quick navigation</h2>
      <p class="section-lead">All entry points to AIM — pick a workflow.</p>

      <div class="grid">
        <a href="/dashboard" class="card link">
          <div class="role">📊 Overview</div>
          <h3><%= t("home.menu.dashboard", @locale) %><span class="arrow">→</span></h3>
          <p><%= t("dashboard.health", @locale) %> · <%= t("dashboard.projects", @locale) %> · <%= t("dashboard.deadlines", @locale) %></p>
        </a>
        <a href="/chat" class="card link">
          <div class="role">💬 LLM</div>
          <h3><%= t("nav.chat", @locale) %><span class="arrow">→</span></h3>
          <p><%= t("home.cta.chat", @locale) %> · multi-LLM routing through aim-llm-router.</p>
        </a>
        <a href="/intake" class="card link">
          <div class="role">📝 Patient</div>
          <h3><%= t("nav.intake", @locale) %><span class="arrow">→</span></h3>
          <p><%= t("intake.heading", @locale) %> · OCR/PDF lab parsing via aim-patient-inbox-watcher.</p>
        </a>
        <a href="/cases" class="card link">
          <div class="role">📁 History</div>
          <h3><%= t("nav.cases", @locale) %><span class="arrow">→</span></h3>
          <p><%= t("cases.heading", @locale) %> · stored locally per CLAUDE.md privacy rule.</p>
        </a>
        <a href="/drugs" class="card link">
          <div class="role">💊 Safety</div>
          <h3><%= t("home.menu.drugs", @locale) %><span class="arrow">→</span></h3>
          <p><%= t("drugs.prompt", @locale) %></p>
        </a>
        <a href="/settings" class="card link">
          <div class="role">⚙️ Account</div>
          <h3><%= t("home.menu.settings", @locale) %><span class="arrow">→</span></h3>
          <p><%= t("settings.keys", @locale) %></p>
        </a>
      </div>

      <h2 class="section-title">Patient as a Project (cornerstone)</h2>
      <p class="section-lead">
        Level-3 developmental engagement: PAM-13 trajectory, co-design log,
        4-zone disagreement classifier, motivational-interviewing coach.
        <br/>
        <small>
          Per Tkemaladze J. (2026), <em>Longevity Horizon</em> 2(5),
          DOI <a href="https://doi.org/10.65649/qqwva850">10.65649/qqwva850</a>.
        </small>
      </p>

      <div class="grid">
        <a href="/pam" class="card link">
          <div class="role">📊 Activation</div>
          <h3>PAM-13 cohort<span class="arrow">→</span></h3>
          <p>Patient Activation Measure trajectory across the cohort
          (MCID 5.4, MDC 7.2). Per-patient drill-down at /pam/:id.</p>
          <div class="badges">
            <span class="badge purple">aim-pam</span>
          </div>
        </a>
        <a href="/activation" class="card link">
          <div class="role">🎯 Funnel</div>
          <h3>Activation funnel<span class="arrow">→</span></h3>
          <p>L1→L4 distribution across all patients with PAM-13 history.</p>
        </a>
        <a href="/disagreement" class="card link">
          <div class="role">⚖️ HCI</div>
          <h3>Disagreement zones<span class="arrow">→</span></h3>
          <p>Blumenthal-Lee 4-zone classifier — interactive explorer for
          AI/clinician confidence pairs.</p>
          <div class="badges">
            <span class="badge purple">aim-disagreement</span>
          </div>
        </a>
        <a href="/coaching/example" class="card link">
          <div class="role">🌱 Coaching</div>
          <h3>Motivational interviewing<span class="arrow">→</span></h3>
          <p>OARS classifier + next-move picker for clinician-facing
          patient coaching turns. /coaching/&lt;patient_id&gt;.</p>
          <div class="badges">
            <span class="badge purple">aim-coach</span>
          </div>
        </a>
      </div>
    </main>
    """
  end
end
