defmodule AimOrchestrator.Doctor do
  @moduledoc "Wrapper for aim-doctor :8773 endpoints."

  alias AimOrchestrator.Upstream

  def intake(complaint, language \\ nil) do
    body = if language, do: %{complaint: complaint, language: language}, else: %{complaint: complaint}
    Upstream.post("doctor_url", "/v1/intake", body)
  end

  def diagnose(case_id_or_intake, opts \\ []) do
    body =
      cond do
        is_binary(case_id_or_intake) -> %{case_id: case_id_or_intake}
        is_map(case_id_or_intake)    -> %{intake: case_id_or_intake}
        true                          -> %{}
      end
      |> maybe_put(:cbc, Keyword.get(opts, :cbc))
      |> maybe_put(:system, Keyword.get(opts, :system))

    Upstream.post("doctor_url", "/v1/diagnose", body)
  end

  def list_cases, do: Upstream.get("doctor_url", "/v1/cases")
  def get_case(id), do: Upstream.get("doctor_url", "/v1/cases/#{id}")

  defp maybe_put(map, _k, nil), do: map
  defp maybe_put(map, k, v), do: Map.put(map, k, v)
end
