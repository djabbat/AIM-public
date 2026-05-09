defmodule AimGateway.HealthController do
  use Phoenix.Controller, formats: [:json]

  @services %{
    "aim_llm"        => "llm_url",
    "aim_rag"        => "rag_url",
    "aim_medkb"      => "medkb_url",
    "aim_doctor"     => "doctor_url",
    "aim_generalist" => "generalist_url",
    "diffdx_api"     => "diffdx_url",
    "ssa_api"        => "ssa_url"
  }

  def show(conn, _params) do
    json(conn, %{service: "aim_gateway", status: "ok"})
  end

  def system(conn, _params) do
    upstreams =
      @services
      |> Enum.map(fn {name, key} -> Task.async(fn -> {name, probe(key)} end) end)
      |> Enum.map(&Task.await(&1, 5_000))
      |> Map.new()

    overall = if Enum.all?(Map.values(upstreams), &(&1["status"] == "ok")), do: "ok", else: "degraded"
    json(conn, %{
      service: "aim_gateway",
      overall_status: overall,
      upstreams: upstreams,
      checked_at: DateTime.utc_now() |> DateTime.to_iso8601()
    })
  end

  defp probe(key) do
    base =
      try do
        Application.fetch_env!(:aim_orchestrator, String.to_atom(key))
      rescue
        _ -> nil
      end

    if base in [nil, ""] do
      %{"status" => "not_configured"}
    else
      case Req.get("#{base}/health", receive_timeout: 3_000) do
        {:ok, %Req.Response{status: 200, body: b}} when is_map(b) ->
          %{"status" => b["status"] || "ok", "url" => base}
        {:ok, %Req.Response{status: s}} ->
          %{"status" => "bad_status", "code" => s, "url" => base}
        {:error, e} ->
          %{"status" => "unreachable", "error" => Exception.message(e), "url" => base}
      end
    end
  end
end
