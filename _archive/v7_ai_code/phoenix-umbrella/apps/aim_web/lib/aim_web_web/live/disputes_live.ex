defmodule AimWebWeb.DisputesLive do
  @moduledoc """
  Conflict-resolution UI per SPEC §8. Lists every entity pair currently in
  `status = disputed` and lets the user pick a winner. The losing entity
  becomes `superseded`; the winner becomes `active`.
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
  def handle_event("choose", %{"winner" => winner, "loser" => loser}, socket) do
    actor = %{user_id: socket.assigns.tenant_id, session_id: nil}

    case FS.resolve_dispute(socket.assigns.tenant_id, winner, loser, actor) do
      {:ok, _} ->
        {:noreply, socket |> put_flash(:info, "Dispute resolved.") |> reload()}

      {:error, e} ->
        {:noreply, put_flash(socket, :error, "Failed: #{inspect(e)}")}
    end
  end

  @impl true
  def handle_info({:dispute_resolved, _, _}, socket), do: {:noreply, reload(socket)}
  def handle_info(_, socket), do: {:noreply, socket}

  defp reload(socket) do
    case FS.list_disputes(socket.assigns.tenant_id) do
      {:ok, items} -> assign(socket, :disputes, items)
      _ -> assign(socket, :disputes, [])
    end
  end

  @impl true
  def render(assigns) do
    ~H"""
    <div class="disputes">
      <h1>Disputes · <%= length(@disputes) %></h1>

      <%= if @disputes == [] do %>
        <p>✓ No active disputes. AIM_FS detected no contradicting facts.</p>
      <% end %>

      <%= for d <- @disputes do %>
        <article class="pair">
          <div class="side a">
            <h3>A · newer</h3>
            <p class="title"><%= d["a_title"] || "(no title)" %></p>
            <pre class="body"><%= d["a_body"] || "" %></pre>
            <p class="id"><code><%= d["a_id"] %></code></p>
            <button phx-click="choose"
                    phx-value-winner={d["a_id"]}
                    phx-value-loser={d["b_id"]}>
              ✓ A wins
            </button>
          </div>

          <div class="vs">contradicts</div>

          <div class="side b">
            <h3>B · older</h3>
            <p class="title"><%= d["b_title"] || "(no title)" %></p>
            <pre class="body"><%= d["b_body"] || "" %></pre>
            <p class="id"><code><%= d["b_id"] %></code></p>
            <button phx-click="choose"
                    phx-value-winner={d["b_id"]}
                    phx-value-loser={d["a_id"]}>
              ✓ B wins
            </button>
          </div>
        </article>
      <% end %>
    </div>

    <style>
      .disputes { max-width: 1024px; margin: 1.5rem auto; font-family: system-ui; }
      .disputes h1 { font-size: 1.4rem; }
      .disputes article.pair {
        display: grid;
        grid-template-columns: 1fr auto 1fr;
        gap: .75rem;
        align-items: center;
        border: 1px solid #e0c0c0;
        background: #fff8f8;
        border-radius: 6px;
        padding: .75rem;
        margin: .75rem 0;
      }
      .disputes .side { padding: .5rem; background: #fff; border: 1px solid #ddd; border-radius: 4px; }
      .disputes .vs { font-weight: 600; color: #b00; text-align: center; }
      .disputes .title { font-weight: 600; }
      .disputes pre.body { background: #f6f6f6; padding: .5rem; font-size: .85em; overflow: auto; max-height: 8em; }
      .disputes .id { font-size: .8em; color: #777; }
      .disputes button { padding: .25rem .75rem; }
    </style>
    """
  end
end
