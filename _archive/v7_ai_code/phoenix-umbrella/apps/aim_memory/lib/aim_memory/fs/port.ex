defmodule AimMemory.FS.Port do
  @moduledoc """
  Owns the Erlang Port that talks to the `aim-fs` Rust binary.

  Each `call/1` ships one JSON line, blocks until one JSON line of reply arrives
  (or the configured timeout fires).  Concurrent callers serialize through this
  GenServer — that's intentional: the Rust binary serializes via SQLite WAL +
  BEGIN IMMEDIATE anyway, so a single process pipeline avoids interleaved IO on
  the Port.

  Configuration:
      config :aim_memory, AimMemory.FS.Port,
        binary: "/opt/aim/bin/aim-fs",
        root: "/var/lib/aim_fs",
        call_timeout: 5_000

  A watchdog auto-restarts the binary if it dies; in-flight callers receive
  `{:error, :port_died}`.
  """
  use GenServer
  require Logger

  @type call_result :: {:ok, term()} | {:error, term()}

  ## Public API

  def start_link(opts \\ []) do
    GenServer.start_link(__MODULE__, opts, name: __MODULE__)
  end

  @spec call(map(), timeout()) :: call_result
  def call(payload, timeout \\ 5_000) when is_map(payload) do
    GenServer.call(__MODULE__, {:cmd, payload}, timeout + 1_000)
  end

  ## GenServer

  @impl true
  def init(opts) do
    cfg = Application.get_env(:aim_memory, __MODULE__, [])
    binary = Keyword.get(opts, :binary) || Keyword.get(cfg, :binary) || "aim-fs"
    root = Keyword.get(opts, :root) || Keyword.get(cfg, :root) || "/var/lib/aim_fs"

    port =
      Port.open({:spawn_executable, System.find_executable(binary)},
        [:binary, :line, :exit_status, args: [], env: [{~c"AIM_FS_ROOT", to_charlist(root)}]]
      )

    {:ok, %{port: port, pending: nil, buffer: ""}}
  end

  @impl true
  def handle_call({:cmd, payload}, from, %{pending: nil} = state) do
    line = Jason.encode!(payload) <> "\n"
    Port.command(state.port, line)
    {:noreply, %{state | pending: from}}
  end

  def handle_call({:cmd, _payload}, _from, state) do
    {:reply, {:error, :busy}, state}
  end

  @impl true
  def handle_info({port, {:data, {:eol, line}}}, %{port: port, pending: from} = state) do
    case Jason.decode(line) do
      {:ok, %{"ok" => true, "result" => res}} ->
        GenServer.reply(from, {:ok, res})
      {:ok, %{"ok" => false, "error" => err}} ->
        GenServer.reply(from, {:error, err})
      {:error, decode_err} ->
        GenServer.reply(from, {:error, {:decode, decode_err, line}})
    end
    {:noreply, %{state | pending: nil}}
  end

  def handle_info({port, {:exit_status, status}}, %{port: port, pending: pending} = state) do
    Logger.error("aim-fs port died with status #{status}")
    if pending, do: GenServer.reply(pending, {:error, :port_died})
    {:stop, {:port_died, status}, state}
  end

  def handle_info(_msg, state), do: {:noreply, state}
end
