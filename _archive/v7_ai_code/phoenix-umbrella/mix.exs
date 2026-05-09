defmodule AimUmbrella.MixProject do
  use Mix.Project

  def project do
    [
      apps_path: "apps",
      version: "0.1.0",
      start_permanent: Mix.env() == :prod,
      deps: deps(),
      aliases: aliases(),
      releases: releases()
    ]
  end

  defp releases do
    [
      aim_web: [
        applications: [
          aim_gateway: :permanent,
          aim_memory: :permanent,
          aim_orchestrator: :permanent,
          aim_web: :permanent
        ],
        include_executables_for: [:unix],
        steps: [:assemble]
      ]
    ]
  end

  defp deps do
    []
  end

  defp aliases do
    [
      setup: ["cmd mix setup"],
      "ecto.setup": ["cmd --app aim_memory mix ecto.setup"]
    ]
  end
end
