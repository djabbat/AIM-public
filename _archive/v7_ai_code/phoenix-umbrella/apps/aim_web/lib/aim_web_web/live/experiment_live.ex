defmodule AimWeb.ExperimentLive do
  @moduledoc """
  Experiment lifecycle dashboard (Phase B, HW1, 2026-05-06).

  Lists experiments (`USER/experiments/*.yaml`) — phase, hot milestones,
  overdue follow-ups, daily checks. Data source: Rust binary
  `aim-experiment-owner` via `System.cmd/3`.

  Refreshes every 60s (slower than patient_live — experiment briefs are
  typically smaller and change less often).
  """
  use AimWeb, :live_view

  @refresh_ms 60_000

  def mount(_params, _session, socket) do
    if connected?(socket), do: :timer.send_interval(@refresh_ms, :tick)

    {:ok,
     socket
     |> assign(:experiments, [])
     |> assign(:last_refresh, nil)
     |> load_experiments()}
  end

  def handle_info(:tick, socket), do: {:noreply, load_experiments(socket)}

  defp load_experiments(socket) do
    socket
    |> assign(:experiments, fetch_experiments())
    |> assign(:last_refresh, DateTime.utc_now())
  end

  defp aim_root, do: System.get_env("AIM_ROOT") || "/home/oem/Desktop/LongevityCommon/AIM"

  defp experiment_owner_bin do
    [
      Path.join([aim_root(), "rust-core", "target", "release", "aim-experiment-owner"]),
      Path.join([aim_root(), "rust-core", "target", "debug", "aim-experiment-owner"])
    ]
    |> Enum.find(&File.exists?/1)
  end

  defp fetch_experiments do
    case experiment_owner_bin() do
      nil ->
        []

      bin ->
        env = [{"AIM_EXPERIMENTS_DIR", Path.join([aim_root(), "USER", "experiments"])}]

        with {names_str, 0} <- System.cmd(bin, ["list"], env: env),
             names <- names_str |> String.split("\n", trim: true) do
          today = Date.utc_today() |> Date.to_iso8601()

          Enum.map(names, fn name ->
            brief = case System.cmd(bin, ["brief", name, today], env: env) do
              {b, 0} -> b
              _ -> "(unable to render brief for #{name})"
            end

            phase = case System.cmd(bin, ["phase", name], env: env) do
              {p, 0} -> p |> String.trim()
              _ -> "?"
            end

            %{
              name: name,
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

  defp count_in_brief(brief, marker) do
    case Regex.run(~r/#{Regex.escape(marker)}[^\(]*\((\d+)\)/, brief) do
      [_, n] -> String.to_integer(n)
      _ -> 0
    end
  end

  def render(assigns) do
    ~H"""
    <div class="aim-experiments">
      <h1>🔬 Experiments</h1>

      <p :if={@experiments == []} class="empty">
        (no experiments configured at USER/experiments/*.yaml,
         or aim-experiment-owner binary not built)
      </p>

      <ul class="experiment-list">
        <li :for={e <- @experiments} class={"phase phase-#{String.downcase(e.phase)}"}>
          <header>
            <strong><%= e.name %></strong>
            <span class={"phase-badge phase-#{String.downcase(e.phase)}"}>
              <%= e.phase %>
            </span>
            <span :if={e.hot_count > 0} class="badge badge-hot">
              🔥 <%= e.hot_count %>
            </span>
            <span :if={e.overdue_count > 0} class="badge badge-overdue">
              📮 <%= e.overdue_count %>
            </span>
          </header>
          <pre class="brief"><%= e.brief %></pre>
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
