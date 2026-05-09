import Config

# Endpoints
config :aim_web, AimWeb.Endpoint,
  http: [ip: {127, 0, 0, 1}, port: 4002],
  pubsub_server: AimWeb.PubSub,
  live_view: [signing_salt: "aim_web_salt_dev"],
  secret_key_base: "REPLACE_VIA_RUNTIME_EXS",
  render_errors: [formats: [html: AimWeb.ErrorHTML, json: AimWeb.ErrorJSON], layout: false]

config :aim_gateway, AimGateway.Endpoint,
  http: [ip: {127, 0, 0, 1}, port: 4003],
  secret_key_base: "REPLACE_VIA_RUNTIME_EXS",
  render_errors: [formats: [json: AimGateway.ErrorJSON], layout: false]

# Upstream Rust services
config :aim_orchestrator,
  llm_url:        System.get_env("AIM_LLM_URL")        || "http://127.0.0.1:8770",
  rag_url:        System.get_env("AIM_RAG_URL")        || "http://127.0.0.1:8771",
  medkb_url:      System.get_env("AIM_MEDKB_URL")      || "http://127.0.0.1:8772",
  doctor_url:     System.get_env("AIM_DOCTOR_URL")     || "http://127.0.0.1:8773",
  generalist_url: System.get_env("AIM_GENERALIST_URL") || "http://127.0.0.1:8774",
  diffdx_url:     System.get_env("AIM_DIFFDX_URL")     || "http://127.0.0.1:8765",
  ssa_url:        System.get_env("AIM_SSA_URL")        || "http://127.0.0.1:8766"

# Memory (Postgres for prod, sqlite for dev)
config :aim_memory, AimMemory.Repo,
  database: Path.expand("../../aim.db", __DIR__),
  pool_size: 5

config :aim_memory, ecto_repos: [AimMemory.Repo]

# AIM_FS Port — set the absolute path of the `aim-fs` Rust binary and the
# data root.  See AIM/docs/AIM_FS/SPEC.md §10.2.
config :aim_memory, AimMemory.FS.Port,
  binary: System.get_env("AIM_FS_BIN") || "aim-fs",
  root: System.get_env("AIM_FS_ROOT") || Path.expand("~/.aim_fs"),
  call_timeout: 5_000

# Guided onboarding wizard. Reads YAML templates from `templates_dir` and
# shells out to `aim-onboard` (Rust binary).
config :aim_web, AimWebWeb.OnboardLive,
  binary: System.get_env("AIM_ONBOARD_BIN") || "aim-onboard",
  templates_dir:
    System.get_env("AIM_ONBOARD_TEMPLATES_DIR") ||
      Path.expand("../rust-core/crates/aim-onboarding/templates", __DIR__),
  aim_root: System.get_env("AIM_FS_ROOT") || Path.expand("~/.aim_fs")

config :phoenix, :json_library, Jason
config :logger, level: :info

import_config "#{config_env()}.exs"
