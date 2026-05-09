defmodule AimWebWeb.EntityDetailLive do
  @moduledoc """
  Full entity detail page — body, links graph, event history, scope.
  Linked-from /fs/projects/:slug, /fs/profile, /fs/search.
  """
  use AimWebWeb, :live_view
  alias AimMemory.FS

  @impl true
  def mount(%{"id" => id}, session, socket) do
    tenant_id = session["user_id"] || "djabbat"

    {:ok,
     socket
     |> assign(:tenant_id, tenant_id)
     |> assign(:id, id)
     |> reload()}
  end

  defp reload(socket) do
    case FS.entity_detail(socket.assigns.tenant_id, socket.assigns.id) do
      {:ok, e} -> assign(socket, :entity, e)
      _ -> assign(socket, :entity, nil)
    end
  end

  @impl true
  def render(assigns) do
    ~H"""
    <div class="entity-detail">
      <p><a href="javascript:history.back()">← back</a></p>

      <%= if @entity do %>
        <h1><%= @entity["title"] || "(no title)" %></h1>
        <p class="meta">
          <span class={"status status-#{@entity["status"]}"}><%= @entity["status"] %></span>
          <span class="schema"><%= @entity["schema"] %> v<%= @entity["schema_version"] %></span>
          <code><%= @entity["id"] %></code>
        </p>

        <%= if @entity["description"] do %>
          <p class="desc"><%= @entity["description"] %></p>
        <% end %>

        <%= if @entity["body"] do %>
          <details open>
            <summary>Body (<%= String.length(@entity["body"]) %> chars)</summary>
            <pre><%= @entity["body"] %></pre>
          </details>
        <% end %>

        <h3>Provenance</h3>
        <ul class="meta-list">
          <li>source: <%= @entity["source"] %></li>
          <li>user_id: <%= @entity["user_id"] %></li>
          <%= if @entity["llm_model"] do %><li>llm: <%= @entity["llm_model"] %></li><% end %>
          <%= if @entity["confidence"] do %><li>confidence: <%= @entity["confidence"] %></li><% end %>
          <li>created_at: <%= @entity["created_at"] %></li>
          <li>updated_at: <%= @entity["updated_at"] %></li>
          <li>version: <%= @entity["version"] %></li>
        </ul>

        <h3>Scope</h3>
        <ul class="meta-list">
          <li>global: <%= @entity["scope_global"] %></li>
          <li>users: <%= Enum.join(@entity["scope_user_ids"] || [], ", ") %></li>
          <%= if @entity["scope_project_ids"] do %>
            <li>projects:
              <%= for p <- @entity["scope_project_ids"] do %>
                <a href={"/fs/projects/#{p}"}><code><%= p %></code></a>
              <% end %>
            </li>
          <% end %>
          <%= if @entity["scope_patient_ids"] != [] do %>
            <li>patients: <%= Enum.join(@entity["scope_patient_ids"], ", ") %></li>
          <% end %>
        </ul>

        <%= if @entity["tags"] != [] do %>
          <h3>Tags</h3>
          <div class="tags">
            <%= for t <- @entity["tags"] do %>
              <span class="tag"><%= t %></span>
            <% end %>
          </div>
        <% end %>

        <%= if @entity["outgoing_links"] != [] or @entity["incoming_links"] != [] do %>
          <h3>Links</h3>
          <%= if @entity["outgoing_links"] != [] do %>
            <h4>Outgoing</h4>
            <ul>
              <%= for l <- @entity["outgoing_links"] do %>
                <li>
                  <span class="link-type"><%= l["link_type"] %></span>
                  →
                  <a href={"/fs/entity/#{l["other_id"]}"}>
                    <%= l["other_title"] || String.slice(l["other_id"], 0, 12) %>
                  </a>
                </li>
              <% end %>
            </ul>
          <% end %>
          <%= if @entity["incoming_links"] != [] do %>
            <h4>Incoming</h4>
            <ul>
              <%= for l <- @entity["incoming_links"] do %>
                <li>
                  <a href={"/fs/entity/#{l["other_id"]}"}>
                    <%= l["other_title"] || String.slice(l["other_id"], 0, 12) %>
                  </a>
                  →
                  <span class="link-type"><%= l["link_type"] %></span>
                </li>
              <% end %>
            </ul>
          <% end %>
        <% end %>

        <%= if @entity["events"] != [] do %>
          <h3>Events (<%= length(@entity["events"]) %>)</h3>
          <ul class="events">
            <%= for ev <- @entity["events"] do %>
              <li>
                <code><%= ev["created_at"] %></code>
                <span class="ev-type"><%= ev["event_type"] %></span>
              </li>
            <% end %>
          </ul>
        <% end %>
      <% else %>
        <p>Entity not found: <code><%= @id %></code></p>
      <% end %>
    </div>

    <style>
      .entity-detail { max-width: 880px; margin: 1.5rem auto; font-family: system-ui; }
      .entity-detail h1 { font-size: 1.4rem; }
      .entity-detail h3 { margin-top: 1.5rem; border-bottom: 1px solid #ccc; }
      .entity-detail h4 { margin: .5rem 0; font-size: .95rem; color: #555; }
      .entity-detail .meta { display: flex; gap: .5rem; align-items: center; font-size: .9em; color: #555; }
      .entity-detail .schema { background: #eef; padding: 0 .35rem; border-radius: 3px; }
      .entity-detail .status { padding: 0 .35rem; border-radius: 3px; font-size: .85em; }
      .entity-detail .status-active { background: #efe; color: #383; }
      .entity-detail .status-pending { background: #ffe; color: #883; }
      .entity-detail .status-disputed { background: #fee; color: #833; }
      .entity-detail .status-superseded { background: #f0f0f0; color: #888; }
      .entity-detail pre {
        background: #f7f7f7; padding: .75rem; border-radius: 4px;
        white-space: pre-wrap; word-wrap: break-word; max-height: 30em; overflow: auto;
      }
      .entity-detail ul.meta-list { font-size: .9em; color: #555; }
      .entity-detail .tags .tag {
        display: inline-block; background: #e8e8f5; padding: .15rem .5rem;
        border-radius: 999px; font-size: .8em; margin-right: .25rem;
      }
      .entity-detail .link-type { background: #fff5d8; padding: 0 .35rem; border-radius: 3px; font-size: .85em; }
      .entity-detail ul.events { font-family: monospace; font-size: .85em; }
      .entity-detail .ev-type { color: #666; margin-left: .5rem; }
    </style>
    """
  end
end
