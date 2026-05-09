defmodule AimWeb.HealthLive do
  @moduledoc """
  Public health / observability dashboard. Route `/health`. Probes:

    - Phoenix uptime
    - `aim-llm` HTTP service (`:8770/health` + `/v1/providers`)
    - 7 cornerstone Rust binaries (`aim-pam`, `aim-coach`,
      `aim-codesign`, `aim-disagreement`, `aim-interactions`,
      `aim-regimen-validator`, `aim-smart-routing`) — checks file
      existence + `--help` exit-zero.

  Refreshes every 15 s.
  """
  use AimWeb, :live_view

  @refresh_ms 15_000
  @aim_llm_url "http://127.0.0.1:8770"

  def mount(_params, _session, socket) do
    if connected?(socket), do: :timer.send_interval(@refresh_ms, :tick)

    {:ok,
     socket
     |> assign(:page_title, "Health")
     |> assign(:status, %{})
     |> assign(:last_refresh, nil)
     |> probe()}
  end

  def handle_info(:tick, socket), do: {:noreply, probe(socket)}

  # ── probes ─────────────────────────────────────────────────────────────

  defp aim_root, do: System.get_env("AIM_ROOT") || "/home/oem/Desktop/LongevityCommon/AIM"

  defp probe(socket) do
    cornerstone_bins = [
      "aim-pam", "aim-coach", "aim-codesign", "aim-disagreement",
      "aim-interactions", "aim-regimen-validator", "aim-smart-routing",
      "aim-reflexion", "aim-llm"
    ]

    bins =
      Enum.map(cornerstone_bins, fn name ->
        path = Path.join([aim_root(), "rust-core", "target", "release", name])
        present = File.exists?(path)
        runs =
          if present do
            try do
              case System.cmd(path, ["--help"], stderr_to_stdout: true) do
                {_out, 0} -> true
                _ -> false
              end
            catch
              _, _ -> false
            end
          else
            false
          end
        %{name: name, present: present, runs: runs}
      end)

    {llm_ok, llm_providers, llm_ready_count} = probe_aim_llm()

    status = %{
      phoenix_uptime_s: System.system_time(:second) - boot_time(),
      aim_llm_reachable: llm_ok,
      aim_llm_providers: llm_providers,
      aim_llm_ready_count: llm_ready_count,
      binaries: bins,
      cornerstone_present_count: Enum.count(bins, & &1.present),
      cornerstone_total: length(cornerstone_bins)
    }

    socket
    |> assign(:status, status)
    |> assign(:last_refresh, DateTime.utc_now())
  end

  defp probe_aim_llm do
    try do
      url = String.to_charlist("#{@aim_llm_url}/v1/providers")
      :inets.start()

      case :httpc.request(:get, {url, []},
             [timeout: 2_000, connect_timeout: 1_000], []) do
        {:ok, {{_v, 200, _r}, _h, body}} ->
          case Jason.decode(IO.iodata_to_binary(body)) do
            {:ok, providers} when is_list(providers) ->
              ready = Enum.count(providers, &Map.get(&1, "ready", false))
              {true, providers, ready}

            _ ->
              {true, [], 0}
          end

        _ ->
          {false, [], 0}
      end
    catch
      _, _ -> {false, [], 0}
    end
  end

  defp boot_time do
    {epoch_us, _} = :erlang.statistics(:wall_clock)
    System.system_time(:second) - div(epoch_us, 1_000)
  end

  # ── render ─────────────────────────────────────────────────────────────

  def render(assigns) do
    ~H"""
    <div class="aim-health container mx-auto px-4 py-8 max-w-4xl">
      <h1>🩺 Health</h1>

      <p class="lead">
        Live status of the AIM stack. Auto-refresh every 15 s.
      </p>

      <section class="about-section">
        <h2>aim-llm Rust HTTP service (:8770)</h2>
        <%= if @status[:aim_llm_reachable] do %>
          <p>
            <strong>✅ Reachable.</strong> Providers ready:
            <strong><%= @status[:aim_llm_ready_count] %></strong>
            of <%= length(@status[:aim_llm_providers] || []) %>
          </p>
          <ul>
            <li :for={p <- @status[:aim_llm_providers] || []}>
              <%= if Map.get(p, "ready", false), do: "✅", else: "⚪" %>
              <strong><%= p["id"] %></strong> —
              <code><%= p["default_model"] %></code>
            </li>
          </ul>
        <% else %>
          <p>
            <strong>🚫 Unreachable</strong> at <code><%= @aim_llm_url %></code>.
            Start with <code>./rust-core/target/release/aim-llm</code> or
            via <code>systemctl --user start aim-llm</code>.
          </p>
        <% end %>
      </section>

      <section class="about-section">
        <h2>Cornerstone Rust binaries</h2>
        <p>
          Built: <strong><%= @status[:cornerstone_present_count] %></strong>
          of <%= @status[:cornerstone_total] %>.
          Each must respond to <code>--help</code> with exit-zero.
        </p>
        <table class="about-table">
          <thead>
            <tr><th>Binary</th><th>Built</th><th>Runs</th></tr>
          </thead>
          <tbody>
            <tr :for={b <- @status[:binaries] || []}>
              <td><code><%= b.name %></code></td>
              <td><%= if b.present, do: "✅", else: "⛔" %></td>
              <td><%= if b.runs, do: "✅", else: "⛔" %></td>
            </tr>
          </tbody>
        </table>
      </section>

      <section class="about-section">
        <h2>Cornerstone routes (this Phoenix instance)</h2>
        <p>
          All 7 routes are implemented and tested
          (<code>apps/aim_web/test/cornerstone_live_test.exs</code> +
          <code>apps/aim_web/test/about_live_test.exs</code> = 13 tests).
        </p>
        <ul>
          <li><a href="/about">/about</a> — comprehensive English description</li>
          <li><a href="/pam">/pam</a> — PAM-13 cohort</li>
          <li>/pam/:patient_id — per-patient PAM trajectory</li>
          <li>/codesign/:patient_id — co-design event log</li>
          <li><a href="/disagreement">/disagreement</a> — Blumenthal-Lee 4-zone classifier</li>
          <li><a href="/activation">/activation</a> — activation funnel</li>
          <li>/coaching/:patient_id — motivational interviewing OARS</li>
        </ul>
      </section>

      <section class="about-section">
        <h2>Asimov kernel laws (immutable contract)</h2>
        <p>
          8 laws active in production: L0 (danger) · L1 (patient harm) ·
          L2 (override compliance) · L3 (destructive) · L_PRIVACY ·
          L_CONSENT · L_VERIFIABILITY · L_AGENCY (co-design gate).
          Threshold values cannot be modified without explicit human
          instruction (see <code>CLAUDE.md</code> § IMMUTABLE).
        </p>
      </section>

      <footer :if={@last_refresh}>
        <small>
          Refreshed: <%= Calendar.strftime(@last_refresh, "%Y-%m-%d %H:%M:%S UTC") %>
          · Phoenix uptime: <%= format_uptime(@status[:phoenix_uptime_s] || 0) %>
        </small>
      </footer>
    </div>
    """
  end

  defp format_uptime(s) when is_integer(s) and s > 0 do
    days = div(s, 86_400)
    hours = div(rem(s, 86_400), 3600)
    mins = div(rem(s, 3600), 60)
    "#{days}d #{hours}h #{mins}m"
  end

  defp format_uptime(_), do: "?"
end
