defmodule AimWeb.AdminLive do
  @moduledoc """
  Local control panel for AIM operator. Route `/admin`. Surfaces:

    - System status grid (Phoenix self / aim-llm :8770 / aim-rag :8771 /
      aim-hive-queen :8090 / aim-hive-telemetry binary / Ollama :11434)
    - Last full diagnostic + P0/P1/P2 counts (reads
      `docs/operational/diagnostic_latest.md` if present)
    - Hive worker last contribution timestamp + DP-budget remaining
    - Patient cohort size
    - Quick action buttons:
        • Run full diagnostic (spawns scripts/aim_full_diagnostic.py)
        • Trigger telemetry contribute (spawns aim-hive-telemetry contribute)
        • Open AIM_UI (browser)

  Refreshes every 5 s (status grid only — actions are user-triggered).
  Read-only by default; enable mutating actions with AIM_ADMIN_ENABLE=1
  in Phoenix env (otherwise buttons render disabled with explanation).
  """
  use AimWeb, :live_view

  @refresh_ms 5_000
  @aim_llm_url "http://127.0.0.1:8770"
  @aim_rag_url "http://127.0.0.1:8771"
  @aim_hive_queen_url "http://127.0.0.1:8090"
  @ollama_url "http://127.0.0.1:11434"

  def mount(_params, _session, socket) do
    if connected?(socket), do: :timer.send_interval(@refresh_ms, :tick)

    {:ok,
     socket
     |> assign(:page_title, "AIM Control Panel")
     |> assign(:enabled, System.get_env("AIM_ADMIN_ENABLE") == "1")
     |> assign(:last_refresh, nil)
     |> assign(:flash_msg, nil)
     |> probe()}
  end

  def handle_info(:tick, socket), do: {:noreply, probe(socket)}

  def handle_info({:flash_clear, ref}, socket) do
    if socket.assigns[:flash_ref] == ref do
      {:noreply, assign(socket, flash_msg: nil, flash_ref: nil)}
    else
      {:noreply, socket}
    end
  end

  def handle_event("run_diagnostic", _params, socket) do
    cond do
      not socket.assigns.enabled ->
        {:noreply, flash(socket, "ACTIONS DISABLED — set AIM_ADMIN_ENABLE=1 in Phoenix env to enable")}

      true ->
        spawn_action("scripts/aim_full_diagnostic.py", ["--md",
          "--out", Path.join(["docs", "operational", "diagnostic_latest.md"])])
        {:noreply, flash(socket, "✓ diagnostic kicked off — refresh in 10-15s for updated report")}
    end
  end

  def handle_event("contribute", _params, socket) do
    cond do
      not socket.assigns.enabled ->
        {:noreply, flash(socket, "ACTIONS DISABLED — set AIM_ADMIN_ENABLE=1")}

      true ->
        bin = Path.join([aim_root(), "rust-core", "target", "release", "aim-hive-telemetry"])
        spawn_action(bin, ["contribute"])
        {:noreply, flash(socket, "✓ aim-hive-telemetry contribute kicked off")}
    end
  end

  def render(assigns) do
    ~H"""
    <main class="container">
      <h1>AIM Control Panel</h1>
      <p class="section-lead">
        Local operator dashboard.  Refreshes every 5 s.
        Last refresh: <%= refresh_label(@last_refresh) %>.
        Mutating actions: <strong><%= if @enabled, do: "ENABLED", else: "disabled (read-only)" %></strong>.
      </p>

      <%= if @flash_msg do %>
        <div class="card" style="border-left: 4px solid #f59e0b; padding: 12px;">
          <%= @flash_msg %>
        </div>
      <% end %>

      <h2 class="section-title">Services</h2>
      <div class="grid">
        <%= for svc <- @status.services do %>
          <div class="card">
            <div class="role"><%= status_dot(svc.up) %> <%= svc.label %></div>
            <h3><%= svc.url %></h3>
            <p><%= svc.detail %></p>
          </div>
        <% end %>
      </div>

      <h2 class="section-title">Diagnostic — last run</h2>
      <div class="card">
        <p>
          <strong>P0:</strong> <%= @status.diagnostic.p0 %> ·
          <strong>P1:</strong> <%= @status.diagnostic.p1 %> ·
          <strong>P2:</strong> <%= @status.diagnostic.p2 %><br>
          <small><%= @status.diagnostic.note %></small>
        </p>
        <button phx-click="run_diagnostic" disabled={not @enabled}>
          Run full diagnostic
        </button>
      </div>

      <h2 class="section-title">Hive worker</h2>
      <div class="card">
        <p>
          Queen URL: <code><%= System.get_env("AIM_HIVE_QUEEN_URL") || "(not set — telemetry will fail)" %></code><br>
          Telemetry binary: <code><%= @status.hive.bin_present_label %></code><br>
          Last contribute (best-effort): <code><%= @status.hive.last_contribute %></code><br>
          DP budget: <code><%= @status.hive.dp_budget %></code>
        </p>
        <button phx-click="contribute" disabled={not @enabled}>
          Trigger telemetry contribute
        </button>
      </div>

      <h2 class="section-title">Cohort</h2>
      <div class="card">
        <p>
          Patient folders: <strong><%= @status.cohort.n_patients %></strong><br>
          PAM-13 administrations across cohort: <strong><%= @status.cohort.n_pam %></strong><br>
          Co-design events: <strong><%= @status.cohort.n_codesign %></strong>
        </p>
      </div>

      <h2 class="section-title">Quick links</h2>
      <ul>
        <li><a href="/">/ — HomeLive</a></li>
        <li><a href="/about">/about — system description</a></li>
        <li><a href="/status">/status — public health page</a></li>
        <li><a href="/dashboard">/dashboard — clinical overview</a></li>
      </ul>
    </main>
    """
  end

  # ── probes ─────────────────────────────────────────────────────────────

  defp probe(socket) do
    services = [
      probe_http("Phoenix self", "http://127.0.0.1:4000/health"),
      probe_http("aim-llm", "#{@aim_llm_url}/health"),
      probe_http("aim-rag", "#{@aim_rag_url}/health"),
      probe_http("aim-hive-queen", "#{@aim_hive_queen_url}/healthz"),
      probe_http("Ollama (offline LLM)", "#{@ollama_url}/")
    ]

    diagnostic = read_last_diagnostic()
    hive = probe_hive()
    cohort = probe_cohort()

    socket
    |> assign(:status, %{services: services, diagnostic: diagnostic,
                          hive: hive, cohort: cohort})
    |> assign(:last_refresh, DateTime.utc_now())
  end

  defp probe_http(label, url) do
    try do
      :inets.start()

      case :httpc.request(:get, {String.to_charlist(url), []},
             [timeout: 1_500, connect_timeout: 800], []) do
        {:ok, {{_v, code, _r}, _h, _body}} when code in 200..399 ->
          %{label: label, url: url, up: true, detail: "HTTP #{code}"}

        {:ok, {{_v, code, _r}, _h, _body}} ->
          %{label: label, url: url, up: false, detail: "HTTP #{code}"}

        _ ->
          %{label: label, url: url, up: false, detail: "unreachable"}
      end
    rescue
      _ -> %{label: label, url: url, up: false, detail: "probe error"}
    end
  end

  defp read_last_diagnostic do
    p = Path.join([aim_root(), "docs", "operational", "diagnostic_latest.md"])
    case File.read(p) do
      {:ok, body} ->
        # Find "Summary: N P0 / N P1 / N P2 findings"
        case Regex.run(~r/Summary:\s*(\d+)\s*P0\s*\/\s*(\d+)\s*P1\s*\/\s*(\d+)\s*P2/i, body) do
          [_, p0, p1, p2] ->
            %{p0: String.to_integer(p0), p1: String.to_integer(p1), p2: String.to_integer(p2),
              note: "last_modified: #{file_mtime_label(p)}"}
          _ ->
            %{p0: "?", p1: "?", p2: "?", note: "report present, unparseable summary"}
        end

      _ ->
        %{p0: "?", p1: "?", p2: "?", note: "no report yet — click 'Run full diagnostic' to generate"}
    end
  end

  defp probe_hive do
    bin = Path.join([aim_root(), "rust-core", "target", "release", "aim-hive-telemetry"])
    bin_label =
      if File.exists?(bin), do: "✓ #{bin}", else: "✗ MISSING (build with cargo)"

    last = case File.stat(Path.join([System.user_home!(), ".cache", "aim", "hive_last_contribute.txt"])) do
      {:ok, %{mtime: mtime}} -> mtime |> :calendar.datetime_to_gregorian_seconds() |> seconds_to_label()
      _ -> "(never; or no track file)"
    end

    %{bin_present_label: bin_label, last_contribute: last,
      dp_budget: System.get_env("AIM_DP_BUDGET") || "(unset, default applies)"}
  end

  defp probe_cohort do
    p_dir = Path.join([aim_root(), "Patients"])
    n_patients =
      case File.ls(p_dir) do
        {:ok, entries} ->
          entries
          |> Enum.reject(&(&1 in ["INBOX", "README.md"] or String.starts_with?(&1, "_") or String.starts_with?(&1, ".")))
          |> length()
        _ -> 0
      end

    n_pam = count_jsonl(p_dir, "_pam_history.jsonl")
    n_codesign = count_jsonl(p_dir, "_codesign.jsonl")
    %{n_patients: n_patients, n_pam: n_pam, n_codesign: n_codesign}
  end

  defp count_jsonl(root, fname) do
    case File.ls(root) do
      {:ok, dirs} ->
        Enum.reduce(dirs, 0, fn d, acc ->
          fp = Path.join([root, d, fname])
          case File.read(fp) do
            {:ok, body} -> acc + (body |> String.split("\n", trim: true) |> length())
            _ -> acc
          end
        end)
      _ -> 0
    end
  end

  defp aim_root, do: System.get_env("AIM_ROOT") || "/home/oem/Desktop/LongevityCommon/AIM"

  defp status_dot(true), do: "🟢"
  defp status_dot(false), do: "🔴"

  defp refresh_label(nil), do: "(probing...)"
  defp refresh_label(dt), do: Calendar.strftime(dt, "%H:%M:%S")

  defp file_mtime_label(p) do
    case File.stat(p) do
      {:ok, %{mtime: mtime}} -> mtime |> :calendar.datetime_to_gregorian_seconds() |> seconds_to_label()
      _ -> "?"
    end
  end

  defp seconds_to_label(secs) do
    epoch = :calendar.datetime_to_gregorian_seconds({{1970,1,1},{0,0,0}})
    DateTime.from_unix!(secs - epoch)
    |> Calendar.strftime("%Y-%m-%d %H:%M:%S")
  end

  defp spawn_action(cmd, args) do
    # Best-effort spawn — return immediately, action runs async.
    spawn(fn ->
      try do
        path =
          if String.starts_with?(cmd, "/") do
            cmd
          else
            Path.join([aim_root(), cmd])
          end
        System.cmd(path, args, stderr_to_stdout: true, cd: aim_root())
      rescue
        _ -> :error
      end
    end)
  end

  defp flash(socket, msg) do
    ref = make_ref()
    Process.send_after(self(), {:flash_clear, ref}, 5_000)
    assign(socket, flash_msg: msg, flash_ref: ref)
  end
end
