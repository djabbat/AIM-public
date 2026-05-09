defmodule AimWebWeb.DiagLive do
  @moduledoc """
  AIM AI diagnostic dashboard.

  Reads ledger / regression / health metrics from the canonical
  `aim-ai-health-info --json` Rust binary every 10 s. Fields:

  - 0–100 score with letter grade and 5-component breakdown
  - ledger trend (run count, avg compliance, retry share, first/last ts)
  - regression diff (new vs fixed findings, prev/curr grade & crit)
  """
  use AimWebWeb, :live_view

  alias AimWeb.AiClient

  @poll_ms 10_000

  @impl true
  def mount(_params, _session, socket) do
    if connected?(socket), do: :timer.send_interval(@poll_ms, :poll)

    {:ok,
     socket
     |> assign(:page_title, "AI · diagnostics")
     |> assign(:loading?, true)
     |> assign(:error, nil)
     |> assign(:snapshot, nil)
     |> refresh()}
  end

  @impl true
  def handle_info(:poll, socket), do: {:noreply, refresh(socket)}

  defp refresh(socket) do
    case AiClient.snapshot() do
      {:ok, m} ->
        socket
        |> assign(:loading?, false)
        |> assign(:error, nil)
        |> assign(:snapshot, m)

      {:error, e} ->
        socket
        |> assign(:loading?, false)
        |> assign(:error, "aim-ai-health-info: #{inspect(e)}")
    end
  end

  @impl true
  def render(assigns) do
    ~H"""
    <div class="container">
      <header class="hdr">
        <h1>📈 AI diagnostics</h1>
        <p class="lead">
          Snapshot of the closed-loop self-improvement ledger.
          Backed by <code>aim-ai-health-info</code> (Rust).
        </p>
      </header>

      <%= if @error do %>
        <section class="card err">
          <h2>error</h2>
          <p><%= @error %></p>
        </section>
      <% end %>

      <%= if @loading? and is_nil(@snapshot) do %>
        <section class="card"><p class="muted">loading…</p></section>
      <% else %>
        <%= render_snapshot(assigns) %>
      <% end %>
    </div>
    """
  end

  defp render_snapshot(assigns) do
    ~H"""
    <% s = @snapshot %>
    <div class="grid">
      <section class="card score-card">
        <h2>health score</h2>
        <div class="score">
          <span class={"big-grade grade-" <> String.downcase(s.grade)}><%= s.grade %></span>
          <span class="big-num"><%= s.total %><span class="dim">/100</span></span>
        </div>
        <div class="components">
          <div :for={{k, v} <- s.components} class="comp">
            <span class="comp-k"><%= k %></span>
            <span class="comp-v"><%= v %></span>
          </div>
        </div>
        <%= if s.notes != [] do %>
          <ul class="notes">
            <li :for={n <- s.notes}><%= n %></li>
          </ul>
        <% end %>
      </section>

      <section class="card">
        <h2>ledger trend</h2>
        <%= if s.trend.n_runs == 0 do %>
          <p class="muted">no diagnostic runs recorded yet</p>
        <% else %>
          <div class="kv"><span class="k">runs</span><span class="v num"><%= s.trend.n_runs %></span></div>
          <div class="kv"><span class="k">avg compliance</span><span class="v num"><%= percent(s.trend.avg_compliance) %></span></div>
          <div class="kv"><span class="k">avg crit</span><span class="v num"><%= round1(s.trend.avg_crit) %></span></div>
          <div class="kv"><span class="k">retry share</span><span class="v num"><%= percent(s.trend.retry_share) %></span></div>
          <div class="kv"><span class="k">first run</span><span class="v small mono"><%= s.trend.first_ts %></span></div>
          <div class="kv"><span class="k">last run</span><span class="v small mono"><%= s.trend.last_ts %></span></div>
        <% end %>
      </section>

      <section class="card">
        <h2>regression vs previous</h2>
        <%= if not s.regression.have_baseline do %>
          <p class="muted">no baseline yet — need at least 2 runs in the ledger</p>
        <% else %>
          <div class="kv">
            <span class="k">grade</span>
            <span class="v">
              <%= s.regression.prev_grade || "?" %> → <%= s.regression.curr_grade || "?" %>
            </span>
          </div>
          <div class="kv">
            <span class="k">crit</span>
            <span class="v num">
              <%= s.regression.prev_crit %> → <%= s.regression.curr_crit %>
            </span>
          </div>
          <div class="kv"><span class="k">new findings</span><span class="v num"><%= s.regression.new_count %></span></div>
          <div class="kv"><span class="k">fixed findings</span><span class="v num"><%= s.regression.fixed_count %></span></div>
          <%= cond do %>
            <% s.regression.regressed -> %>
              <p class="reg-warn">⚠ regressed — new critical issues this run</p>
            <% s.regression.improved -> %>
              <p class="reg-ok">✅ improved</p>
            <% true -> %>
              <p class="muted">= stable</p>
          <% end %>
        <% end %>
      </section>
    </div>
    """
  end

  defp percent(nil), do: "—"
  defp percent(n) when is_number(n), do: "#{trunc(n * 100)}%"
  defp percent(_), do: "—"

  defp round1(nil), do: "—"
  defp round1(n) when is_number(n), do: :erlang.float_to_binary(n / 1, decimals: 1)
  defp round1(_), do: "—"
end
