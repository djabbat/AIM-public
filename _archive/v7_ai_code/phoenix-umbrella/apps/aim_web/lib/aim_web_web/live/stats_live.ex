defmodule AimWebWeb.StatsLive do
  @moduledoc """
  Aggregated AIM_FS analytics — entity counts, creation rate per week,
  by schema / status / source / scope, average approval latency.
  """
  use AimWebWeb, :live_view
  alias AimMemory.FS

  @impl true
  def mount(_params, session, socket) do
    tenant_id = session["user_id"] || "djabbat"
    {:ok, socket |> assign(:tenant_id, tenant_id) |> reload()}
  end

  defp reload(socket) do
    case FS.stats(socket.assigns.tenant_id) do
      {:ok, s} -> assign(socket, :stats, s)
      _ -> assign(socket, :stats, nil)
    end
  end

  @impl true
  def render(assigns) do
    ~H"""
    <div class="stats">
      <h1>AIM_FS · stats</h1>

      <%= if @stats do %>
        <section class="counts">
          <div class="card">
            <strong><%= @stats["total_entities"] %></strong>
            <span>entities</span>
          </div>
          <div class="card">
            <strong><%= @stats["events_total"] %></strong>
            <span>events</span>
          </div>
          <%= if @stats["avg_approval_latency_ms"] do %>
            <div class="card">
              <strong><%= Float.round(@stats["avg_approval_latency_ms"], 1) %></strong>
              <span>ms avg approval latency</span>
            </div>
          <% end %>
        </section>

        <h2>Creation per week (last 12)</h2>
        <% max_w = (@stats["creation_per_week"] || [])
                   |> Enum.map(fn [_w, n] -> n end) |> Enum.max(fn -> 1 end) %>
        <ul class="bars">
          <%= for [w, n] <- (@stats["creation_per_week"] || []) |> Enum.reverse() do %>
            <li>
              <span class="label"><%= w %></span>
              <span class="bar" style={"width: #{div(n * 240, max(max_w, 1))}px"}>
                <span class="count"><%= n %></span>
              </span>
            </li>
          <% end %>
        </ul>

        <div class="grid">
          <div>
            <h2>By schema</h2>
            <ul class="kv">
              <%= for [k, v] <- (@stats["by_schema"] || []) do %>
                <li><code><%= k %></code> <span><%= v %></span></li>
              <% end %>
            </ul>
          </div>

          <div>
            <h2>By status</h2>
            <ul class="kv">
              <%= for [k, v] <- (@stats["by_status"] || []) do %>
                <li>
                  <span class={"status status-#{k}"}><%= k %></span>
                  <span><%= v %></span>
                </li>
              <% end %>
            </ul>
          </div>

          <div>
            <h2>By source</h2>
            <ul class="kv">
              <%= for [k, v] <- (@stats["by_source"] || []) do %>
                <li><code><%= k %></code> <span><%= v %></span></li>
              <% end %>
            </ul>
          </div>

          <div>
            <h2>Top scopes (top 25)</h2>
            <ul class="kv">
              <%= for [k, v] <- (@stats["by_scope"] || []) do %>
                <li><code><%= String.slice(k, 0, 50) %></code> <span><%= v %></span></li>
              <% end %>
            </ul>
          </div>
        </div>
      <% else %>
        <p>(stats unavailable)</p>
      <% end %>
    </div>

    <style>
      .stats { max-width: 1024px; margin: 1.5rem auto; font-family: system-ui; }
      .stats h1 { font-size: 1.4rem; }
      .stats h2 { font-size: 1rem; margin-top: 1rem; border-bottom: 1px solid #ccc; }
      .stats section.counts { display: flex; gap: .75rem; margin: 1rem 0; }
      .stats .card {
        flex: 1; padding: .75rem; border: 1px solid #ddd;
        border-radius: 6px; text-align: center; background: #fafafa;
      }
      .stats .card strong { display: block; font-size: 1.6rem; }
      .stats .card span { font-size: .85em; color: #555; }
      .stats ul.bars { list-style: none; padding: 0; }
      .stats ul.bars li {
        display: flex; align-items: center; gap: .5rem; padding: .15rem 0;
      }
      .stats ul.bars .label { min-width: 5em; font-family: monospace; font-size: .85em; }
      .stats ul.bars .bar {
        background: #5a8; height: 18px; border-radius: 3px;
        display: inline-flex; align-items: center; padding: 0 .35rem;
      }
      .stats ul.bars .count { color: white; font-size: .8em; }
      .stats .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
      .stats ul.kv { list-style: none; padding: 0; font-size: .9em; }
      .stats ul.kv li { display: flex; justify-content: space-between; padding: .15rem 0; border-bottom: 1px dashed #eee; }
      .stats .status { padding: 0 .35rem; border-radius: 3px; }
      .stats .status-active { background: #efe; color: #383; }
      .stats .status-pending { background: #ffe; color: #883; }
      .stats .status-disputed { background: #fee; color: #833; }
      .stats .status-superseded { background: #f0f0f0; color: #888; }
    </style>
    """
  end
end
