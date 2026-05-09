defmodule AimWebWeb.InboxLive do
  @moduledoc """
  AIM_FS approval queue. Shows pending proposals and lets the user approve,
  edit, reject or defer each one. Per SPEC.md §4.1.
  """
  use AimWebWeb, :live_view
  alias AimMemory.FS

  @impl true
  def mount(_params, session, socket) do
    tenant_id = session["user_id"] || "djabbat"

    if connected?(socket) do
      Phoenix.PubSub.subscribe(AIM.PubSub, "inbox:#{tenant_id}")
    end

    {:ok,
     socket
     |> assign(:tenant_id, tenant_id)
     |> assign(:filter, :all)
     |> reload()}
  end

  @impl true
  def handle_event("approve", %{"id" => id}, socket) do
    actor = %{user_id: socket.assigns.tenant_id, session_id: nil}
    case FS.approve(socket.assigns.tenant_id, id, actor) do
      {:ok, _} ->
        {:noreply, socket |> put_flash(:info, "Approved.") |> reload()}
      {:error, e} ->
        {:noreply, put_flash(socket, :error, "Approve failed: #{inspect(e)}")}
    end
  end

  def handle_event("reject", %{"id" => id, "reason" => reason}, socket) do
    actor = %{user_id: socket.assigns.tenant_id, session_id: nil}
    case FS.reject(socket.assigns.tenant_id, id, actor, reason) do
      {:ok, _} ->
        {:noreply, socket |> put_flash(:info, "Rejected.") |> reload()}
      {:error, e} ->
        {:noreply, put_flash(socket, :error, "Reject failed: #{inspect(e)}")}
    end
  end

  def handle_event("filter", %{"f" => f}, socket) do
    {:noreply, socket |> assign(:filter, String.to_existing_atom(f)) |> reload()}
  end

  @impl true
  def handle_info({:approved, _}, socket), do: {:noreply, reload(socket)}
  def handle_info({:rejected, _}, socket), do: {:noreply, reload(socket)}
  def handle_info({:proposed, _outcome}, socket), do: {:noreply, reload(socket)}
  def handle_info({:dispute_resolved, _, _}, socket), do: {:noreply, reload(socket)}
  def handle_info(_, socket), do: {:noreply, socket}

  defp reload(socket) do
    case FS.list_pending(socket.assigns.tenant_id, 100) do
      {:ok, items} -> assign(socket, :items, filter_items(items, socket.assigns.filter))
      {:error, _}  -> assign(socket, :items, [])
    end
  end

  defp filter_items(items, :all), do: items
  defp filter_items(items, :feedback),
    do: Enum.filter(items, fn p -> get_in(p, ["proposal_type"]) == "create" end)
  defp filter_items(items, _), do: items

  @impl true
  def render(assigns) do
    ~H"""
    <div class="inbox">
      <h1>AIM Inbox · <%= length(@items) %> pending</h1>

      <nav class="filters">
        <button phx-click="filter" phx-value-f="all"      class={if @filter == :all, do: "on"}>All</button>
        <button phx-click="filter" phx-value-f="feedback" class={if @filter == :feedback, do: "on"}>User-facts</button>
      </nav>

      <ul class="items">
        <%= for p <- @items do %>
          <li>
            <header>
              <span class="schema"><%= p["proposal_type"] %></span>
              <small><%= p["created_at"] %></small>
            </header>
            <p class="rationale"><%= p["rationale"] || "—" %></p>
            <details>
              <summary>data</summary>
              <pre><%= p["proposed_data"] %></pre>
            </details>
            <div class="actions">
              <button phx-click="approve" phx-value-id={p["id"]}>✓ Approve</button>
              <button phx-click="reject"  phx-value-id={p["id"]} phx-value-reason="not relevant">✗ Reject</button>
            </div>
          </li>
        <% end %>
      </ul>
    </div>

    <style>
      .inbox { max-width: 880px; margin: 1.5rem auto; font-family: system-ui; }
      .inbox h1 { font-size: 1.4rem; }
      .filters button { margin-right: .5rem; padding: .25rem .75rem; }
      .filters button.on { background: #333; color: #fff; }
      .items { list-style: none; padding: 0; }
      .items li { border: 1px solid #ddd; padding: .75rem; margin: .5rem 0; border-radius: 6px; }
      .items header { display: flex; justify-content: space-between; }
      .schema { font-weight: 600; color: #555; }
      .rationale { color: #444; margin: .5rem 0; }
      details pre { background: #f6f6f6; padding: .5rem; font-size: .8em; overflow-x: auto; }
      .actions button { margin-right: .5rem; }
    </style>
    """
  end
end
