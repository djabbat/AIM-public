defmodule AimWeb.MixProject do
  use Mix.Project

  def project do
    [
      app: :aim_web,
      version: "0.1.0",
      build_path: "../../_build",
      config_path: "../../config/config.exs",
      deps_path: "../../deps",
      lockfile: "../../mix.lock",
      elixir: "~> 1.17",
      start_permanent: Mix.env() == :prod,
      deps: deps()
    ]
  end

  def application do
    [
      mod: {AimWeb.Application, []},
      extra_applications: [:logger, :runtime_tools]
    ]
  end

  defp deps do
    [
      {:phoenix, "~> 1.7"},
      {:phoenix_html, "~> 4.1"},
      {:phoenix_live_view, "~> 1.0"},
      {:phoenix_pubsub, "~> 2.1"},
      {:bandit, "~> 1.5"},
      {:jason, "~> 1.4"},
      {:aim_orchestrator, in_umbrella: true},
      {:aim_memory, in_umbrella: true},
      # Phoenix LiveViewTest needs an HTML parser at test-time (P2.7, 2026-05-07).
      {:lazy_html, ">= 0.1.0", only: :test}
    ]
  end
end
