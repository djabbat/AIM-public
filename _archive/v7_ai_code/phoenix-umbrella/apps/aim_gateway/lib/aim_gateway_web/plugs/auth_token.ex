defmodule AimGateway.Plugs.AuthToken do
  @moduledoc """
  Bearer-token auth. Reads `Authorization: Bearer <token>` (or `?token=`),
  hashes it, and looks up against AimMemory.AuthToken.

  If env `AIM_REQUIRE_AUTH=0` (default for dev) — bypassed unless a token is present.
  In prod set `AIM_REQUIRE_AUTH=1`.
  """
  import Plug.Conn

  @auth_header "authorization"

  def init(opts), do: opts

  def call(conn, _opts) do
    required? = System.get_env("AIM_REQUIRE_AUTH") == "1"
    raw = extract(conn)

    case {raw, required?} do
      {nil, true} ->
        deny(conn, "missing_token")

      {nil, false} ->
        assign(conn, :auth, %{anonymous: true})

      {raw, _} ->
        case AimMemory.lookup_token(AimMemory.hash_token(raw)) do
          nil ->
            deny(conn, "invalid_or_expired")

          %AimMemory.AuthToken{username: u, role: r} ->
            conn
            |> assign(:auth, %{username: u, role: r, anonymous: false})
        end
    end
  end

  defp extract(conn) do
    header =
      conn
      |> get_req_header(@auth_header)
      |> List.first()

    cond do
      is_binary(header) and String.starts_with?(header, "Bearer ") ->
        String.trim_leading(header, "Bearer ")

      params_map?(conn) and is_binary(conn.params["token"]) ->
        conn.params["token"]

      true ->
        nil
    end
  end

  defp params_map?(conn) do
    case conn.params do
      %Plug.Conn.Unfetched{} -> false
      m when is_map(m)       -> true
      _                      -> false
    end
  end

  defp deny(conn, code) do
    conn
    |> put_status(:unauthorized)
    |> Phoenix.Controller.json(%{error: code})
    |> halt()
  end
end
