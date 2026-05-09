defmodule AimWebWeb.ProjectsBrowserLive do
  @moduledoc """
  AIM_FS-backed projects browser. Lists user-defined projects under
  `<aim_root>/users/<u>/projects/` with title + description from CONCEPT.md.

  Distinct from the legacy `PatientLive` / `ExperimentLive` which read
  YAML files in the AIM repo. This one is the canonical view going forward.
  """
  use AimWebWeb, :live_view
  alias AimMemory.FS

  @impl true
  def mount(_params, session, socket) do
    user_id = session["user_id"] || "djabbat"
    {:ok, socket |> assign(:user_id, user_id) |> assign(:filter, "") |> reload()}
  end

  @impl true
  def handle_event("filter", %{"q" => q}, socket) do
    {:noreply, socket |> assign(:filter, q) |> reload()}
  end

  defp reload(socket) do
    case FS.list_projects(socket.assigns.user_id) do
      {:ok, items} ->
        filtered =
          if socket.assigns.filter != "" do
            f = String.downcase(socket.assigns.filter)
            Enum.filter(items, fn p ->
              String.contains?(String.downcase(p["slug"] || ""), f) or
                String.contains?(String.downcase(p["title"] || ""), f)
            end)
          else
            items
          end

        assign(socket, :projects, filtered)

      _ ->
        assign(socket, :projects, [])
    end
  end

  @impl true
  def render(assigns) do
    ~H"""
    <div class="projects-browser">
      <h1>Projects · <%= length(@projects) %></h1>

      <form phx-change="filter">
        <input type="text" name="q" value={@filter} placeholder="filter by slug/title" />
      </form>

      <ul class="cards">
        <%= for p <- @projects do %>
          <li>
            <h3><%= p["title"] || p["slug"] %></h3>
            <p class="slug"><code><%= p["slug"] %></code></p>
            <p class="desc"><%= String.slice(p["description"] || "", 0, 200) %></p>
            <p class="meta">
              status: <%= p["status"] || "—" %> ·
              created: <%= p["created_at"] || "—" %>
            </p>
            <p class="path"><code><%= p["path"] %></code></p>
          </li>
        <% end %>
      </ul>

      <p>
        <a href="/onboard">+ Create new project (guided onboarding)</a>
      </p>
    </div>

    <style>
      .projects-browser { max-width: 880px; margin: 1.5rem auto; font-family: system-ui; }
      .projects-browser h1 { font-size: 1.4rem; }
      .projects-browser form input { width: 100%; padding: .25rem .5rem; }
      .projects-browser ul.cards { list-style: none; padding: 0; }
      .projects-browser ul.cards li {
        border: 1px solid #ddd;
        padding: .75rem;
        margin: .5rem 0;
        border-radius: 6px;
      }
      .projects-browser .meta { font-size: .85em; color: #666; }
      .projects-browser .path { font-size: .8em; color: #999; }
    </style>
    """
  end
end
