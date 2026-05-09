defmodule AimWeb.AiClient do
  @moduledoc """
  Thin shell to the `aim-ai-health-info` Rust binary, which is the
  single source of truth for ledger/regression/health metrics.

  Returns a normalised map; on any error returns `{:error, reason}`.
  """

  require Logger

  @spec snapshot() :: {:ok, map()} | {:error, term()}
  def snapshot do
    bin = binary_path()

    case System.cmd(bin, ["--json"], stderr_to_stdout: true) do
      {out, 0} ->
        case Jason.decode(out) do
          {:ok, m} -> {:ok, normalise(m)}
          err -> err
        end

      {out, code} ->
        Logger.debug("aim-ai-health-info exit #{code}: #{out}")
        {:error, {:exit, code}}
    end
  rescue
    e -> {:error, e}
  end

  defp binary_path do
    System.get_env("AIM_AI_HEALTH_BIN")
    || resolve_relative()
    || "aim-ai-health-info"
  end

  defp resolve_relative do
    cwd = File.cwd!()

    [
      Path.join([cwd, "..", "rust-core", "target", "release", "aim-ai-health-info"]),
      Path.join([cwd, "..", "rust-core", "target", "debug", "aim-ai-health-info"])
    ]
    |> Enum.find(&File.exists?/1)
  end

  defp normalise(%{"score" => s, "trend" => t, "regression" => r}) do
    %{
      total: s["total"] || 0,
      grade: s["grade"] || "F",
      components: s["components"] || %{},
      notes: s["notes"] || [],
      trend: %{
        n_runs: t["n_runs"] || 0,
        avg_compliance: t["avg_compliance"] || 0.0,
        avg_crit: t["avg_crit"] || 0.0,
        retry_share: t["retry_share"] || 0.0,
        first_ts: t["first_ts"],
        last_ts: t["last_ts"],
        grade_dist: t["grade_dist"] || %{}
      },
      regression: %{
        have_baseline: r["have_baseline"] || false,
        regressed: r["regressed"] || false,
        improved: r["improved"] || false,
        new_count: r["new_findings_count"] || 0,
        fixed_count: r["fixed_findings_count"] || 0,
        prev_grade: r["prev_grade"],
        curr_grade: r["curr_grade"],
        prev_crit: r["prev_crit"],
        curr_crit: r["curr_crit"]
      }
    }
  end

  defp normalise(_), do: %{}
end
