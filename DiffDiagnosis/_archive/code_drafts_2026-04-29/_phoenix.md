```elixir
# mix.exs
defmodule Mixfile.MixProject do
  use Mix.Project

  def project do
    [
      app: :diffdx_web,
      version: "0.1.0",
      elixir: "~> 1.17",
      elixirc_paths: elixirc_paths(Mix.env()),
      start_permanent: Mix.env() == :prod,
      aliases: aliases(),
      deps: deps()
    ]
  end

  def application do
    [
      mod: {DiffdxWeb.Application, []},
      extra_applications: [:logger, :runtime_tools]
    ]
  end

  defp elixirc_paths(:test), do: ["lib", "test/support"]
  defp elixirc_paths(_), do: ["lib"]

  defp deps do
    [
      {:phoenix, "~> 1.7"},
      {:phoenix_live_view, "~> 1.0"},
      {:phoenix_html, "~> 4.1"},
      {:phoenix_live_reload, "~> 1.5", only: :dev},
      {:req, "~> 0.5"},
      {:jason, "~> 1.4"},
      {:telemetry, "~> 1.2"},
      {:plug_cowboy, "~> 2.7"},
      {:esbuild, "~> 0.8", runtime: Mix.env() == :dev}
    ]
  end

  defp aliases do
    [
      setup: ["deps.get", "cmd npm install --prefix assets"],
      "assets.deploy": ["esbuild default --minify", "phx.digest"]
    ]
  end
end
```

```elixir
# config/config.exs
import Config

config :diffdx_web, :generators, context_app: false

config :phoenix, :json_library, Jason

config :diffdx_web, DiffdxWeb.Endpoint,
  url: [host: "localhost"],
  secret_key_base: "abcdefghijklmnopqrstuvwxyz0123456789",
  render_errors: [view: DiffdxWeb.ErrorView, accepts: ~w(html json)],
  pubsub_server: DiffdxWeb.PubSub,
  live_view: [signing_salt: "abc123"]

config :esbuild,
  version: "0.17.0",
  default: [
    args: ["js/app.js", "--bundle", "--target=es2017", "--outdir=../priv/static/assets"],
    cd: Path.expand("../assets", __DIR__),
    env: %{"NODE_PATH" => Path.expand("../deps", __DIR__)}
  ]

config :logger, :console,
  format: "$time $metadata[$level] $message\n",
  metadata: [:request_id]
```

```elixir
# config/dev.exs
import Config

config :diffdx_web, DiffdxWeb.Endpoint,
  http: [port: 4000],
  debug_errors: true,
  code_reloader: true,
  check_origin: false,
  watchers: [
    esbuild: {Esbuild, :install_and_run, [:default, ~w(--sourcemap=inline --watch)]}
  ]

config :phoenix_live_reload, DiffdxWeb.Endpoint,
  live_reload: [
    patterns: [
      ~r{lib/diffdx_web/(live|views)/.*(ex|heex)$},
      ~r{priv/static/.*(js|css|png|jpeg|jpg|gif|svg)$},
      ~r{priv/gettext/.*(po)$}
    ]
  ]
```

```elixir
# lib/diffdx_web.ex
defmodule DiffdxWeb do
  @moduledoc false

  def view do
    quote do
      use Phoenix.View,
        root: "lib/diffdx_web/templates",
        namespace: DiffdxWeb

      import Phoenix.Controller,
        only: [get_flash: 1, get_flash: 2, view_module: 1]

      use Phoenix.HTML
    end
  end

  def router do
    quote do
      use Phoenix.Router, helpers: false
      import Phoenix.LiveView.Router
    end
  end

  def channel do
    quote do
      use Phoenix.Channel
    end
  end

  def live_view do
    quote do
      use Phoenix.LiveView,
        layout: {DiffdxWeb.LayoutView, :live}

      unquote(view())
    end
  end

  def live_component do
    quote do
      use Phoenix.LiveComponent
      unquote(view())
    end
  end

  def component do
    quote do
      use Phoenix.Component
    end
  end

  defmacro __using__(which) when is_atom(which) do
    apply(__MODULE__, which, [])
  end
end
```

```elixir
# lib/diffdx_web/application.ex
defmodule DiffdxWeb.Application do
  @moduledoc false

  use Application

  @impl true
  def start(_type, _args) do
    children = [
      DiffdxWeb.Telemetry,
      DiffdxWeb.DiffStore,
      {Phoenix.PubSub, name: DiffdxWeb.PubSub},
      DiffdxWeb.Endpoint
    ]

    opts = [strategy: :one_for_one, name: DiffdxWeb.Supervisor]
    Supervisor.start_link(children, opts)
  end

  @impl true
  def config_change(changed, _new, removed) do
    DiffdxWeb.Endpoint.config_change(changed, removed)
    :ok
  end
end
```

```elixir
# lib/diffdx_web/endpoint.ex
defmodule DiffdxWeb.Endpoint do
  use Phoenix.Endpoint, otp_app: :diffdx_web

  socket "/live", Phoenix.LiveView.Socket,
    websocket: [connect_info: [session: @session_options]],
    longpoll: [connect_info: [session: @session_options]]

  plug Plug.Static,
    at: "/",
    from: :diffdx_web,
    gzip: false,
    only: ~w(assets fonts images favicon.ico robots.txt)

  if code_reloading? do
    socket "/phoenix/live_reload/socket", Phoenix.LiveReloader.Socket
    plug Phoenix.LiveReloader
    plug Phoenix.CodeReloader
  end

  plug Plug.RequestId
  plug Plug.Telemetry, event_prefix: [:phoenix, :endpoint]

  plug Plug.Parsers,
    parsers: [:urlencoded, :multipart, :json],
    pass: ["*/*"],
    json_decoder: Phoenix.json_library()

  plug Plug.MethodOverride
  plug Plug.Head

  plug Plug.Session,
    store: :cookie,
    key: "_diffdx_web_key",
    signing_salt: "abc123"

  plug DiffdxWeb.Router
end
```

```elixir
# lib/diffdx_web/router.ex
defmodule DiffdxWeb.Router do
  use DiffdxWeb, :router

  pipeline :browser do
    plug :accepts, ["html"]
    plug :fetch_session
    plug :fetch_live_flash
    plug :put_root_layout, {DiffdxWeb.LayoutView, :root}
    plug :protect_from_forgery
    plug :put_secure_browser_headers
  end

  pipeline :api do
    plug :accepts, ["json"]
  end

  scope "/", DiffdxWeb do
    pipe_through :browser

    live "/", CaseLive.New
    live "/case/:id", CaseLive.Show
    live "/algorithms", AlgorithmsLive
    live "/sources", SourcesLive
  end
end
```

```elixir
# lib/diffdx_web/store.ex
defmodule DiffdxWeb.DiffStore do
  use GenServer

  def start_link(_opts) do