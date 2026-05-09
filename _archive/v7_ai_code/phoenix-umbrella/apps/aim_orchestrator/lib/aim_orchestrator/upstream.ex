defmodule AimOrchestrator.Upstream do
  @moduledoc """
  Tiny HTTP wrapper around Req with a uniform error shape.
  Each Rust service URL is configured under :aim_orchestrator app env.
  """

  @timeout_ms 30_000

  def post(url_key, path, body) when is_binary(url_key) do
    base = Application.fetch_env!(:aim_orchestrator, String.to_atom(url_key))

    Req.post(base <> path, json: body, receive_timeout: @timeout_ms)
    |> normalize()
  end

  def get(url_key, path) when is_binary(url_key) do
    base = Application.fetch_env!(:aim_orchestrator, String.to_atom(url_key))

    Req.get(base <> path, receive_timeout: @timeout_ms)
    |> normalize()
  end

  def base(url_key) when is_binary(url_key) do
    Application.fetch_env!(:aim_orchestrator, String.to_atom(url_key))
  end

  defp normalize({:ok, %Req.Response{status: s, body: b}}) when s in 200..299, do: {:ok, b}
  defp normalize({:ok, %Req.Response{status: s, body: b}}), do: {:error, {:upstream, s, b}}
  defp normalize({:error, exception}), do: {:error, {:transport, Exception.message(exception)}}
end
