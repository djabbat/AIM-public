defmodule AimWeb.ActivationLive do
  @moduledoc """
  Cohort PAM-13 activation funnel (Phase 7+, 2026-05-07).

  Route `/activation`. Aggregates current activation level (0-4)
  across all patients with `_pam_history.jsonl`, showing how many
  sit in each tier. Refreshes every 30 s.
  """
  use AimWeb, :live_view

  @refresh_ms 30_000

  def mount(_params, _session, socket) do
    if connected?(socket), do: :timer.send_interval(@refresh_ms, :tick)

    {:ok,
     socket
     |> assign(:counts, %{0 => 0, 1 => 0, 2 => 0, 3 => 0, 4 => 0})
     |> assign(:total, 0)
     |> assign(:last_refresh, nil)
     |> load()}
  end

  def handle_info(:tick, socket), do: {:noreply, load(socket)}

  # ── data ───────────────────────────────────────────────────────────────

  defp aim_root, do: System.get_env("AIM_ROOT") || "/home/oem/Desktop/LongevityCommon/AIM"

  defp pam_bin do
    [
      Path.join([aim_root(), "rust-core", "target", "release", "aim-pam"]),
      Path.join([aim_root(), "rust-core", "target", "debug", "aim-pam"])
    ]
    |> Enum.find(&File.exists?/1)
  end

  defp patients_dir, do: Path.join(aim_root(), "Patients")

  defp list_patient_ids do
    case File.ls(patients_dir()) do
      {:ok, names} ->
        names
        |> Enum.filter(fn n -> File.dir?(Path.join(patients_dir(), n)) end)
        |> Enum.reject(&(&1 in ["INBOX", "_archive"]))

      _ ->
        []
    end
  end

  defp load(socket) do
    {counts, total} =
      case pam_bin() do
        nil ->
          {%{0 => 0, 1 => 0, 2 => 0, 3 => 0, 4 => 0}, 0}

        bin ->
          ids = list_patient_ids()

          counts =
            Enum.reduce(ids, %{0 => 0, 1 => 0, 2 => 0, 3 => 0, 4 => 0}, fn id, acc ->
              level = level_for(bin, id)
              Map.update(acc, level, 1, &(&1 + 1))
            end)

          {counts, length(ids)}
      end

    socket
    |> assign(:counts, counts)
    |> assign(:total, total)
    |> assign(:last_refresh, DateTime.utc_now())
  end

  defp level_for(bin, id) do
    env = [{"AIM_PATIENTS_DIR", patients_dir()}]

    case System.cmd(bin, ["level", id, "--patients-dir", patients_dir()], env: env) do
      {out, 0} ->
        case Integer.parse(String.trim(out)) do
          {n, _} -> n
          _ -> 0
        end

      _ ->
        0
    end
  end

  # ── render ─────────────────────────────────────────────────────────────

  def render(assigns) do
    ~H"""
    <div class="aim-activation">
      <h1>🎯 Patient activation funnel</h1>
      <p>
        Total patients tracked: <strong><%= @total %></strong>
        · with PAM-13 history: <strong><%= @total - @counts[0] %></strong>
      </p>

      <table class="activation-funnel">
        <thead>
          <tr><th>Level</th><th>Label</th><th>Count</th><th>Share</th></tr>
        </thead>
        <tbody>
          <tr :for={lvl <- [4, 3, 2, 1, 0]} class={"level-#{lvl}"}>
            <td><strong><%= lvl %></strong></td>
            <td><%= level_label(lvl) %></td>
            <td><%= @counts[lvl] %></td>
            <td><%= share(@counts[lvl], @total) %>%</td>
          </tr>
        </tbody>
      </table>

      <p><a href={"/pam"}>view cohort →</a></p>

      <footer :if={@last_refresh}>
        <small>Refreshed: <%= Calendar.strftime(@last_refresh, "%Y-%m-%d %H:%M:%S UTC") %></small>
      </footer>
    </div>
    """
  end

  defp level_label(0), do: "no PAM-13 history"
  defp level_label(1), do: "L1 — disengaged & overwhelmed"
  defp level_label(2), do: "L2 — becoming aware"
  defp level_label(3), do: "L3 — taking action"
  defp level_label(4), do: "L4 — maintaining"

  defp share(_, 0), do: "0.0"
  defp share(n, total), do: Float.to_string(Float.round(n / total * 100, 1))
end
