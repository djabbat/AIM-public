defmodule AimWebWeb.DashboardLive do
  @moduledoc """
  Consolidated AIM/AI dashboard. Shells out to `aim-ai-dashboard --json`
  every 15 s and renders one card per section.
  """
  use AimWebWeb, :live_view

  @poll_ms 15_000

  @impl true
  def mount(_params, _session, socket) do
    if connected?(socket), do: :timer.send_interval(@poll_ms, :poll)

    {:ok,
     socket
     |> assign(:page_title, "AI · dashboard")
     |> assign(:loading?, true)
     |> assign(:error, nil)
     |> assign(:sections, [])
     |> refresh()}
  end

  @impl true
  def handle_info(:poll, socket), do: {:noreply, refresh(socket)}

  defp refresh(socket) do
    case fetch_sections() do
      {:ok, list} ->
        socket
        |> assign(:loading?, false)
        |> assign(:error, nil)
        |> assign(:sections, list)

      {:error, e} ->
        socket
        |> assign(:loading?, false)
        |> assign(:error, "aim-ai-dashboard: #{inspect(e)}")
    end
  end

  defp fetch_sections do
    bin = binary_path()

    case System.cmd(bin, ["--json"], stderr_to_stdout: true) do
      {out, 0} ->
        case Jason.decode(out) do
          {:ok, %{"sections" => list}} when is_list(list) -> {:ok, list}
          _ -> {:ok, []}
        end

      {out, code} ->
        {:error, {:exit, code, out}}
    end
  rescue
    e -> {:error, e}
  end

  defp binary_path do
    System.get_env("AIM_AI_DASHBOARD_BIN")
    || resolve_relative()
    || "aim-ai-dashboard"
  end

  defp resolve_relative do
    cwd = File.cwd!()

    [
      Path.join([cwd, "..", "rust-core", "target", "release", "aim-ai-dashboard"]),
      Path.join([cwd, "..", "rust-core", "target", "debug", "aim-ai-dashboard"])
    ]
    |> Enum.find(&File.exists?/1)
  end

  @impl true
  def render(assigns) do
    ~H"""
    <div class="container">
      <header class="hdr">
        <h1>📊 AI dashboard</h1>
        <p class="lead">
          Consolidated state of every closed-loop AI module.
          Backed by <code>aim-ai-dashboard</code> (Rust).
        </p>
      </header>

      <%= if @error do %>
        <section class="card err">
          <h2>error</h2>
          <p><%= @error %></p>
        </section>
      <% end %>

      <%= if @loading? and @sections == [] do %>
        <section class="card"><p class="muted">loading…</p></section>
      <% else %>
        <div class="grid">
          <section :for={s <- @sections} class={"card section-card " <> ok_class(s["ok"])}>
            <h2>
              <%= if s["ok"], do: "✓", else: "✗" %>
              <%= s["title"] %>
            </h2>
            <pre class="section-body"><%= s["body"] %></pre>
            <%= if s["error"] do %>
              <p class="section-err"><%= s["error"] %></p>
            <% end %>
          </section>
        </div>
      <% end %>
    </div>
    """
  end

  defp ok_class(true), do: "ok"
  defp ok_class(_), do: "stale"
end
