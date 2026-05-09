defmodule AimWeb.Router do
  use AimWeb, :router

  pipeline :browser do
    plug :accepts, ["html"]
    plug :fetch_session
    plug :fetch_live_flash
    plug :put_root_layout, html: {AimWeb.Layouts, :root}
    plug :protect_from_forgery
    plug :put_secure_browser_headers
    plug AimWeb.Plugs.SecurityHeaders
    plug AimWeb.Plugs.Locale
  end

  pipeline :health do
    plug :accepts, ["json"]
  end

  scope "/", AimWeb do
    pipe_through :health
    get "/health", HealthController, :index
  end

  scope "/", AimWeb do
    pipe_through :browser

    live "/",         HomeLive,     :index
    live "/chat",     ChatLive,     :index
    live "/intake",   IntakeLive,   :new
    live "/cases",    CasesLive,    :index
    live "/cases/:id", CaseLive,    :show
    live "/consult",  ConsultLive,  :index
    live "/dashboard", DashboardLive, :index
    live "/drugs",    DrugInteractionsLive, :index
    live "/settings", SettingsLive,  :index
    # AIM_FS approval queue (SPEC v11 ACCEPT 2026-05-08):
    live "/inbox",            InboxLive,             :index
    live "/onboard",          OnboardLive,           :index
    live "/fs/projects",      ProjectsBrowserLive,   :index
    live "/fs/patients",      PatientsBrowserLive,   :index
    live "/fs/disputes",      DisputesLive,          :index
    live "/fs/search",        SearchLive,            :index
    live "/fs/profile",       ProfileLive,           :index
    live "/fs/projects/:slug", ProjectActivityLive,  :show
    live "/fs/entity/:id",     EntityDetailLive,     :show
    live "/fs",                FsDashboardLive,      :index
    live "/fs/replay",         ReplayLive,           :index
    live "/fs/stats",          StatsLive,            :index
    live "/fs/audit",          AuditLive,            :index
    # Phase A/B (HW1, 2026-05-06):
    live "/patients",    PatientLive,    :index
    live "/patients/:id", PatientWorkspaceLive, :show
    live "/experiments", ExperimentLive, :index
    # Patient as a Project cornerstone (Fix #3, 2026-05-07):
    live "/pam",                   PamLive,           :cohort
    live "/pam/:patient_id",       PamLive,           :patient
    live "/cohort",                CohortLive,        :index
    live "/codesign/:patient_id",  CodesignLive,      :index
    live "/disagreement",          DisagreementLive,  :index
    live "/activation",            ActivationLive,    :index
    # Phase 4 cornerstone (2026-05-07):
    live "/coaching/:patient_id",  CoachingLive,      :index
    # System description (English) — single source of truth (2026-05-07):
    live "/about",                 AboutLive,         :index
    # Public observability dashboard (2026-05-07):
    live "/status",                HealthLive,        :index
    # Operator control panel (2026-05-07):
    live "/admin",                 AdminLive,         :index
  end
end
