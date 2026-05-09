defmodule AimWebWeb.SearchLive do
  @moduledoc """
  Interactive search over AIM_FS entities. FTS5 BM25 ranking with optional
  project / patient / schema scope. Live updates as you type (debounced).
  """
  use AimWebWeb, :live_view
  alias AimMemory.FS

  @impl true
  def mount(_params, session, socket) do
    tenant_id = session["user_id"] || "djabbat"

    {:ok,
     socket
     |> assign(:tenant_id, tenant_id)
     |> assign(:q, "")
     |> assign(:project_id, "")
     |> assign(:schema, "")
     |> assign(:hits, [])
     |> assign(:elapsed_ms, 0)}
  end

  @impl true
  def handle_event("search", params, socket) do
    q = String.trim(params["q"] || "")
    project_id = String.trim(params["project_id"] || "")
    schema = String.trim(params["schema"] || "")

    if q == "" do
      {:noreply,
       socket
       |> assign(:q, q)
       |> assign(:project_id, project_id)
       |> assign(:schema, schema)
       |> assign(:hits, [])
       |> assign(:elapsed_ms, 0)}
    else
      scope = %{}
      scope = if project_id != "", do: Map.put(scope, :project_id, project_id), else: scope
      scope = if schema != "", do: Map.put(scope, :schema, schema), else: scope

      t0 = System.monotonic_time(:millisecond)

      hits =
        case FS.search(socket.assigns.tenant_id, q, scope, 30) do
          {:ok, items} -> items
          _ -> []
        end

      elapsed = System.monotonic_time(:millisecond) - t0

      {:noreply,
       socket
       |> assign(:q, q)
       |> assign(:project_id, project_id)
       |> assign(:schema, schema)
       |> assign(:hits, hits)
       |> assign(:elapsed_ms, elapsed)}
    end
  end

  @impl true
  def render(assigns) do
    ~H"""
    <div class="search">
      <h1>Search · AIM_FS</h1>

      <form phx-change="search" phx-submit="search">
        <div class="row">
          <input type="text" name="q" value={@q} placeholder="query (FTS5 BM25)" autofocus />
        </div>
        <div class="row inline">
          <input type="text" name="project_id" value={@project_id} placeholder="scope: project_id (e.g. LC_CDATA)" />
          <select name="schema">
            <option value="" selected={@schema == ""}>any schema</option>
            <option value="feedback_v1" selected={@schema == "feedback_v1"}>feedback</option>
            <option value="fact_v1" selected={@schema == "fact_v1"}>fact</option>
            <option value="user_fact_v1" selected={@schema == "user_fact_v1"}>user_fact</option>
            <option value="project_state_v1" selected={@schema == "project_state_v1"}>project_state</option>
            <option value="contact_v1" selected={@schema == "contact_v1"}>contact</option>
            <option value="reference_v1" selected={@schema == "reference_v1"}>reference</option>
            <option value="audit_v1" selected={@schema == "audit_v1"}>audit</option>
          </select>
        </div>
      </form>

      <%= if @q != "" do %>
        <p class="meta">
          <%= length(@hits) %> hits · <%= @elapsed_ms %> ms · ranking: BM25
        </p>
      <% end %>

      <ul class="hits">
        <%= for h <- @hits do %>
          <li>
            <header>
              <span class="score">★ <%= h["score"] %></span>
              <span class="schema"><%= h["schema"] %></span>
              <span class="status status-<%= h["status"] %>"><%= h["status"] %></span>
              <small><%= String.split(h["created_at"] || "", "T") |> List.first() %></small>
            </header>
            <p class="title"><%= h["title"] || "(no title)" %></p>
            <%= if h["snippet"] do %>
              <p class="snippet"><%= String.slice(h["snippet"], 0, 240) %></p>
            <% end %>
            <p class="id"><code><%= String.slice(h["id"] || "", 0, 12) %></code></p>
          </li>
        <% end %>
      </ul>
    </div>

    <style>
      .search { max-width: 880px; margin: 1.5rem auto; font-family: system-ui; }
      .search h1 { font-size: 1.4rem; }
      .search form .row { margin: .5rem 0; }
      .search form input[type=text] { width: 100%; padding: .4rem; }
      .search form .inline { display: flex; gap: .5rem; }
      .search form .inline input { flex: 2; }
      .search form .inline select { flex: 1; padding: .4rem; }
      .search .meta { color: #666; font-size: .9em; }
      .search ul.hits { list-style: none; padding: 0; }
      .search ul.hits li { border: 1px solid #e0e0e0; padding: .5rem; margin: .5rem 0; border-radius: 4px; }
      .search ul.hits header { display: flex; gap: .5rem; align-items: center; font-size: .8em; }
      .search .score { font-weight: 600; color: #4a4; }
      .search .schema { background: #eef; padding: 0 .35rem; border-radius: 3px; }
      .search .status { padding: 0 .35rem; border-radius: 3px; }
      .search .status-active { background: #efe; color: #383; }
      .search .status-pending { background: #ffe; color: #883; }
      .search .status-disputed { background: #fee; color: #833; }
      .search .title { font-weight: 600; margin: .25rem 0; }
      .search .snippet { color: #555; font-size: .9em; }
      .search .id { font-size: .75em; color: #999; }
    </style>
    """
  end
end
