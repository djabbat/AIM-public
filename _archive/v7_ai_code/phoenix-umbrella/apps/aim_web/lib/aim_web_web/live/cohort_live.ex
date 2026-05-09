defmodule AimWeb.CohortLive do
  @moduledoc """
  Cohort dashboard for PAM-13 pilot (STRATEGY.md P1-2, peer-review-driven).

  Aggregates per-patient PAM-13 trajectory + co-design adherence + kernel
  violation tally + cost across `Patients/<id>/`. Zero-pilot mode shows
  thresholds (MCID 5.4 / MDC 7.2) + empty state explaining recruitment is
  the bottleneck (per Tkemaladze 2026 cornerstone primary-outcome metric).

  Backend: subprocess to `scripts/pilot_cohort_extract.py --json`. Per
  peer-review #3.1, NO dedicated Rust statistical crate — existing Python
  script is sufficient for N≤30 cohort.
  """
  use AimWeb, :live_view

  @refresh_ms 60_000

  def mount(_params, _session, socket) do
    if connected?(socket), do: :timer.send_interval(@refresh_ms, :tick)

    {:ok,
     socket
     |> assign(:cohort, nil)
     |> assign(:error, nil)
     |> assign(:last_refresh, nil)
     |> load_cohort()}
  end

  def handle_info(:tick, socket), do: {:noreply, load_cohort(socket)}
  def handle_event("refresh", _params, socket), do: {:noreply, load_cohort(socket)}

  defp aim_root, do: System.get_env("AIM_ROOT") || "/home/oem/Desktop/LongevityCommon/AIM"

  defp load_cohort(socket) do
    case fetch_cohort() do
      {:ok, c} ->
        socket
        |> assign(:cohort, c)
        |> assign(:error, nil)
        |> assign(:last_refresh, DateTime.utc_now())

      {:error, msg} ->
        socket
        |> assign(:cohort, nil)
        |> assign(:error, msg)
        |> assign(:last_refresh, DateTime.utc_now())
    end
  end

  defp fetch_cohort do
    script = Path.join([aim_root(), "scripts", "pilot_cohort_extract.py"])

    if File.exists?(script) do
      env = [{"AIM_PATIENTS_DIR", Path.join(aim_root(), "Patients")}]

      case System.cmd("python3", [script, "--json"], env: env, stderr_to_stdout: false) do
        {json, 0} ->
          case Jason.decode(json) do
            {:ok, c} -> {:ok, c}
            {:error, e} -> {:error, "JSON: #{inspect(e)}"}
          end

        {err, code} ->
          {:error, "exit #{code}: #{String.trim(err)}"}
      end
    else
      {:error, "script not found: #{script}"}
    end
  rescue
    e -> {:error, "exec error: #{inspect(e)}"}
  end

  def render(assigns) do
    ~H"""
    <div class="aim-cohort">
      <header class="cohort-header">
        <h1>📊 Pilot cohort (PAM-13)</h1>
        <button phx-click="refresh" type="button">↻ Refresh</button>
      </header>

      <%= if @error do %>
        <div class="cohort-error">
          <strong>Error:</strong> <pre><%= @error %></pre>
        </div>
      <% end %>

      <%= if @cohort do %>
        <div class="cohort-summary">
          <article class="card stat">
            <div class="stat-num"><%= @cohort["n_enrolled"] || 0 %></div>
            <div class="stat-label">enrolled</div>
            <div class="stat-target">target ≥30 by 2026-11-07</div>
          </article>

          <article class="card stat">
            <div class="stat-num"><%= @cohort["thresholds"]["mcid"] %></div>
            <div class="stat-label">MCID (Hibbard 2009)</div>
            <div class="stat-target">primary endpoint Δ</div>
          </article>

          <article class="card stat">
            <div class="stat-num"><%= @cohort["thresholds"]["mdc"] %></div>
            <div class="stat-label">MDC (Hibbard 2009)</div>
            <div class="stat-target">measurement noise floor</div>
          </article>

          <article class="card stat">
            <div class="stat-num">
              <%= @cohort["kernel_violations"] || "—" %>
            </div>
            <div class="stat-label">kernel violations</div>
            <div class="stat-target">target 0 critical</div>
          </article>
        </div>

        <%= if (@cohort["patients"] || []) == [] do %>
          <article class="card wide cohort-empty">
            <h2>No PAM-13 measurements recorded yet</h2>
            <p>
              Pilot recruitment is the dominant pre-publication blocker
              (per <a href="/about">cornerstone</a>: Tkemaladze J. (2026),
              <em>Longevity Horizon</em> 2(5),
              <a href="https://doi.org/10.65649/qqwva850">DOI 10.65649/qqwva850</a>).
              Once at least one patient has T0 + T1 PAM-13 measurements,
              that pair will appear here with MCID/MDC classification.
            </p>
            <p class="muted">
              Pre-flight checklist (<code>docs/operational/PILOT_PROTOCOL.md</code>):
              IRB-equivalent approval (Georgian Personal Data Protection Law 2014),
              consent forms (KA + RU + EN), drug-interactions DB extension to
              200+ pairs (per peer-review safety lock-in), trained physician(s).
            </p>
          </article>
        <% else %>
          <article class="card wide cohort-table">
            <h2>Per-patient trajectory <span class="count"><%= length(@cohort["patients"]) %></span></h2>
            <table>
              <thead>
                <tr>
                  <th>Patient</th>
                  <th>T0 score</th>
                  <th>T0 date</th>
                  <th>T1 score</th>
                  <th>T1 date</th>
                  <th>Δ</th>
                  <th>Class</th>
                  <th>Co-design events</th>
                  <th>Disagreements</th>
                </tr>
              </thead>
              <tbody>
                <tr :for={p <- @cohort["patients"]} class={"row class-#{p["classification"] || "unknown"}"}>
                  <td><code><%= p["patient_id"] %></code></td>
                  <td class="value"><%= fmt_score(p["t0_score"]) %></td>
                  <td><%= p["t0_date"] || "—" %></td>
                  <td class="value"><%= fmt_score(p["t1_score"]) %></td>
                  <td><%= p["t1_date"] || "—" %></td>
                  <td class="value delta"><%= fmt_delta(p["delta"]) %></td>
                  <td><span class={"class-badge class-#{p["classification"] || "unknown"}"}><%= p["classification"] || "—" %></span></td>
                  <td><%= p["codesign_count"] || 0 %></td>
                  <td><%= p["disagreement_count"] || 0 %></td>
                </tr>
              </tbody>
            </table>
          </article>
        <% end %>
      <% end %>

      <footer :if={@last_refresh} class="cohort-footer">
        <small>Refreshed <%= Calendar.strftime(@last_refresh, "%Y-%m-%d %H:%M:%S UTC") %></small>
      </footer>
    </div>
    """
  end

  defp fmt_score(nil), do: "—"
  defp fmt_score(s) when is_number(s), do: :erlang.float_to_binary(s / 1, decimals: 1)
  defp fmt_score(_), do: "—"

  defp fmt_delta(nil), do: "—"
  defp fmt_delta(d) when is_number(d) and d > 0, do: "+" <> fmt_score(d)
  defp fmt_delta(d), do: fmt_score(d)
end
