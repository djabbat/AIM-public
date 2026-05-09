defmodule AimWeb.PamLive do
  @moduledoc """
  PAM-13 patient activation dashboard (Phase 7+, 2026-05-07).

  Two modes:
  - `/pam`               — cohort view: list every patient with current
                            activation level (1-4) and latest Δ.
  - `/pam/:patient_id`   — trajectory view: full history JSONL for a
                            single patient.

  Data source: Rust binary `aim-pam` (subcommands `level`, `latest-delta`,
  `history`) invoked via `System.cmd/3`. Refreshes every 30 s.
  """
  use AimWeb, :live_view

  @refresh_ms 30_000

  def mount(%{"patient_id" => pid} = _params, _session, socket) do
    if connected?(socket), do: :timer.send_interval(@refresh_ms, :tick)

    {:ok,
     socket
     |> assign(:mode, :patient)
     |> assign(:patient_id, pid)
     |> assign(:last_refresh, nil)
     |> load_patient()}
  end

  def mount(_params, _session, socket) do
    if connected?(socket), do: :timer.send_interval(@refresh_ms, :tick)

    {:ok,
     socket
     |> assign(:mode, :cohort)
     |> assign(:rows, [])
     |> assign(:last_refresh, nil)
     |> load_cohort()}
  end

  def handle_info(:tick, %{assigns: %{mode: :cohort}} = socket),
    do: {:noreply, load_cohort(socket)}

  def handle_info(:tick, %{assigns: %{mode: :patient}} = socket),
    do: {:noreply, load_patient(socket)}

  # ── data fetchers ──────────────────────────────────────────────────────

  defp aim_root, do: System.get_env("AIM_ROOT") || "/home/oem/Desktop/LongevityCommon/AIM"

  defp pam_bin do
    [
      Path.join([aim_root(), "rust-core", "target", "release", "aim-pam"]),
      Path.join([aim_root(), "rust-core", "target", "debug", "aim-pam"])
    ]
    |> Enum.find(&File.exists?/1)
  end

  defp patients_dir, do: Path.join(aim_root(), "Patients")

  defp env, do: [{"AIM_PATIENTS_DIR", patients_dir()}]

  defp list_patient_ids do
    case File.ls(patients_dir()) do
      {:ok, names} ->
        names
        |> Enum.filter(fn n -> File.dir?(Path.join(patients_dir(), n)) end)
        |> Enum.reject(&(&1 in ["INBOX", "_archive"]))
        |> Enum.sort()

      _ ->
        []
    end
  end

  defp load_cohort(socket) do
    rows =
      case pam_bin() do
        nil ->
          []

        bin ->
          list_patient_ids()
          |> Enum.take(50)
          |> Enum.map(fn id -> patient_summary(bin, id) end)
      end

    socket
    |> assign(:rows, rows)
    |> assign(:last_refresh, DateTime.utc_now())
  end

  defp patient_summary(bin, id) do
    level =
      case System.cmd(bin, ["level", id, "--patients-dir", patients_dir()], env: env()) do
        {out, 0} -> out |> String.trim() |> Integer.parse() |> elem(0)
        _ -> 0
      end

    {label, delta} = latest_delta_or_blank(bin, id)
    %{id: id, level: level, delta: delta, label: label}
  end

  defp latest_delta_or_blank(bin, id) do
    case System.cmd(bin, ["latest-delta", id, "--patients-dir", patients_dir()], env: env()) do
      {out, 0} ->
        case Jason.decode(String.trim(out)) do
          {:ok, %{"label" => l, "delta" => d}} -> {l, d}
          _ -> {"insufficient_data", 0.0}
        end

      _ ->
        {"insufficient_data", 0.0}
    end
  end

  defp load_patient(socket) do
    pid = socket.assigns.patient_id

    history =
      case pam_bin() do
        nil ->
          []

        bin ->
          case System.cmd(bin, ["history", pid, "--patients-dir", patients_dir()], env: env()) do
            {out, 0} ->
              out
              |> String.split("\n", trim: true)
              |> Enum.map(&Jason.decode!/1)

            _ ->
              []
          end
      end

    {label, delta} =
      case pam_bin() do
        nil -> {"insufficient_data", 0.0}
        bin -> latest_delta_or_blank(bin, pid)
      end

    socket
    |> assign(:history, history)
    |> assign(:label, label)
    |> assign(:delta, delta)
    |> assign(:last_refresh, DateTime.utc_now())
  end

  # ── render ─────────────────────────────────────────────────────────────

  def render(%{mode: :cohort} = assigns) do
    ~H"""
    <div class="aim-pam">
      <h1>📊 PAM-13 cohort</h1>
      <p :if={@rows == []} class="empty">
        (no patients with PAM-13 history, or aim-pam binary not built)
      </p>

      <table :if={@rows != []} class="pam-cohort">
        <thead>
          <tr><th>Patient</th><th>Level</th><th>Latest Δ</th><th>Significance</th></tr>
        </thead>
        <tbody>
          <tr :for={r <- @rows} class={"level-#{r.level}"}>
            <td><a href={"/pam/#{r.id}"}><%= r.id %></a></td>
            <td><strong><%= r.level %></strong> <%= level_label(r.level) %></td>
            <td><%= delta_str(r.delta, r.label) %></td>
            <td><%= r.label %></td>
          </tr>
        </tbody>
      </table>

      <footer :if={@last_refresh}>
        <small>Refreshed: <%= Calendar.strftime(@last_refresh, "%Y-%m-%d %H:%M:%S UTC") %></small>
      </footer>
    </div>
    """
  end

  def render(%{mode: :patient} = assigns) do
    ~H"""
    <div class="aim-pam">
      <h1>📈 PAM-13 trajectory: <%= @patient_id %></h1>

      <p :if={@history == []} class="empty">
        (no administrations yet for this patient)
      </p>

      <p :if={@history != []}>
        Latest Δ: <strong><%= Float.round(@delta, 1) %></strong>
        — <em><%= @label %></em>
        (MCID 5.4, MDC 7.2)
      </p>

      <table :if={@history != []} class="pam-history">
        <thead>
          <tr><th>Date</th><th>Score</th><th>Level</th></tr>
        </thead>
        <tbody>
          <tr :for={a <- @history}>
            <td><%= a["date"] %></td>
            <td><%= Float.round(a["score"] * 1.0, 1) %></td>
            <td class={"level-#{a["level"]}"}>
              <strong><%= a["level"] %></strong> <%= level_label(a["level"]) %>
            </td>
          </tr>
        </tbody>
      </table>

      <p><a href={"/pam"}>← cohort</a> · <a href={"/codesign/#{@patient_id}"}>co-design events →</a></p>

      <footer :if={@last_refresh}>
        <small>Refreshed: <%= Calendar.strftime(@last_refresh, "%Y-%m-%d %H:%M:%S UTC") %></small>
      </footer>
    </div>
    """
  end

  defp level_label(0), do: "(no PAM-13 yet)"
  defp level_label(1), do: "(disengaged)"
  defp level_label(2), do: "(becoming aware)"
  defp level_label(3), do: "(taking action)"
  defp level_label(4), do: "(maintaining)"
  defp level_label(_), do: ""

  defp delta_str(_d, "insufficient_data"), do: "—"

  defp delta_str(d, _label) do
    sign = if d >= 0, do: "+", else: ""
    "#{sign}#{Float.round(d, 1)}"
  end
end
