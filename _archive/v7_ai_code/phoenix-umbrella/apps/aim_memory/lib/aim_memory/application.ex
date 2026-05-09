defmodule AimMemory.Application do
  @moduledoc false
  use Application

  @impl true
  def start(_type, _args) do
    children =
      [AimMemory.Repo] ++ aim_fs_port_children()

    Supervisor.start_link(children, strategy: :one_for_one, name: AimMemory.Supervisor)
  end

  # AIM_FS Port GenServer (SPEC v11 §10.2). Started only when the binary is
  # available — keeps dev/CI environments without the Rust binary working.
  defp aim_fs_port_children do
    cfg = Application.get_env(:aim_memory, AimMemory.FS.Port, [])
    bin = Keyword.get(cfg, :binary) || System.get_env("AIM_FS_BIN") || "aim-fs"

    if System.find_executable(bin) do
      [AimMemory.FS.Port]
    else
      :logger.warning(
        "AimMemory.FS.Port not started — `aim-fs` binary not found on PATH. " <>
          "Set config :aim_memory, AimMemory.FS.Port, binary: \"/path/to/aim-fs\" " <>
          "or place the binary on PATH."
      )

      []
    end
  end
end
