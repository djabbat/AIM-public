defmodule SsaWeb.SsaClient do
  @moduledoc "HTTP client for ssa-api Rust backend (default :8766)."

  @default_base "http://127.0.0.1:8766"

  defp base, do: Application.get_env(:ssa_web, :api_base, @default_base)

  def health, do: Req.get(base() <> "/health") |> unwrap()

  def syndromes(values, sex \\ "any", age \\ ">=18") do
    Req.post(base() <> "/api/v1/syndromes",
      json: %{values: values, sex: sex, age: age}
    )
    |> unwrap()
  end

  def list_parameters, do: Req.get(base() <> "/api/v1/parameters") |> unwrap()
  def list_patterns,   do: Req.get(base() <> "/api/v1/patterns") |> unwrap()

  defp unwrap({:ok, %Req.Response{status: s, body: b}}) when s in 200..299, do: {:ok, b}
  defp unwrap({:ok, %Req.Response{status: s, body: b}}), do: {:error, {:http, s, b}}
  defp unwrap({:error, e}), do: {:error, e}
end
