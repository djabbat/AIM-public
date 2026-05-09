defmodule AimWebWeb.FsDashboardLive do
  @moduledoc """
  Combined homepage for AIM_FS — gives the doctor a single-page view of:
  inbox queue depth, recent decisions, project counts, search box, quick links.
  Mounted at `/fs`.
  """
  use AimWebWeb, :live_view
  alias AimMemory.FS

  @impl true
  def mount(_params, session, socket) do
    tenant_id = session["user_id"] || "djabbat"

    if connected?(socket) do
      Phoenix.PubSub.subscribe(AIM.PubSub, "inbox:#{tenant_id}")
    end

    {:ok, socket |> assign(:tenant_id, tenant_id) |> reload()}
  end

  @impl true
  def handle_info({:proposed, _}, socket), do: {:noreply, reload(socket)}
  def handle_info({:approved, _}, socket), do: {:noreply, reload(socket)}
  def handle_info({:rejected, _}, socket), do: {:noreply, reload(socket)}
  def handle_info({:dispute_resolved, _, _}, socket), do: {:noreply, reload(socket)}
  def handle_info(_, socket), do: {:noreply, socket}

  defp reload(socket) do
    profile =
      case FS.profile_view(socket.assigns.tenant_id) do
        {:ok, p} -> p
        _ -> %{"counts" => %{}, "recent_decisions" => [], "feedback_rules" => []}
      end

    pending =
      case FS.list_pending(socket.assigns.tenant_id, 10) do
        {:ok, items} -> items
        _ -> []
      end

    disputes =
      case FS.list_disputes(socket.assigns.tenant_id) do
        {:ok, items} -> items
        _ -> []
      end

    projects =
      case FS.list_projects(socket.assigns.tenant_id) do
        {:ok, items} -> items
        _ -> []
      end

    socket
    |> assign(:profile, profile)
    |> assign(:pending, pending)
    |> assign(:disputes, disputes)
    |> assign(:projects, projects)
  end

  @impl true
  def render(assigns) do
    ~H"""
    <div class="fs-dash">
      <h1>AIM_FS · <code><%= @tenant_id %></code></h1>

      <section class="counts">
        <a href="/inbox" class="card pending">
          <strong><%= length(@pending) %></strong>
          <span>pending</span>
        </a>
        <a href="/fs/disputes" class={"card disputes #{if length(@disputes) > 0, do: "warn"}"}>
          <strong><%= length(@disputes) %></strong>
          <span>disputes</span>
        </a>
        <a href="/fs/profile" class="card profile">
          <strong><%= @profile["counts"]["user_facts"] || 0 %></strong>
          <span>user facts</span>
        </a>
        <a href="/fs/profile" class="card feedback">
          <strong><%= @profile["counts"]["feedback_rules"] || 0 %></strong>
          <span>feedback rules</span>
        </a>
        <a href="/fs/projects" class="card projects">
          <strong><%= length(@projects) %></strong>
          <span>projects</span>
        </a>
        <a href="/fs/patients" class="card patients">
          <strong><%= @profile["counts"]["patients"] || 0 %></strong>
          <span>patients</span>
        </a>
      </section>

      <section class="quicklinks">
        <a href="/onboard">+ Create project / register patient</a>
        <a href="/fs/search">🔍 Search AIM_FS</a>
      </section>

      <%= if @pending != [] do %>
        <h2>Awaiting your approval (<%= length(@pending) %>)</h2>
        <ul class="pending">
          <%= for p <- Enum.take(@pending, 5) do %>
            <li>
              <span class="schema"><%= p["proposal_type"] %></span>
              <span class="rationale"><%= String.slice(p["rationale"] || "", 0, 100) %></span>
              <small>id: <code><%= String.slice(p["id"], 0, 8) %></code></small>
            </li>
          <% end %>
        </ul>
        <p><a href="/inbox">→ Review inbox</a></p>
      <% end %>

      <%= if @disputes != [] do %>
        <h2 class="warn">⚖ Disputes (<%= length(@disputes) %>)</h2>
        <p>Two contradicting facts await resolution. <a href="/fs/disputes">→ Resolve</a></p>
      <% end %>

      <h2>Recent decisions (top 10)</h2>
      <ul class="decisions">
        <%= for d <- Enum.take(@profile["recent_decisions"] || [], 10) do %>
          <li>
            <a href={"/fs/entity/#{d["id"]}"}>
              <span class="schema"><%= d["schema"] %></span>
              <%= d["title"] || "(no title)" %>
            </a>
          </li>
        <% end %>
      </ul>

      <h2>Top projects</h2>
      <ul class="projects">
        <%= for p <- Enum.take(@projects, 8) do %>
          <li>
            <a href={"/fs/projects/#{p["slug"]}"}>
              <strong><%= p["title"] || p["slug"] %></strong>
              <small><%= p["status"] || "" %></small>
            </a>
          </li>
        <% end %>
      </ul>
    </div>

    <style>
      .fs-dash { max-width: 980px; margin: 1.5rem auto; font-family: system-ui; }
      .fs-dash h1 { font-size: 1.4rem; }
      .fs-dash h2 { margin-top: 1.5rem; border-bottom: 1px solid #ccc; }
      .fs-dash h2.warn { color: #b00; border-bottom-color: #fcc; }
      .fs-dash section.counts { display: flex; gap: .75rem; flex-wrap: wrap; margin: 1rem 0; }
      .fs-dash .card {
        flex: 1 1 110px; padding: .75rem; border: 1px solid #ddd;
        border-radius: 6px; text-align: center; text-decoration: none; color: inherit;
        background: #fafafa;
      }
      .fs-dash .card:hover { background: #f0f0ff; }
      .fs-dash .card.warn { border-color: #d77; background: #fff8f8; }
      .fs-dash .card strong { display: block; font-size: 1.6rem; }
      .fs-dash .card span { font-size: .85em; color: #555; }
      .fs-dash section.quicklinks { display: flex; gap: 1rem; margin: 1rem 0; }
      .fs-dash section.quicklinks a {
        background: #333; color: white; padding: .5rem 1rem;
        text-decoration: none; border-radius: 6px;
      }
      .fs-dash ul.pending, .fs-dash ul.decisions, .fs-dash ul.projects { list-style: none; padding: 0; }
      .fs-dash ul.pending li { padding: .35rem; border-bottom: 1px dashed #eee; }
      .fs-dash ul.decisions li { padding: .25rem 0; }
      .fs-dash ul.projects li { padding: .25rem 0; }
      .fs-dash .schema {
        background: #eef; padding: 0 .35rem; border-radius: 3px;
        font-size: .8em; margin-right: .5rem;
      }
    </style>
    """
  end
end
