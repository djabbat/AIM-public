defmodule AimOrchestrator.HubClient do
  @moduledoc """
  Node-side hub integration. Replaces agents/hub_client.py.

  When AIM_ROLE=node, this GenServer:
    1. validates AIM_USER_TOKEN against AIM_HUB_URL on start
    2. caches the validation result for 24h (offline-grace 7d via env)
    3. sends a heartbeat every 5 min (configurable)

  Environment:
    AIM_ROLE=node | hub | (default: standalone — disables this client)
    AIM_HUB_URL=https://hub.example.com
    AIM_USER_TOKEN=aim_xxx
    AIM_NODE_ID=hostname-username   (default: derived)
    AIM_HEARTBEAT_SECONDS=300
    AIM_OFFLINE_GRACE_DAYS=7
  """
  use GenServer
  require Logger

  @cache_path "~/.cache/aim/hub_cache.json"
  @cache_ttl_seconds 24 * 3600

  # ── Public API ──────────────────────────────────────────────────────────────

  def start_link(_opts) do
    case System.get_env("AIM_ROLE") do
      "node" -> GenServer.start_link(__MODULE__, %{}, name: __MODULE__)
      _      -> :ignore
    end
  end

  def status, do: GenServer.call(__MODULE__, :status)

  # ── GenServer ───────────────────────────────────────────────────────────────

  @impl true
  def init(_state) do
    state = %{
      hub_url:    System.get_env("AIM_HUB_URL"),
      token:      System.get_env("AIM_USER_TOKEN"),
      node_id:    System.get_env("AIM_NODE_ID") || default_node_id(),
      validated?: false,
      last_validated_at: nil,
      offline_until: nil,
    }

    cond do
      is_nil(state.hub_url) or state.hub_url == "" ->
        Logger.warning("[hub_client] AIM_ROLE=node but AIM_HUB_URL missing — disabled")
        {:stop, :no_hub_url}

      is_nil(state.token) or state.token == "" ->
        Logger.warning("[hub_client] AIM_ROLE=node but AIM_USER_TOKEN missing — disabled")
        {:stop, :no_token}

      true ->
        send(self(), :validate)
        {:ok, state}
    end
  end

  @impl true
  def handle_info(:validate, state) do
    state =
      case validate_remote(state) do
        {:ok, _} ->
          write_cache(state.token)
          %{state | validated?: true, last_validated_at: now(), offline_until: nil}

        {:error, _reason} ->
          case read_cache(state.token) do
            {:ok, ts} ->
              grace = grace_seconds()
              if now() - ts < grace do
                Logger.warning("[hub_client] hub unreachable; running on cached validation")
                %{state | validated?: true, offline_until: ts + grace}
              else
                Logger.error("[hub_client] hub unreachable AND cache expired; refusing")
                %{state | validated?: false}
              end
            :error ->
              Logger.error("[hub_client] hub unreachable, no cache; refusing")
              %{state | validated?: false}
          end
      end

    schedule_heartbeat()
    {:noreply, state}
  end

  def handle_info(:heartbeat, state) do
    case heartbeat_remote(state) do
      :ok    -> :noop
      :error -> Logger.warning("[hub_client] heartbeat failed")
    end
    schedule_heartbeat()
    {:noreply, state}
  end

  @impl true
  def handle_call(:status, _from, state), do: {:reply, state, state}

  # ── Helpers ─────────────────────────────────────────────────────────────────

  defp validate_remote(%{hub_url: url, token: token}) do
    Req.post("#{url}/api/auth/validate-token",
      json: %{token: token},
      receive_timeout: 10_000)
    |> normalize()
  end

  defp heartbeat_remote(%{hub_url: url, token: token, node_id: node_id}) do
    case Req.post("#{url}/api/nodes/heartbeat",
           json: %{node_id: node_id, ts: now()},
           headers: [{"authorization", "Bearer #{token}"}],
           receive_timeout: 10_000) do
      {:ok, %Req.Response{status: s}} when s in 200..299 -> :ok
      _ -> :error
    end
  end

  defp normalize({:ok, %Req.Response{status: s, body: b}}) when s in 200..299, do: {:ok, b}
  defp normalize({:ok, %Req.Response{status: s}}), do: {:error, {:http, s}}
  defp normalize({:error, e}), do: {:error, {:transport, Exception.message(e)}}

  defp schedule_heartbeat do
    secs = case System.get_env("AIM_HEARTBEAT_SECONDS") do
      nil -> 300
      s   -> String.to_integer(s)
    end
    Process.send_after(self(), :heartbeat, secs * 1000)
  end

  defp grace_seconds do
    days = case System.get_env("AIM_OFFLINE_GRACE_DAYS") do
      nil -> 7
      d   -> String.to_integer(d)
    end
    days * 86_400
  end

  defp now, do: DateTime.utc_now() |> DateTime.to_unix()

  defp default_node_id do
    {:ok, host} = :inet.gethostname()
    user = System.get_env("USER") || "anon"
    "#{host}-#{user}"
  end

  defp cache_path do
    @cache_path
    |> Path.expand()
  end

  defp write_cache(token) do
    path = cache_path()
    File.mkdir_p!(Path.dirname(path))
    payload = %{
      token_hash: :crypto.hash(:sha256, token) |> Base.encode16(case: :lower),
      ts: now()
    }
    File.write!(path, Jason.encode!(payload))
  end

  defp read_cache(token) do
    path = cache_path()
    expected = :crypto.hash(:sha256, token) |> Base.encode16(case: :lower)
    with {:ok, data} <- File.read(path),
         {:ok, %{"token_hash" => h, "ts" => ts}} <- Jason.decode(data),
         true <- h == expected,
         true <- now() - ts < @cache_ttl_seconds * 7 do
      {:ok, ts}
    else
      _ -> :error
    end
  end
end
