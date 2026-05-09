defmodule AimWebWeb.AuditLive do
  @moduledoc """
  Recent AIM_FS event feed (created / approved / rejected / disputed /
  sweeper_run / link_added / dispute_resolved / cascade_stale).

  Mounted at `/fs/audit`. Refreshes every 5 seconds via PubSub on
  `inbox:<tenant>` plus a periodic timer for sweeper-class events that
  don't broadcast.
  """
  use AimWebWeb, :live_view
  alias AimMemory.FS

  @impl true
  def mount(_params, session, socket) do
    tenant_id = session["user_id"] || "djabbat"

    if connected?(socket) do
      Phoenix.PubSub.subscribe(AIM.PubSub, "inbox:#{tenant_id}")
      :timer.send_interval(5_000, self(), :tick)
    end

    {:ok, socket |> assign(:tenant_id, tenant_id) |> reload()}
  end

  @impl true
  def handle_info(:tick, socket), do: {:noreply, reload(socket)}
  def handle_info(_, socket), do: {:noreply, reload(socket)}

  defp reload(socket) do
    case FS.list_events(socket.assigns.tenant_id, 100) do
      {:ok, events} -> assign(socket, :events, events)
      _ -> assign(socket, :events, [])
    end
  end

  @impl true
  def render(assigns) do
    ~H"""
    <div class="audit">
      <h1>Audit · last <%= length(@events) %> events</h1>
      <p class="meta">Auto-refreshes every 5s. Approve/reject/propose events
        push immediately via PubSub.</p>

      <table class="events">
        <thead>
          <tr>
            <th>when</th>
            <th>event</th>
            <th>entity</th>
            <th>schema</th>
            <th>payload</th>
          </tr>
        </thead>
        <tbody>
          <%= for ev <- @events do %>
            <tr class={"event-#{ev["event_type"]}"}>
              <td><code><%= ev["created_at"] %></code></td>
              <td><span class={"badge ev-#{ev["event_type"]}"}><%= ev["event_type"] %></span></td>
              <td>
                <%= if ev["entity_id"] do %>
                  <a href={"/fs/entity/#{ev["entity_id"]}"}>
                    <%= String.slice(ev["entity_id"], 0, 8) %>
                  </a>
                  <%= if ev["entity_title"] do %>
                    <small><%= String.slice(ev["entity_title"], 0, 40) %></small>
                  <% end %>
                <% end %>
              </td>
              <td><small><%= ev["entity_schema"] %></small></td>
              <td>
                <%= if ev["payload"] do %>
                  <code><%= String.slice(ev["payload"], 0, 80) %></code>
                <% end %>
              </td>
            </tr>
          <% end %>
        </tbody>
      </table>
    </div>

    <style>
      .audit { max-width: 1024px; margin: 1.5rem auto; font-family: system-ui; }
      .audit h1 { font-size: 1.4rem; }
      .audit .meta { color: #666; font-size: .85em; }
      .audit table.events { width: 100%; border-collapse: collapse; font-size: .85em; }
      .audit table.events th { text-align: left; padding: .25rem .5rem; border-bottom: 2px solid #ccc; }
      .audit table.events td { padding: .15rem .5rem; border-bottom: 1px dashed #eee; }
      .audit .badge { padding: 0 .35rem; border-radius: 3px; font-size: .85em; }
      .audit .ev-created       { background: #efe; color: #383; }
      .audit .ev-auto_approved { background: #efe; color: #383; }
      .audit .ev-approved      { background: #efe; color: #383; }
      .audit .ev-rejected      { background: #fee; color: #833; }
      .audit .ev-disputed      { background: #ffe; color: #883; }
      .audit .ev-superseded    { background: #f0f0f0; color: #666; }
      .audit .ev-link_added    { background: #fff5d8; color: #884; }
      .audit .ev-sweeper_run   { background: #eef; color: #338; }
      .audit .ev-dispute_resolved { background: #efe; color: #383; }
      .audit .ev-cascade_stale { background: #f5e0e0; color: #844; }
    </style>
    """
  end
end
