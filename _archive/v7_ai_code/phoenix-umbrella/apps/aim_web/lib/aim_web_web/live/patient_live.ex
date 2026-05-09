defmodule AimWeb.PatientLive do
  @moduledoc """
  Patient lifecycle dashboard (Phase A, HW1, 2026-05-06).

  Lists managed patients (folders with `Patients/<id>/MEMORY.md`) with
  current phase, hot milestones, overdue follow-ups. Data source:
  Rust binary `aim-patient-owner` invoked via `System.cmd/3`. The
  binary parses MEMORY.md schema and renders the brief.

  No HTTP endpoint or PubSub — pure pull on tick. Refreshes every 30s.
  """
  use AimWeb, :live_view

  @refresh_ms 30_000

  def mount(_params, _session, socket) do
    if connected?(socket), do: :timer.send_interval(@refresh_ms, :tick)

    {:ok,
     socket
     |> assign(:patients, [])
     |> assign(:last_refresh, nil)
     |> load_patients()}
  end

  def handle_info(:tick, socket), do: {:noreply, load_patients(socket)}

  defp load_patients(socket) do
    socket
    |> assign(:patients, fetch_patients())
    |> assign(:last_refresh, DateTime.utc_now())
  end

  # ── data fetcher ───────────────────────────────────────────────────────

  defp aim_root, do: System.get_env("AIM_ROOT") || "/home/oem/Desktop/LongevityCommon/AIM"

  defp patient_owner_bin do
    [
      Path.join([aim_root(), "rust-core", "target", "release", "aim-patient-owner"]),
      Path.join([aim_root(), "rust-core", "target", "debug", "aim-patient-owner"])
    ]
    |> Enum.find(&File.exists?/1)
  end

  defp fetch_patients do
    case patient_owner_bin() do
      nil ->
        []

      bin ->
        env = [{"AIM_PATIENTS_DIR", Path.join(aim_root(), "Patients")}]

        with {ids_str, 0} <- System.cmd(bin, ["list"], env: env),
             ids <- ids_str |> String.split("\n", trim: true) do
          today = Date.utc_today() |> Date.to_iso8601()

          ids
          |> Enum.take(50)
          |> Enum.map(fn id ->
            brief = case System.cmd(bin, ["brief", id, today], env: env) do
              {b, 0} -> b
              _ -> "(unable to render brief for #{id})"
            end

            phase = case System.cmd(bin, ["phase", id], env: env) do
              {p, 0} -> p |> String.trim()
              _ -> "?"
            end

            %{
              id: id,
              phase: phase,
              brief: brief,
              hot_count: count_in_brief(brief, "🔥 hot milestones"),
              overdue_count: count_in_brief(brief, "📮 overdue")
            }
          end)
        else
          _ -> []
        end
    end
  rescue
    _ -> []
  end

  # Parse "🔥 hot milestones (N)" / "📮 overdue follow-ups (N)" lines.
  defp count_in_brief(brief, marker) do
    case Regex.run(~r/#{Regex.escape(marker)}[^\(]*\((\d+)\)/, brief) do
      [_, n] -> String.to_integer(n)
      _ -> 0
    end
  end

  # ── render ─────────────────────────────────────────────────────────────

  def render(assigns) do
    ~H"""
    <div class="aim-patients">
      <h1>🏥 Patients</h1>

      <p :if={@patients == []} class="empty">
        (no patients with MEMORY.md, or aim-patient-owner binary not built)
      </p>

      <ul class="patient-list">
        <li :for={p <- @patients} class={"phase phase-#{String.downcase(p.phase)}"}>
          <header>
            <strong><%= p.id %></strong>
            <span class={"phase-badge phase-#{String.downcase(p.phase)}"}>
              <%= p.phase %>
            </span>
            <span :if={p.hot_count > 0} class="badge badge-hot">
              🔥 <%= p.hot_count %>
            </span>
            <span :if={p.overdue_count > 0} class="badge badge-overdue">
              📮 <%= p.overdue_count %>
            </span>
          </header>
          <pre class="brief"><%= p.brief %></pre>
        </li>
      </ul>

      <footer :if={@last_refresh}>
        <small>
          Refreshed:
          <%= Calendar.strftime(@last_refresh, "%Y-%m-%d %H:%M:%S UTC") %>
        </small>
      </footer>
    </div>
    """
  end
end
