defmodule AimGateway.HubController do
  @moduledoc """
  Hub-side endpoints for node validation + heartbeat. Active only when
  AIM_ROLE=hub. The router gates this; controllers expect AuthToken plug
  to have validated the bearer token already.
  """
  use Phoenix.Controller, formats: [:json]

  def validate_token(conn, %{"token" => token}) do
    hash = AimMemory.hash_token(token)
    case AimMemory.lookup_token(hash) do
      %AimMemory.AuthToken{username: u, role: r} ->
        json(conn, %{ok: true, username: u, role: r})
      nil ->
        conn |> put_status(:unauthorized) |> json(%{ok: false, error: "invalid"})
    end
  end

  def heartbeat(conn, %{"node_id" => node_id} = params) do
    auth = conn.assigns[:auth] || %{}
    ts = params["ts"] || DateTime.utc_now() |> DateTime.to_unix()
    # In a richer impl we'd persist into a `nodes` table. For now, log.
    require Logger
    Logger.info("[hub] heartbeat node=#{node_id} user=#{auth[:username]} ts=#{ts}")
    json(conn, %{ok: true, observed_at: DateTime.utc_now() |> DateTime.to_iso8601()})
  end
end
