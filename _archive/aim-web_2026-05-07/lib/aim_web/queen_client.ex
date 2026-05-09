defmodule AimWeb.QueenClient do
  @moduledoc """
  Thin HTTP client for the local AIM Hive queen (`aim-hive-queen` Rust
  binary). Endpoints mirror the Rust crate's Axum routes:

      GET  /healthz               public
      GET  /v1/hive/updates       public (or Bearer if AIM_HIVE_REQUIRE_AUTH=1)
      GET  /v1/hive/status        admin (Bearer)

  Default base URL is `http://127.0.0.1:8090` — the queen's loopback
  port. Override with `AIM_HIVE_QUEEN_URL`.
  """

  require Logger

  @default_url "http://127.0.0.1:8090"

  @spec base_url() :: String.t()
  def base_url do
    System.get_env("AIM_HIVE_QUEEN_URL") || @default_url
  end

  @spec admin_token() :: String.t() | nil
  def admin_token do
    System.get_env("AIM_HIVE_ADMIN_TOKEN")
  end

  @spec healthz() :: {:ok, map()} | {:error, term()}
  def healthz do
    get_json(base_url() <> "/healthz", [])
  end

  @spec status() :: {:ok, map()} | {:error, term()}
  def status do
    headers = bearer_header(admin_token())
    get_json(base_url() <> "/v1/hive/status", headers)
  end

  @spec updates(String.t() | nil) :: {:ok, list(map())} | {:error, term()}
  def updates(since \\ nil) do
    qs = if is_binary(since), do: "?since=" <> URI.encode_www_form(since), else: ""

    case get_json(base_url() <> "/v1/hive/updates" <> qs, []) do
      {:ok, %{"updates" => list}} when is_list(list) -> {:ok, list}
      {:ok, _other} -> {:ok, []}
      {:error, _} = e -> e
    end
  end

  # ── helpers ────────────────────────────────────────────────────

  defp get_json(url, headers) do
    case :httpc.request(:get, {String.to_charlist(url), to_httpc_headers(headers)},
           [{:timeout, 5_000}, {:connect_timeout, 2_000}],
           []) do
      {:ok, {{_, 200, _}, _hdrs, body}} ->
        case Jason.decode(IO.iodata_to_binary(body)) do
          {:ok, json} -> {:ok, json}
          {:error, e} -> {:error, {:bad_json, e}}
        end

      {:ok, {{_, status, _}, _, _body}} ->
        {:error, {:http, status}}

      {:error, reason} ->
        Logger.debug("queen client error: #{inspect(reason)}")
        {:error, reason}
    end
  end

  defp bearer_header(nil), do: []
  defp bearer_header(t), do: [{"Authorization", "Bearer " <> t}]

  defp to_httpc_headers(list) do
    Enum.map(list, fn {k, v} -> {String.to_charlist(k), String.to_charlist(v)} end)
  end
end
