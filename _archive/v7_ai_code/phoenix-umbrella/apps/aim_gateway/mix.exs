defmodule AimGateway.MixProject do
  use Mix.Project

  def project do
    [
      app: :aim_gateway,
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
      mod: {AimGateway.Application, []},
      extra_applications: [:logger, :runtime_tools]
    ]
  end

  defp deps do
    [
      {:phoenix, "~> 1.7"},
      {:phoenix_pubsub, "~> 2.1"},
      {:plug_cowboy, "~> 2.7"},
      {:bandit, "~> 1.5"},
      {:jason, "~> 1.4"},
      {:aim_orchestrator, in_umbrella: true},
      {:aim_memory, in_umbrella: true},
      {:plug_crypto, "~> 2.0"}
    ]
  end
end
