defmodule AimWebWeb.ReplayLive do
  @moduledoc """
  Time-travel UI: shows entity-state snapshot at a chosen past timestamp by
  shelling out to `aim-fs-replay --json --until <ts>`. Verifies SPEC §13
  audit-trail / replay invariant interactively.
  """
  use AimWebWeb, :live_view

  @impl true
  def mount(_params, session, socket) do
    tenant_id = session["user_id"] || "djabbat"
    binary = System.get_env("AIM_FS_REPLAY_BIN") || "aim-fs-replay"
    aim_root = System.get_env("AIM_FS_ROOT") || Path.expand("~/.aim_fs")

    {:ok,
     socket
     |> assign(:tenant_id, tenant_id)
     |> assign(:binary, binary)
     |> assign(:aim_root, aim_root)
     |> assign(:until, default_until())
     |> assign(:snapshot, nil)
     |> assign(:elapsed_ms, 0)
     |> assign(:error, nil)}
  end

  @impl true
  def handle_event("replay", %{"until" => until}, socket) do
    do_replay(socket, until)
  end

  def handle_event("preset", %{"days" => d}, socket) do
    {:ok, dt} = DateTime.now("Etc/UTC")
    until = dt |> DateTime.add(-String.to_integer(d) * 86_400, :second) |> DateTime.to_iso8601()
    do_replay(socket, until)
  end

  defp do_replay(socket, until) do
    args = [
      "--aim-root", socket.assigns.aim_root,
      "--tenant-id", socket.assigns.tenant_id,
      "--until", until,
      "--json"
    ]

    t0 = System.monotonic_time(:millisecond)

    {result, error} =
      try do
        case System.cmd(socket.assigns.binary, args) do
          {out, 0} ->
            case Jason.decode(out) do
              {:ok, list} when is_list(list) -> {list, nil}
              _ -> {[], "decode failed"}
            end
          {err, code} -> {[], "exit=#{code}: #{err}"}
        end
      rescue
        e -> {[], Exception.message(e)}
      end

    elapsed = System.monotonic_time(:millisecond) - t0

    {:noreply,
     socket
     |> assign(:until, until)
     |> assign(:snapshot, result)
     |> assign(:elapsed_ms, elapsed)
     |> assign(:error, error)}
  end

  defp default_until do
    {:ok, dt} = DateTime.now("Etc/UTC")
    DateTime.to_iso8601(dt)
  end

  @impl true
  def render(assigns) do
    ~H"""
    <div class="replay">
      <h1>Replay · time-travel snapshot</h1>
      <p class="meta">
        Folds the events log up to a chosen timestamp and reconstructs the
        entity-state snapshot at that point in time. Verifies SPEC §13.
      </p>

      <form phx-submit="replay">
        <label>Until (RFC3339):
          <input type="text" name="until" value={@until} size="35" />
        </label>
        <button type="submit">Snapshot</button>
      </form>

      <div class="presets">
        Quick:
        <button phx-click="preset" phx-value-days="0">now</button>
        <button phx-click="preset" phx-value-days="1">1d ago</button>
        <button phx-click="preset" phx-value-days="7">1w ago</button>
        <button phx-click="preset" phx-value-days="30">30d ago</button>
        <button phx-click="preset" phx-value-days="90">90d ago</button>
      </div>

      <%= if @error do %>
        <p class="err">⚠ <%= @error %></p>
      <% end %>

      <%= if @snapshot do %>
        <p class="meta">
          <strong><%= length(@snapshot) %></strong> entities at <code><%= @until %></code>
          · replay took <%= @elapsed_ms %> ms
        </p>

        <% by_status = Enum.frequencies_by(@snapshot, & &1["status"]) %>
        <h3>By status</h3>
        <ul class="status-list">
          <%= for {st, n} <- by_status do %>
            <li><span class={"status status-#{st}"}><%= st %></span> <strong><%= n %></strong></li>
          <% end %>
        </ul>

        <h3>Snapshot (top 50)</h3>
        <table class="snap">
          <thead>
            <tr>
              <th>id</th><th>schema</th><th>status</th>
              <th>title</th><th>events</th><th>last_event</th>
            </tr>
          </thead>
          <tbody>
            <%= for e <- Enum.take(@snapshot, 50) do %>
              <tr>
                <td><code><%= String.slice(e["id"], 0, 8) %></code></td>
                <td><span class="schema"><%= e["schema"] %></span></td>
                <td><span class={"status status-#{e["status"]}"}><%= e["status"] %></span></td>
                <td><%= String.slice(e["title"] || "", 0, 50) %></td>
                <td><%= e["events_seen"] %></td>
                <td><small><%= String.split(e["last_event_at"] || "", "T") |> List.first() %></small></td>
              </tr>
            <% end %>
          </tbody>
        </table>
      <% end %>
    </div>

    <style>
      .replay { max-width: 1024px; margin: 1.5rem auto; font-family: system-ui; }
      .replay h1 { font-size: 1.4rem; }
      .replay form input { padding: .25rem; }
      .replay .presets { margin: .5rem 0; }
      .replay .presets button { margin-right: .25rem; padding: .25rem .5rem; }
      .replay .meta { color: #555; font-size: .9em; }
      .replay .err { color: #b00; }
      .replay table.snap { width: 100%; border-collapse: collapse; }
      .replay table.snap th, .replay table.snap td {
        text-align: left; padding: .25rem .5rem; border-bottom: 1px solid #eee;
      }
      .replay .schema { background: #eef; padding: 0 .35rem; border-radius: 3px; font-size: .85em; }
      .replay .status { padding: 0 .35rem; border-radius: 3px; font-size: .85em; }
      .replay .status-active { background: #efe; color: #383; }
      .replay .status-pending { background: #ffe; color: #883; }
      .replay .status-disputed { background: #fee; color: #833; }
      .replay .status-superseded { background: #f0f0f0; color: #888; }
      .replay ul.status-list { list-style: none; padding: 0; }
      .replay ul.status-list li { display: inline-block; margin-right: 1rem; }
    </style>
    """
  end
end
