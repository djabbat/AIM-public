defmodule AimWebWeb.ProjectActivityLive do
  @moduledoc """
  Per-project activity feed: every entity scoped to this project + recent
  events. Drilled-into from /fs/projects.
  """
  use AimWebWeb, :live_view
  alias AimMemory.FS

  @impl true
  def mount(%{"slug" => slug}, session, socket) do
    tenant_id = session["user_id"] || "djabbat"

    {:ok,
     socket
     |> assign(:tenant_id, tenant_id)
     |> assign(:slug, slug)
     |> reload()}
  end

  defp reload(socket) do
    case FS.project_activity(socket.assigns.tenant_id, socket.assigns.slug) do
      {:ok, a} -> assign(socket, :activity, a)
      _ -> assign(socket, :activity, nil)
    end
  end

  @impl true
  def render(assigns) do
    ~H"""
    <div class="project-activity">
      <p><a href="/fs/projects">← Projects</a></p>
      <h1><%= @slug %></h1>

      <%= if @activity do %>
        <%= if @activity["summary"]["title"] do %>
          <h2><%= @activity["summary"]["title"] %></h2>
        <% end %>
        <%= if @activity["summary"]["description"] do %>
          <p class="desc"><%= @activity["summary"]["description"] %></p>
        <% end %>

        <section class="counts">
          <div><strong><%= @activity["counts"]["feedback_rules"] %></strong> feedback rules</div>
          <div><strong><%= @activity["counts"]["project_state"] %></strong> project state</div>
          <div><strong><%= @activity["counts"]["audits"] %></strong> audits</div>
          <div><strong><%= @activity["counts"]["references"] %></strong> references</div>
          <div><strong><%= @activity["counts"]["other"] %></strong> other</div>
        </section>

        <h3>Entries (top 100)</h3>
        <ul class="entries">
          <%= for e <- @activity["entries"] do %>
            <li>
              <header>
                <span class="schema"><%= e["schema"] %></span>
                <span class={"status status-#{e["status"]}"}><%= e["status"] %></span>
                <small><%= String.split(e["created_at"] || "", "T") |> List.first() %></small>
              </header>
              <p class="title"><%= e["title"] || "(no title)" %></p>
              <%= if e["snippet"] do %>
                <p class="snippet"><%= String.slice(e["snippet"], 0, 200) %></p>
              <% end %>
            </li>
          <% end %>
        </ul>

        <h3>Recent events (top 50)</h3>
        <ul class="events">
          <%= for ev <- @activity["recent_events"] do %>
            <li>
              <span class="ev-type"><%= ev["event_type"] %></span>
              <code><%= String.slice(ev["entity_id"] || "", 0, 12) %></code>
              <small><%= ev["created_at"] %></small>
            </li>
          <% end %>
        </ul>
      <% else %>
        <p>(no data for <%= @slug %>)</p>
      <% end %>
    </div>

    <style>
      .project-activity { max-width: 980px; margin: 1.5rem auto; font-family: system-ui; }
      .project-activity h1 { font-size: 1.4rem; }
      .project-activity h2 { font-size: 1.1rem; margin-top: 0; }
      .project-activity h3 { margin-top: 1.5rem; border-bottom: 1px solid #ccc; }
      .project-activity .desc { color: #555; }
      .project-activity section.counts { display: flex; gap: 1rem; margin: 1rem 0; flex-wrap: wrap; }
      .project-activity section.counts > div { background: #f0f0f8; padding: .35rem .75rem; border-radius: 6px; }
      .project-activity ul.entries { list-style: none; padding: 0; }
      .project-activity ul.entries li { border: 1px solid #eee; padding: .4rem .6rem; margin: .35rem 0; border-radius: 4px; }
      .project-activity ul.entries header { display: flex; gap: .5rem; font-size: .8em; }
      .project-activity .schema { background: #eef; padding: 0 .35rem; border-radius: 3px; }
      .project-activity .status { padding: 0 .35rem; border-radius: 3px; }
      .project-activity .status-active { background: #efe; color: #383; }
      .project-activity .status-disputed { background: #fee; color: #833; }
      .project-activity .status-superseded { background: #f0f0f0; color: #888; }
      .project-activity .title { font-weight: 600; margin: .15rem 0; }
      .project-activity .snippet { color: #666; font-size: .85em; }
      .project-activity ul.events { list-style: none; padding: 0; font-family: monospace; font-size: .85em; }
      .project-activity ul.events li { padding: .15rem 0; border-bottom: 1px dashed #eee; }
      .project-activity .ev-type { display: inline-block; min-width: 6em; color: #666; }
    </style>
    """
  end
end
