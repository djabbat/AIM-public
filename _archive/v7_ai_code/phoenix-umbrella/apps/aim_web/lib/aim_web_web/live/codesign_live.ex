defmodule AimWeb.CodesignLive do
  @moduledoc """
  Patient co-design event log viewer (Phase 7+, 2026-05-07).

  Route `/codesign/:patient_id`. Shows the full JSONL of consulted /
  agreed / modified / refused / alternative events backed by the
  `aim-codesign` Rust binary. Refreshes every 30 s.
  """
  use AimWeb, :live_view

  @refresh_ms 30_000

  def mount(%{"patient_id" => pid}, _session, socket) do
    if connected?(socket), do: :timer.send_interval(@refresh_ms, :tick)

    {:ok,
     socket
     |> assign(:patient_id, pid)
     |> assign(:events, [])
     |> assign(:last_refresh, nil)
     |> load()}
  end

  def handle_info(:tick, socket), do: {:noreply, load(socket)}

  # ── data ───────────────────────────────────────────────────────────────

  defp aim_root, do: System.get_env("AIM_ROOT") || "/home/oem/Desktop/LongevityCommon/AIM"

  defp codesign_bin do
    [
      Path.join([aim_root(), "rust-core", "target", "release", "aim-codesign"]),
      Path.join([aim_root(), "rust-core", "target", "debug", "aim-codesign"])
    ]
    |> Enum.find(&File.exists?/1)
  end

  defp patients_dir, do: Path.join(aim_root(), "Patients")

  defp load(socket) do
    pid = socket.assigns.patient_id

    events =
      case codesign_bin() do
        nil ->
          []

        bin ->
          env = [{"AIM_PATIENTS_DIR", patients_dir()}]

          case System.cmd(bin, ["events", pid, "--patients-dir", patients_dir()], env: env) do
            {out, 0} ->
              out
              |> String.split("\n", trim: true)
              |> Enum.map(&Jason.decode!/1)
              |> Enum.reverse()

            _ ->
              []
          end
      end

    socket
    |> assign(:events, events)
    |> assign(:last_refresh, DateTime.utc_now())
  end

  # ── render ─────────────────────────────────────────────────────────────

  def render(assigns) do
    ~H"""
    <div class="aim-codesign">
      <h1>🤝 Co-design events: <%= @patient_id %></h1>

      <p :if={@events == []} class="empty">
        (no co-design events yet for this patient)
      </p>

      <ul :if={@events != []} class="codesign-events">
        <li :for={e <- @events} class={"kind-#{e["kind"]}"}>
          <header>
            <span class={"kind kind-#{e["kind"]}"}><%= kind_emoji(e["kind"]) %> <%= e["kind"] %></span>
            <span class="ts"><%= e["ts"] %></span>
            <span :if={e["decision_id"]} class="decision-id">↪ <%= e["decision_id"] %></span>
            <span class="by">by <%= e["by"] %></span>
          </header>
          <p class="topic"><strong><%= e["topic"] %></strong></p>
          <p :if={e["notes"] not in [nil, ""]} class="notes"><em><%= e["notes"] %></em></p>
        </li>
      </ul>

      <p><a href={"/pam/#{@patient_id}"}>← PAM trajectory</a></p>

      <footer :if={@last_refresh}>
        <small>Refreshed: <%= Calendar.strftime(@last_refresh, "%Y-%m-%d %H:%M:%S UTC") %></small>
      </footer>
    </div>
    """
  end

  defp kind_emoji("consulted"), do: "💬"
  defp kind_emoji("agreed"), do: "✅"
  defp kind_emoji("modified"), do: "✏️"
  defp kind_emoji("refused"), do: "🚫"
  defp kind_emoji("alternative"), do: "🔀"
  defp kind_emoji(_), do: "·"
end
