defmodule DiffdxWeb.DiffdxClient do
  @moduledoc """
  HTTP client for the Rust diffdx-api backend (axum, default port 8765).
  Uses Req. Configure base URL via `:diffdx_web, :api_base`.
  """

  @default_base "http://127.0.0.1:8765"

  defp base_url do
    Application.get_env(:diffdx_web, :api_base, @default_base)
  end

  def health do
    Req.get(base_url() <> "/health") |> unwrap()
  end

  def diff(free_text, structured \\ %{}) do
    Req.post(base_url() <> "/api/v1/diff",
      json: %{free_text: free_text, structured: structured}
    )
    |> unwrap()
  end

  def list_algorithms do
    Req.get(base_url() <> "/api/v1/algorithms") |> unwrap()
  end

  def get_algorithm(id) do
    Req.get(base_url() <> "/api/v1/algorithm/" <> id) |> unwrap()
  end

  def list_sources do
    Req.get(base_url() <> "/api/v1/sources") |> unwrap()
  end

  defp unwrap({:ok, %Req.Response{status: s, body: b}}) when s in 200..299, do: {:ok, b}
  defp unwrap({:ok, %Req.Response{status: s, body: b}}), do: {:error, {:http, s, b}}
  defp unwrap({:error, e}), do: {:error, e}
end
