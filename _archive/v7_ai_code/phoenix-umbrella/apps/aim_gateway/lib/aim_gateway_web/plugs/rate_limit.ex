defmodule AimGateway.Plugs.RateLimit do
  @moduledoc """
  Token-bucket rate limiter keyed by auth username (or remote_ip if anonymous).
  Implementation: ETS-backed counters reset every minute.

  Limits (env, defaults):
    AIM_RPM_USER  → 60   (per token, per minute)
    AIM_RPM_IP    → 30   (per IP, per minute, anonymous traffic)

  Skips bucket creation in tests via AIM_RATE_LIMIT_DISABLE=1.
  """
  import Plug.Conn
  require Logger

  @table :aim_rate_limit

  def init(opts), do: opts

  def call(conn, _opts) do
    if System.get_env("AIM_RATE_LIMIT_DISABLE") == "1" do
      conn
    else
      ensure_table()
      auth = conn.assigns[:auth] || %{}
      key =
        if auth[:anonymous] != false do
          {:ip, ip_string(conn)}
        else
          {:user, auth[:username] || "?"}
        end

      limit = limit_for(key)
      window = bucket_window()
      bucket_key = {key, window}

      count = :ets.update_counter(@table, bucket_key, {2, 1}, {bucket_key, 0})

      if count > limit do
        conn
        |> put_status(:too_many_requests)
        |> put_resp_header("retry-after", "60")
        |> Phoenix.Controller.json(%{error: "rate_limited", limit: limit, window_seconds: 60})
        |> halt()
      else
        conn
      end
    end
  end

  defp ensure_table do
    case :ets.info(@table) do
      :undefined -> :ets.new(@table, [:public, :named_table, write_concurrency: true])
      _ -> :ok
    end
  end

  defp ip_string(conn) do
    case conn.remote_ip do
      nil -> "?"
      ip  -> ip |> Tuple.to_list() |> Enum.join(".")
    end
  end

  defp limit_for({:user, _}) do
    String.to_integer(System.get_env("AIM_RPM_USER") || "60")
  end
  defp limit_for({:ip, _}) do
    String.to_integer(System.get_env("AIM_RPM_IP") || "30")
  end

  defp bucket_window do
    div(System.os_time(:second), 60)
  end
end
