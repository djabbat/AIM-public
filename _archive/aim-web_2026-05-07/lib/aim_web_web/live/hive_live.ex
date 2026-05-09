defmodule AimWebWeb.HiveLive do
  @moduledoc """
  Live dashboard for the AIM Hive worker / queen connection.

  Polls the local queen every 5s for healthz + status + recent updates,
  reads the local DP-budget state file written by `aim-dp::DpAccountant`
  (`~/.cache/aim/dp_accountant.json`), and renders both side by side.

  This is the first AIM web page outside the Python customtkinter GUI;
  the rest of the migration follows in the same `lib/aim_web_web/live/`
  tree. Pattern matches Ze/BioSense/FCLC simulator LiveViews.
  """
  use AimWebWeb, :live_view

  alias AimWeb.QueenClient

  @poll_ms 5_000

  @impl true
  def mount(_params, _session, socket) do
    if connected?(socket), do: :timer.send_interval(@poll_ms, :poll)

    {:ok,
     socket
     |> assign(:page_title, "Hive")
     |> assign(:queen_url, QueenClient.base_url())
     |> assign(:health, nil)
     |> assign(:status, nil)
     |> assign(:updates, [])
     |> assign(:dp, read_dp_state())
     |> assign(:errors, [])
     |> refresh()}
  end

  @impl true
  def handle_info(:poll, socket), do: {:noreply, refresh(socket)}

  defp refresh(socket) do
    health = QueenClient.healthz()
    status = QueenClient.status()
    updates = QueenClient.updates() |> normalise_updates()
    dp = read_dp_state()

    errors =
      [
        case health do
          {:error, e} -> "queen healthz: #{inspect(e)}"
          _ -> nil
        end,
        case status do
          {:error, e} -> "queen status: #{inspect(e)}"
          _ -> nil
        end
      ]
      |> Enum.reject(&is_nil/1)

    socket
    |> assign(:health, unwrap(health))
    |> assign(:status, unwrap(status))
    |> assign(:updates, updates)
    |> assign(:dp, dp)
    |> assign(:errors, errors)
  end

  defp unwrap({:ok, v}), do: v
  defp unwrap(_), do: nil

  defp normalise_updates({:ok, list}), do: list |> Enum.take(20)
  defp normalise_updates(_), do: []

  defp read_dp_state do
    path =
      System.get_env("AIM_DP_STATE")
      || Path.join([System.user_home!() || ".", ".cache", "aim", "dp_accountant.json"])

    with {:ok, body} <- File.read(path),
         {:ok, %{"total_epsilon" => spent, "budget" => budget}} <- Jason.decode(body) do
      remaining = max(0.0, budget - spent)
      pct = if budget > 0.0, do: min(1.0, spent / budget), else: 1.0

      %{
        spent: round_dec(spent, 4),
        budget: round_dec(budget, 4),
        remaining: round_dec(remaining, 4),
        pct: round_dec(pct, 3),
        present: true
      }
    else
      _ -> %{spent: 0.0, budget: 0.0, remaining: 0.0, pct: 0.0, present: false}
    end
  end

  defp round_dec(n, p) when is_number(n) do
    Float.round(n / 1, p)
  end

  defp round_dec(_, _), do: 0.0

  @impl true
  def render(assigns) do
    ~H"""
    <div class="container">
      <header class="hdr">
        <h1>🐝 Hive</h1>
        <p class="lead">
          Federated AIM agent intelligence — local worker view.
          Queen at <code><%= @queen_url %></code>.
        </p>
      </header>

      <%= if Enum.any?(@errors) do %>
        <section class="card err">
          <h2>connection issues</h2>
          <ul>
            <li :for={e <- @errors}><%= e %></li>
          </ul>
        </section>
      <% end %>

      <div class="grid">
        <section class="card">
          <h2>queen health</h2>
          <%= if @health do %>
            <div class="kv"><span class="k">status</span><span class="v ok"><%= @health["status"] %></span></div>
            <div class="kv"><span class="k">ts</span><span class="v"><%= @health["ts"] %></span></div>
          <% else %>
            <p class="muted">unreachable — make sure aim-hive-queen is running on <code><%= @queen_url %></code></p>
          <% end %>
        </section>

        <section class="card">
          <h2>queen state</h2>
          <%= if @status do %>
            <div class="kv"><span class="k">contributions</span><span class="v num"><%= @status["n_contributions"] %></span></div>
            <div class="kv"><span class="k">updates</span><span class="v num"><%= @status["n_updates"] %></span></div>
            <%= if Map.get(@status, "queen_summary") do %>
              <div class="kv">
                <span class="k">pending candidates</span>
                <span class="v num"><%= @status["queen_summary"]["candidates_pending"] || 0 %></span>
              </div>
            <% end %>
          <% else %>
            <p class="muted">admin status requires <code>AIM_HIVE_ADMIN_TOKEN</code></p>
          <% end %>
        </section>

        <section class="card">
          <h2>differential privacy budget</h2>
          <%= if @dp.present do %>
            <div class="kv"><span class="k">spent</span><span class="v num"><%= @dp.spent %></span></div>
            <div class="kv"><span class="k">remaining</span><span class="v num"><%= @dp.remaining %></span></div>
            <div class="kv"><span class="k">budget</span><span class="v num"><%= @dp.budget %></span></div>
            <div class="bar">
              <div class="bar-fill" style={"width: #{trunc(@dp.pct * 100)}%"}></div>
            </div>
            <p class="muted small"><%= trunc(@dp.pct * 100) %>% consumed</p>
          <% else %>
            <p class="muted">no DP state yet — accountant initialises on first <code>contribute()</code>.</p>
          <% end %>
        </section>
      </div>

      <section class="card donate">
        <h2>support AIM</h2>
        <p class="muted small">
          AIM is an open-source non-profit project from Georgia Longevity Alliance.
          The Hive infrastructure is hosted on community-funded servers.
        </p>
        <a class="donate-btn" href="https://longevity.ge/#donate" target="_blank" rel="noopener">
          ♥ Donate to GLA
        </a>
      </section>

      <section class="card">
        <h2>recent updates</h2>
        <%= if @updates == [] do %>
          <p class="muted">no updates yet. Queen publishes after distill detects ≥3 supporting workers.</p>
        <% else %>
          <table class="updates">
            <thead><tr><th>ts</th><th>kind</th><th>source_n</th><th>eval_delta</th><th>signature</th></tr></thead>
            <tbody>
              <tr :for={u <- @updates}>
                <td><%= u["ts"] %></td>
                <td><span class={"pill " <> u["kind"]}><%= u["kind"] %></span></td>
                <td class="num"><%= u["source_n"] %></td>
                <td class="num"><%= format_delta(u["eval_delta"]) %></td>
                <td class="mono small"><%= u["signature"] %></td>
              </tr>
            </tbody>
          </table>
        <% end %>
      </section>
    </div>
    """
  end

  defp format_delta(nil), do: "—"
  defp format_delta(n) when is_number(n), do: :erlang.float_to_binary(n / 1, decimals: 3)
  defp format_delta(other), do: to_string(other)
end
