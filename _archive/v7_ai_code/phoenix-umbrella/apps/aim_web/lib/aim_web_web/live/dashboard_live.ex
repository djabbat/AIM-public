defmodule AimWeb.DashboardLive do
  @moduledoc """
  Project + KPI dashboard. Pulls aggregated state from the orchestrator
  (which talks to the Rust core over the gateway). Replaces the Python
  daily_brief.py terminal output for the GUI/web users.
  """
  use AimWeb, :live_view

  @refresh_ms 30_000

  def mount(_params, _session, socket) do
    if connected?(socket), do: :timer.send_interval(@refresh_ms, :tick)

    {:ok,
     socket
     |> assign(:projects, [])
     |> assign(:deadlines, [])
     |> assign(:health, %{status: "unknown", crates: 0, tests: 0})
     |> assign(:last_refresh, nil)
     |> load_dashboard()}
  end

  def handle_info(:tick, socket), do: {:noreply, load_dashboard(socket)}

  defp load_dashboard(socket) do
    projects = fetch_projects()
    deadlines = fetch_deadlines()
    health = fetch_health()

    socket
    |> assign(:projects, projects)
    |> assign(:deadlines, deadlines)
    |> assign(:health, health)
    |> assign(:last_refresh, DateTime.utc_now())
  end

  defp fetch_projects do
    case Orchestrator.dashboard_projects() do
      {:ok, list} -> list
      _ -> []
    end
  rescue
    _ -> []
  end

  defp fetch_deadlines do
    case Orchestrator.dashboard_deadlines() do
      {:ok, list} -> list
      _ -> []
    end
  rescue
    _ -> []
  end

  defp fetch_health do
    case Orchestrator.health_snapshot() do
      {:ok, h} -> h
      _ -> %{status: "down", crates: 0, tests: 0}
    end
  rescue
    _ -> %{status: "down", crates: 0, tests: 0}
  end

  def render(assigns) do
    ~H"""
    <div class="aim-dashboard">
      <h1><%= t("dashboard.heading", @locale) %></h1>

      <section class="health">
        <h2><%= t("dashboard.health", @locale) %></h2>
        <p>
          <span class={"status status-#{@health.status}"}>
            <%= @health.status %>
          </span>
          · <%= @health.crates %> crates
          · <%= @health.tests %> tests
        </p>
      </section>

      <section class="projects">
        <h2><%= t("dashboard.projects", @locale) %></h2>
        <ul>
          <li :for={p <- @projects}>
            <strong><%= p.name %></strong> ·
            <span class={"phase phase-#{p.phase}"}><%= p.phase %></span> ·
            <em>idle <%= p.idle_days %>d</em>
          </li>
          <li :if={@projects == []}><%= t("dashboard.no_projects", @locale) %></li>
        </ul>
      </section>

      <section class="deadlines">
        <h2><%= t("dashboard.deadlines", @locale) %></h2>
        <ul>
          <li :for={d <- @deadlines} class={"deadline-#{d.urgency}"}>
            <strong><%= d.title %></strong> · <%= d.due %>
          </li>
          <li :if={@deadlines == []}><%= t("dashboard.no_deadlines", @locale) %></li>
        </ul>
      </section>

      <footer :if={@last_refresh}>
        <small>
          <%= t("dashboard.refreshed", @locale) %>:
          <%= Calendar.strftime(@last_refresh, "%Y-%m-%d %H:%M:%S UTC") %>
        </small>
      </footer>
    </div>
    """
  end
end
