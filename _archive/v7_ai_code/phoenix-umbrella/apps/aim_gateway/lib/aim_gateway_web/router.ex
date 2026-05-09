defmodule AimGateway.Router do
  use Phoenix.Router

  pipeline :api do
    plug :accepts, ["json"]
  end

  pipeline :authed do
    plug AimGateway.Plugs.AuthToken
    plug AimGateway.Plugs.RateLimit
  end

  # Public — no auth needed
  scope "/api/v1", AimGateway do
    pipe_through :api

    get  "/health",            HealthController, :show
    get  "/system/health",     HealthController, :system
    post "/telegram/webhook",  TelegramController, :webhook
  end

  # Authed
  scope "/api/v1", AimGateway do
    pipe_through [:api, :authed]

    post "/chat",     ChatController, :create
    post "/diagnose", DiagnoseController, :create
  end

  # Hub-only endpoints (only mounted when AIM_ROLE=hub)
  if System.get_env("AIM_ROLE") == "hub" do
    scope "/api", AimGateway do
      pipe_through :api
      post "/auth/validate-token", HubController, :validate_token
    end

    scope "/api", AimGateway do
      pipe_through [:api, :authed]
      post "/nodes/heartbeat", HubController, :heartbeat
    end
  end
end
