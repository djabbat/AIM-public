defmodule AimWeb.PatientWorkspaceLive do
  @moduledoc """
  Patient-as-Project unified workspace (`/patients/:id`).

  Per project rule (`feedback_project_core` + `feedback_upgrade_md_rule`),
  каждый пациент рассматривается как проект со своим 11-файловым ядром
  (MEMORY/THEORY/CONCEPT/STRATEGY/PARAMETERS/TODO/CHANGELOG/KNOWLEDGE/MAP/
  REMINDER/NEEDTOWRITE + AI_LOG). Этот LiveView показывает Overview tab с
  агрегированными данными, статусом core files, списком лабораторных
  материалов и активацией PAM.

  Backend: `aim-patient-workspace overview <id>` → JSON. No HTTP/PubSub —
  pull on mount + 60s tick. Phase 0 (2026-05-08) — Overview only; Timeline,
  Labs detail, Meds matrix, PAM trends — следующие фазы.
  """
  use AimWeb, :live_view

  @refresh_ms 60_000

  def mount(%{"id" => id}, _session, socket) do
    if connected?(socket), do: :timer.send_interval(@refresh_ms, :tick)

    {:ok,
     socket
     |> assign(:id, id)
     |> assign(:active_tab, :overview)
     |> assign(:view, nil)
     |> assign(:error, nil)
     |> assign(:last_refresh, nil)
     |> assign(:parsed_labs, [])
     |> assign(:lab_eval_error, nil)
     |> assign(:treatment_modal_open, false)
     |> assign(:treatment_drug, "")
     |> assign(:treatment_conflicts, nil)
     |> assign(:event_modal_open, false)
     |> assign(:event_form, %{"date" => Date.utc_today() |> Date.to_iso8601(), "kind" => "complaint", "description" => ""})
     |> assign(:events, [])
     |> load_view()
     |> load_labs()
     |> load_events()}
  end

  def handle_info(:tick, socket),
    do: {:noreply, socket |> load_view() |> load_labs() |> load_events()}

  def handle_event("switch_tab", %{"tab" => tab}, socket) do
    tab_atom =
      case tab do
        "overview" -> :overview
        "timeline" -> :timeline
        "labs" -> :labs
        "meds" -> :meds
        "core" -> :core
        "pam" -> :pam
        _ -> :overview
      end

    {:noreply, assign(socket, :active_tab, tab_atom)}
  end

  def handle_event("refresh", _params, socket), do: {:noreply, load_view(socket)}

  def handle_event("show_treatment_modal", _params, socket) do
    {:noreply,
     socket
     |> assign(:treatment_modal_open, true)
     |> assign(:treatment_drug, "")
     |> assign(:treatment_conflicts, nil)}
  end

  def handle_event("hide_treatment_modal", _params, socket) do
    {:noreply, assign(socket, :treatment_modal_open, false)}
  end

  def handle_event("show_event_modal", _params, socket) do
    today = Date.utc_today() |> Date.to_iso8601()
    {:noreply,
     socket
     |> assign(:event_modal_open, true)
     |> assign(:event_form, %{"date" => today, "kind" => "complaint", "description" => ""})}
  end

  def handle_event("hide_event_modal", _params, socket) do
    {:noreply, assign(socket, :event_modal_open, false)}
  end

  def handle_event("save_event", %{"event" => params}, socket) do
    case append_event(socket.assigns.id, params) do
      {:ok, _} ->
        {:noreply,
         socket
         |> assign(:event_modal_open, false)
         |> load_events()
         |> load_view()}

      {:error, msg} ->
        {:noreply, put_flash(socket, :error, msg)}
    end
  end

  def handle_event("event_form_change", %{"event" => params}, socket) do
    {:noreply, assign(socket, :event_form, params)}
  end

  def handle_event("check_compat", %{"drug" => drug}, socket) do
    drug = String.trim(drug)

    if drug == "" do
      {:noreply, assign(socket, :treatment_drug, "")}
    else
      conflicts = run_compat_check(drug, socket.assigns.view)

      {:noreply,
       socket
       |> assign(:treatment_drug, drug)
       |> assign(:treatment_conflicts, conflicts)}
    end
  end

  # ── data fetcher ─────────────────────────────────────────────────────────

  defp aim_root,
    do:
      System.get_env("AIM_ROOT") ||
        "/home/oem/Desktop/LongevityCommon/AIM"

  defp workspace_bin do
    [
      Path.join([aim_root(), "rust-core", "target", "release", "aim-patient-workspace"]),
      Path.join([aim_root(), "rust-core", "target", "debug", "aim-patient-workspace"])
    ]
    |> Enum.find(&File.exists?/1)
  end

  defp lab_parser_bin do
    [
      Path.join([aim_root(), "rust-core", "target", "release", "aim-lab-parser"]),
      Path.join([aim_root(), "rust-core", "target", "debug", "aim-lab-parser"])
    ]
    |> Enum.find(&File.exists?/1)
  end

  defp compat_bin do
    [
      Path.join([aim_root(), "rust-core", "target", "release", "aim-compat"]),
      Path.join([aim_root(), "rust-core", "target", "debug", "aim-compat"])
    ]
    |> Enum.find(&File.exists?/1)
  end

  defp events_bin do
    [
      Path.join([aim_root(), "rust-core", "target", "release", "aim-patient-events"]),
      Path.join([aim_root(), "rust-core", "target", "debug", "aim-patient-events"])
    ]
    |> Enum.find(&File.exists?/1)
  end

  defp lab_eval_script do
    Path.join([aim_root(), "tools", "lab_evaluate.py"])
  end


  defp load_view(socket) do
    case fetch_view(socket.assigns.id) do
      {:ok, view} ->
        socket
        |> assign(:view, view)
        |> assign(:error, nil)
        |> assign(:last_refresh, DateTime.utc_now())

      {:error, msg} ->
        socket
        |> assign(:view, nil)
        |> assign(:error, msg)
        |> assign(:last_refresh, DateTime.utc_now())
    end
  end

  # Pull parsed + evaluated labs for every *_text.txt file in the patient
  # folder. Pipeline: aim-lab-parser parse-file → JSON → tools/lab_evaluate.py
  # evaluate --sex F → JSON with status/reference/display.
  defp load_labs(socket) do
    case socket.assigns.view do
      nil ->
        socket |> assign(:parsed_labs, []) |> assign(:lab_eval_error, nil)

      view ->
        {labs, err} = fetch_all_labs(view)
        socket |> assign(:parsed_labs, labs) |> assign(:lab_eval_error, err)
    end
  end

  defp fetch_all_labs(view) do
    parser = lab_parser_bin()
    eval_script = lab_eval_script()

    cond do
      parser == nil ->
        {[], "aim-lab-parser binary not built"}

      not File.exists?(eval_script) ->
        {[], "tools/lab_evaluate.py not found"}

      true ->
        sex = get_in(view, ["demographics", "sex"]) || ""
        text_files =
          (view["lab_files"] || [])
          |> Enum.filter(&(&1["kind"] == "ocr_text"))
          |> Enum.map(& &1["filename"])

        try do
          all_evaluated =
            text_files
            |> Enum.flat_map(fn fname ->
              parse_and_eval_one(parser, eval_script, view["folder_path"], fname, sex)
            end)

          {all_evaluated, nil}
        rescue
          e -> {[], "lab pipeline error: #{inspect(e)}"}
        end
    end
  end

  defp parse_and_eval_one(parser, eval_script, folder, fname, sex) do
    full_path = Path.join(folder, fname)

    with {parsed_json, 0} <- System.cmd(parser, ["parse-file", full_path]),
         args <-
           if(sex != "", do: ["--sex", sex], else: []),
         {evaluated_json, 0} <-
           run_pipe(["python3", eval_script, "evaluate" | args], parsed_json) do
      case Jason.decode(evaluated_json) do
        {:ok, items} when is_list(items) ->
          Enum.map(items, &Map.put(&1, "_source_file", fname))

        _ ->
          []
      end
    else
      _ -> []
    end
  end

  # Pipe `input` into `[cmd | args]` and capture stdout. Returns
  # `{stdout_string, exit_code}` for parity with `System.cmd/3`. Uses
  # `Port.open/2` so we can write to stdin.
  defp run_pipe([cmd | args], input) do
    port =
      Port.open(
        {:spawn_executable, System.find_executable(cmd) || cmd},
        [
          :exit_status,
          :binary,
          :stderr_to_stdout,
          {:args, args},
          :use_stdio
        ]
      )

    Port.command(port, input)
    Port.close(port)

    # Drain output.
    receive_loop("", port, 5_000)
  end

  defp receive_loop(buf, port, _timeout_ms) do
    receive do
      {^port, {:data, chunk}} -> receive_loop(buf <> chunk, port, 5_000)
      {^port, {:exit_status, code}} -> {buf, code}
    after
      5_000 -> {buf, 124}
    end
  end

  defp run_compat_check(drug, view) do
    case compat_bin() do
      nil ->
        [%{"error" => "aim-compat binary not built"}]

      bin ->
        ctx_args = build_compat_args(view)
        args = ["check-new", drug] ++ ctx_args

        case System.cmd(bin, args) do
          {json, 0} ->
            case Jason.decode(json) do
              {:ok, list} when is_list(list) -> list
              _ -> [%{"error" => "JSON decode failed"}]
            end

          {err, code} ->
            [%{"error" => "exit #{code}: #{String.trim(err)}"}]
        end
    end
  end

  defp load_events(socket) do
    case socket.assigns.view do
      nil -> assign(socket, :events, [])
      _view ->
        case fetch_events(socket.assigns.id) do
          {:ok, list} -> assign(socket, :events, list)
          {:error, _} -> assign(socket, :events, [])
        end
    end
  end

  defp fetch_events(id) do
    case events_bin() do
      nil ->
        {:error, "aim-patient-events binary not built"}

      bin ->
        env = [{"AIM_PATIENTS_DIR", Path.join(aim_root(), "Patients")}]

        case System.cmd(bin, ["list", id, "--limit", "200"], env: env) do
          {json, 0} ->
            case Jason.decode(json) do
              {:ok, list} when is_list(list) -> {:ok, list}
              _ -> {:error, "decode failed"}
            end

          {err, code} ->
            {:error, "exit #{code}: #{String.trim(err)}"}
        end
    end
  end

  defp append_event(id, params) do
    case events_bin() do
      nil ->
        {:error, "aim-patient-events binary not built"}

      bin ->
        env = [{"AIM_PATIENTS_DIR", Path.join(aim_root(), "Patients")}]
        date = Map.get(params, "date", Date.utc_today() |> Date.to_iso8601())
        kind = Map.get(params, "kind", "note")
        desc = Map.get(params, "description", "")

        if String.trim(desc) == "" do
          {:error, "description cannot be empty"}
        else
          args = ["add", id, "--date", date, "--kind", kind, "--description", desc, "--source", "manual"]

          case System.cmd(bin, args, env: env) do
            {_, 0} -> {:ok, :saved}
            {err, code} -> {:error, "exit #{code}: #{String.trim(err)}"}
          end
        end
    end
  end

  defp build_compat_args(view) do
    age_arg =
      case get_in(view, ["demographics", "age"]) do
        nil -> []
        age when is_integer(age) -> ["--age", Integer.to_string(age)]
        _ -> []
      end

    sex_arg =
      case get_in(view, ["demographics", "sex"]) do
        nil -> []
        "" -> []
        sex -> ["--sex", to_string(sex)]
      end

    allergy_args =
      (view["allergies"] || [])
      |> Enum.flat_map(fn a -> ["--allergy", a] end)

    cond_args =
      (view["conditions"] || [])
      |> Enum.flat_map(fn c -> ["--cond", c["dx"] || ""] end)
      |> Enum.reject(&(&1 == ""))

    existing_args =
      (view["medications"] || [])
      |> Enum.flat_map(fn m -> ["--existing", m["name"] || ""] end)
      |> Enum.reject(&(&1 == ""))

    age_arg ++ sex_arg ++ allergy_args ++ cond_args ++ existing_args
  end

  defp fetch_view(id) do
    case workspace_bin() do
      nil ->
        {:error,
         "aim-patient-workspace binary not found. " <>
           "Run: cd rust-core && cargo build --release -p aim-patient-workspace"}

      bin ->
        env = [{"AIM_PATIENTS_DIR", Path.join(aim_root(), "Patients")}]

        case System.cmd(bin, ["overview", id], env: env, stderr_to_stdout: false) do
          {json, 0} ->
            try do
              {:ok, Jason.decode!(json)}
            rescue
              e -> {:error, "JSON decode failed: #{inspect(e)}"}
            end

          {err, code} ->
            {:error, "binary exit #{code}: #{String.trim(err)}"}
        end
    end
  rescue
    e -> {:error, "exec error: #{inspect(e)}"}
  end

  # ── render ───────────────────────────────────────────────────────────────

  def render(assigns) do
    ~H"""
    <div class="aim-patient-workspace">
      <nav class="back-nav">
        <a href="/patients">← All patients</a>
      </nav>

      <div :if={@error} class="ws-error">
        <strong>Error loading <%= @id %>:</strong>
        <pre><%= @error %></pre>
      </div>

      <div :if={@view} class="ws-content">
        <header class="ws-header">
          <h1><%= @view["id"] %></h1>
          <div class="ws-meta">
            <span :if={demographics_age(@view)} class="meta-pill">
              <%= demographics_age(@view) %>
            </span>
            <span :if={demographics_sex(@view)} class="meta-pill">
              <%= demographics_sex(@view) %>
            </span>
            <span :if={demographics_country(@view)} class="meta-pill">
              <%= demographics_country(@view) %>
            </span>
            <span class={"meta-pill phase phase-#{String.downcase(@view["phase"] || "?")}"}>
              <%= @view["phase"] %>
            </span>
            <span :if={(@view["events_count"] || 0) > 0} class="meta-pill">
              <%= @view["events_count"] %> events
            </span>
          </div>
          <div class="ws-actions">
            <button phx-click="show_treatment_modal" type="button" class="btn-primary">
              + Add medication (compat-check)
            </button>
            <button phx-click="refresh" type="button">↻ Refresh</button>
          </div>
        </header>

        <nav class="ws-tabs">
          <button
            type="button"
            phx-click="switch_tab"
            phx-value-tab="overview"
            class={["tab", @active_tab == :overview && "active"]}
          >Overview</button>
          <button
            type="button"
            phx-click="switch_tab"
            phx-value-tab="timeline"
            class={["tab", @active_tab == :timeline && "active"]}
          >Timeline</button>
          <button
            type="button"
            phx-click="switch_tab"
            phx-value-tab="labs"
            class={["tab", @active_tab == :labs && "active"]}
          >Labs</button>
          <button
            type="button"
            phx-click="switch_tab"
            phx-value-tab="meds"
            class={["tab", @active_tab == :meds && "active"]}
          >Medications</button>
          <button
            type="button"
            phx-click="switch_tab"
            phx-value-tab="core"
            class={["tab", @active_tab == :core && "active"]}
          >Core files</button>
          <button
            type="button"
            phx-click="switch_tab"
            phx-value-tab="pam"
            class={["tab", @active_tab == :pam && "active"]}
          >PAM-13</button>
        </nav>

        <%= render_tab(assigns) %>

        <%= if @treatment_modal_open do %>
          <%= render_treatment_modal(assigns) %>
        <% end %>

        <footer :if={@last_refresh} class="ws-footer">
          <small>Refreshed <%= Calendar.strftime(@last_refresh, "%Y-%m-%d %H:%M:%S UTC") %></small>
        </footer>
      </div>
    </div>
    """
  end

  defp render_treatment_modal(assigns) do
    ~H"""
    <div class="ws-modal-backdrop" phx-click="hide_treatment_modal">
      <div class="ws-modal" phx-click-away="hide_treatment_modal">
        <header>
          <h3>Compatibility check — adding a medication</h3>
          <button phx-click="hide_treatment_modal" type="button" aria-label="close">×</button>
        </header>

        <p class="muted">
          Decision support only — not a prescription. Reviewed against
          patient age, allergies, conditions, existing medications via
          <code>aim-compat</code>.
        </p>

        <form phx-change="check_compat" phx-submit="check_compat">
          <label>
            Drug name:
            <input
              type="text"
              name="drug"
              value={@treatment_drug}
              placeholder="e.g. ibuprofen, amoxicillin"
              autofocus
              autocomplete="off"
            />
          </label>
        </form>

        <%= cond do %>
          <% @treatment_drug == "" -> %>
            <p class="muted">Type a drug to see conflicts.</p>

          <% is_list(@treatment_conflicts) and @treatment_conflicts == [] -> %>
            <p class="ok">
              ✓ No conflicts found for <strong><%= @treatment_drug %></strong>
              against this patient's profile.
              <br/>
              <em>Still requires clinician judgment — see disclaimer.</em>
            </p>

          <% is_list(@treatment_conflicts) -> %>
            <ul class="conflict-list">
              <li :for={c <- @treatment_conflicts} class={"conflict severity-#{c["severity"] || "none"}"}>
                <span class="badge"><%= c["severity"] %></span>
                <strong><%= c["kind"] %></strong>
                <%= if c["other_drug"] do %>
                  <em>× <%= c["other_drug"] %></em>
                <% end %>
                <p><%= c["message"] %></p>
                <small>source: <%= c["source"] %></small>
              </li>
            </ul>

          <% true -> %>
            <p class="muted">No data yet.</p>
        <% end %>
      </div>
    </div>
    """
  end

  # ── tab dispatch ─────────────────────────────────────────────────────────

  defp render_tab(%{active_tab: :overview} = assigns), do: render_overview(assigns)
  defp render_tab(%{active_tab: :timeline} = assigns), do: render_timeline(assigns)
  defp render_tab(%{active_tab: :labs} = assigns), do: render_labs(assigns)
  defp render_tab(%{active_tab: :meds} = assigns), do: render_meds(assigns)
  defp render_tab(%{active_tab: :core} = assigns), do: render_core(assigns)
  defp render_tab(%{active_tab: :pam} = assigns), do: render_pam(assigns)

  # ── Overview ─────────────────────────────────────────────────────────────

  defp render_overview(assigns) do
    ~H"""
    <section class="ws-overview">
      <div class="grid">
        <article class="card">
          <h2>Allergies</h2>
          <p :if={(@view["allergies"] || []) == []} class="muted">none recorded</p>
          <ul :if={(@view["allergies"] || []) != []}>
            <li :for={a <- @view["allergies"]}><%= a %></li>
          </ul>
        </article>

        <article class="card">
          <h2>Active medications <span class="count"><%= length(@view["medications"] || []) %></span></h2>
          <p :if={(@view["medications"] || []) == []} class="muted">none</p>
          <ul :if={(@view["medications"] || []) != []} class="meds-short">
            <li :for={m <- Enum.take(@view["medications"] || [], 6)}>
              <strong><%= m["name"] %></strong>
              <span :if={m["dose"] && m["dose"] != "None"} class="dose">· <%= m["dose"] %></span>
            </li>
            <li :if={length(@view["medications"] || []) > 6} class="muted">
              + <%= length(@view["medications"]) - 6 %> more (see Medications tab)
            </li>
          </ul>
        </article>

        <article class="card">
          <h2>Conditions <span class="count"><%= length(@view["conditions"] || []) %></span></h2>
          <p :if={(@view["conditions"] || []) == []} class="muted">none</p>
          <ul :if={(@view["conditions"] || []) != []}>
            <li :for={c <- @view["conditions"]}>
              <strong><%= c["dx"] %></strong>
              <span :if={c["since"] && c["since"] != "None"} class="since"> (<%= c["since"] %>)</span>
              <p :if={c["notes"]} class="notes"><%= c["notes"] %></p>
            </li>
          </ul>
        </article>

        <article class="card">
          <h2>PAM-13 activation</h2>
          <%= cond do %>
            <% @view["activation"]["current_score"] -> %>
              <p>
                Score <strong><%= Float.round(@view["activation"]["current_score"] || 0.0, 1) %></strong>
                · level <strong><%= @view["activation"]["current_level"] || "?" %></strong>
                · <%= @view["activation"]["history_count"] %> measurement(s)
              </p>
              <p :if={@view["activation"]["last_measured"]} class="muted">
                last measured <%= @view["activation"]["last_measured"] %>
              </p>
              <a href={"/pam/#{@view["id"]}"}>Open PAM trajectory →</a>
            <% true -> %>
              <p class="muted">No PAM-13 measurements yet.</p>
              <a href={"/pam/#{@view["id"]}"}>Administer first PAM-13 →</a>
          <% end %>
        </article>

        <article class="card">
          <h2>Red flags / known unknowns</h2>
          <p :if={(@view["red_flags"] || []) == []} class="muted">none</p>
          <ul :if={(@view["red_flags"] || []) != []} class="red-flags">
            <li :for={r <- @view["red_flags"]}>⚠ <%= r %></li>
          </ul>
          <p :if={@view["primary_complaint_undiagnosed"]} class="warn">
            Primary complaint not yet diagnosed.
          </p>
          <p :if={!@view["has_confirmed_dx"]} class="muted">
            No confirmed diagnosis on record.
          </p>
        </article>

        <article class="card">
          <h2>Project core <span class="count">
            <%= present_core_count(@view) %>/<%= length(@view["core_files"] || []) %>
          </span></h2>
          <p class="muted">
            Patient-as-Project core files. Click "Core files" tab for details.
          </p>
          <ul class="core-mini">
            <li :for={c <- @view["core_files"] || []} class={if c["present"], do: "present", else: "missing"}>
              <span class="dot"><%= if c["present"], do: "●", else: "○" %></span>
              <%= c["filename"] %>
            </li>
          </ul>
        </article>
      </div>

      <article class="card wide">
        <h2>History (reverse-chronological)</h2>
        <p :if={(@view["history"] || []) == []} class="muted">
          No history entries. Add events via Timeline tab (coming soon).
        </p>
        <ul :if={(@view["history"] || []) != []}>
          <li :for={h <- @view["history"]}><%= h %></li>
        </ul>
      </article>

      <article class="card wide">
        <h2>Lab files <span class="count"><%= length(@view["lab_files"] || []) %></span></h2>
        <p :if={(@view["lab_files"] || []) == []} class="muted">No lab files in folder.</p>
        <table :if={(@view["lab_files"] || []) != []} class="lab-table">
          <thead>
            <tr>
              <th>File</th>
              <th>Kind</th>
              <th>Size</th>
              <th>OCR?</th>
              <th>Modified</th>
            </tr>
          </thead>
          <tbody>
            <tr :for={f <- Enum.take(@view["lab_files"] || [], 12)}>
              <td><%= f["filename"] %></td>
              <td><%= f["kind"] %></td>
              <td><%= human_size(f["size_bytes"]) %></td>
              <td><%= if f["has_ocr_pair"], do: "✓", else: "—" %></td>
              <td><%= f["mtime_iso"] || "—" %></td>
            </tr>
          </tbody>
        </table>
        <p :if={length(@view["lab_files"] || []) > 12} class="muted">
          + <%= length(@view["lab_files"]) - 12 %> more (see Labs tab)
        </p>
      </article>
    </section>
    """
  end

  # ── Timeline tab ─────────────────────────────────────────────────────────

  defp render_timeline(assigns) do
    ~H"""
    <section class="ws-timeline">
      <header class="ws-timeline-header">
        <h2>Timeline <span class="count"><%= length(@events) %></span></h2>
        <button phx-click="show_event_modal" type="button" class="btn-primary">
          + Add event
        </button>
      </header>

      <p :if={@events == []} class="muted">
        No events recorded. Use "Add event" to start the patient project log.
      </p>

      <ol :if={@events != []} class="timeline-list">
        <li :for={e <- @events} class={"event kind-#{kind_to_str(e["kind"])}"}>
          <div class="event-date">
            <strong><%= e["event_date"] %></strong>
            <span class="kind-badge"><%= kind_to_str(e["kind"]) %></span>
          </div>
          <p class="event-desc"><%= e["description"] %></p>
          <small class="event-meta">
            recorded <%= e["recorded_at"] %>
            · source: <%= e["source"] %>
            <%= if e["corrects_id"] do %>
              · corrects: <code><%= e["corrects_id"] %></code>
            <% end %>
            · id: <code><%= e["id"] %></code>
          </small>
          <%= if e["payload"] do %>
            <details class="event-payload">
              <summary>payload</summary>
              <pre><%= Jason.encode_to_iodata!(e["payload"], pretty: true) %></pre>
            </details>
          <% end %>
        </li>
      </ol>

      <%= if @event_modal_open do %>
        <%= render_event_modal(assigns) %>
      <% end %>
    </section>
    """
  end

  defp kind_to_str(kind) when is_binary(kind), do: kind
  defp kind_to_str(_), do: "note"

  defp render_event_modal(assigns) do
    ~H"""
    <div class="ws-modal-backdrop" phx-click="hide_event_modal">
      <div class="ws-modal" phx-click-away="hide_event_modal">
        <header>
          <h3>Add event</h3>
          <button phx-click="hide_event_modal" type="button" aria-label="close">×</button>
        </header>

        <form phx-change="event_form_change" phx-submit="save_event">
          <label>
            Date:
            <input type="date" name="event[date]" value={@event_form["date"]} required />
          </label>

          <label>
            Kind:
            <select name="event[kind]">
              <option value="complaint" selected={@event_form["kind"] == "complaint"}>Complaint</option>
              <option value="diagnosis" selected={@event_form["kind"] == "diagnosis"}>Diagnosis</option>
              <option value="lab" selected={@event_form["kind"] == "lab"}>Lab</option>
              <option value="treatment" selected={@event_form["kind"] == "treatment"}>Treatment</option>
              <option value="allergy_reported" selected={@event_form["kind"] == "allergy_reported"}>Allergy reported</option>
              <option value="visit" selected={@event_form["kind"] == "visit"}>Visit</option>
              <option value="note" selected={@event_form["kind"] == "note"}>Note</option>
            </select>
          </label>

          <label>
            Description:
            <textarea name="event[description]" rows="4" required><%= @event_form["description"] %></textarea>
          </label>

          <div class="form-actions">
            <button type="button" phx-click="hide_event_modal">Cancel</button>
            <button type="submit" class="btn-primary">Save event</button>
          </div>
        </form>
      </div>
    </div>
    """
  end

  # ── Labs tab (full) ──────────────────────────────────────────────────────

  defp render_labs(assigns) do
    ~H"""
    <section class="ws-labs">
      <h2>Parsed lab values <span class="count"><%= length(@parsed_labs) %></span></h2>

      <p :if={@lab_eval_error} class="ws-warn">
        ⚠ <%= @lab_eval_error %>
      </p>

      <p :if={@parsed_labs == [] && !@lab_eval_error} class="muted">
        No OCR'd lab files found, or parser couldn't extract any analytes.
        Add lab files to the patient folder + ensure <code>*_text.txt</code>
        OCR pairs exist (intake pipeline auto-creates them).
      </p>

      <table :if={@parsed_labs != []} class="lab-eval-table">
        <thead>
          <tr>
            <th>Analyte</th>
            <th>Abbrev.</th>
            <th>Value</th>
            <th>Unit (OCR)</th>
            <th>Reference</th>
            <th>Unit (ref)</th>
            <th>Status</th>
            <th>Source file</th>
          </tr>
        </thead>
        <tbody>
          <tr :for={l <- @parsed_labs} class={"status-#{l["status"] || "unknown"}"}>
            <td><%= l["display"] || l["analyte"] %></td>
            <td><code><%= l["abbreviation"] || "—" %></code></td>
            <td class="value"><%= l["value"] %></td>
            <td class="unit-raw"><%= l["unit_raw"] || "—" %></td>
            <td class="ref"><%= l["reference"] || "—" %></td>
            <td class="unit-ref"><%= l["unit"] || "—" %></td>
            <td>
              <span class={"status-badge status-#{l["status"] || "unknown"}"}>
                <%= status_label(l["status"]) %>
              </span>
            </td>
            <td class="src"><small><%= l["_source_file"] %></small></td>
          </tr>
        </tbody>
      </table>

      <details class="raw-files">
        <summary>Raw files in folder (<%= length(@view["lab_files"] || []) %>)</summary>
        <table class="lab-table">
          <thead>
            <tr>
              <th>File</th>
              <th>Kind</th>
              <th>Size</th>
              <th>OCR pair</th>
              <th>Modified</th>
            </tr>
          </thead>
          <tbody>
            <tr :for={f <- @view["lab_files"] || []}>
              <td><%= f["filename"] %></td>
              <td><%= f["kind"] %></td>
              <td><%= human_size(f["size_bytes"]) %></td>
              <td><%= if f["has_ocr_pair"], do: "✓", else: "—" %></td>
              <td><%= f["mtime_iso"] || "—" %></td>
            </tr>
          </tbody>
        </table>
      </details>

      <p class="muted">
        ⚠ Unit reconciliation between OCR-reported unit and reference unit
        is <em>not</em> automatic. If OCR unit differs from reference unit,
        flag is <em>raw-value-vs-reference-range</em> only — physician must
        verify before acting. (See AIM_v0.1 lab pipeline limitation.)
      </p>
    </section>
    """
  end

  defp status_label("normal"), do: "normal"
  defp status_label("low"), do: "low ↓"
  defp status_label("high"), do: "high ↑"
  defp status_label("critical_low"), do: "CRIT LOW ⚠"
  defp status_label("critical_high"), do: "CRIT HIGH ⚠"
  defp status_label("unknown"), do: "—"
  defp status_label(other), do: to_string(other || "—")

  # ── Medications tab (full table) ─────────────────────────────────────────

  defp render_meds(assigns) do
    ~H"""
    <section class="ws-meds">
      <h2>All medications</h2>
      <p :if={(@view["medications"] || []) == []} class="muted">none</p>
      <table :if={(@view["medications"] || []) != []} class="meds-table">
        <thead>
          <tr>
            <th>Drug</th>
            <th>Dose</th>
            <th>Frequency / schedule</th>
          </tr>
        </thead>
        <tbody>
          <tr :for={m <- @view["medications"]}>
            <td><strong><%= m["name"] %></strong></td>
            <td><%= m["dose"] || "—" %></td>
            <td><%= m["freq"] || "—" %></td>
          </tr>
        </tbody>
      </table>
      <p class="muted">
        Compatibility check (drug × age × allergy × pregnancy × drug-drug) —
        Phase 2 (TaskList #2, aim-compat crate).
      </p>
    </section>
    """
  end

  # ── Core files tab ───────────────────────────────────────────────────────

  defp render_core(assigns) do
    ~H"""
    <section class="ws-core">
      <h2>Patient-as-Project core files</h2>
      <p class="muted">
        Each patient is a project with an 11-file core
        (per <code>feedback_project_core</code> rule). Missing files can be
        created on demand; only MEMORY.md is required by the kernel.
      </p>
      <table class="core-table">
        <thead>
          <tr>
            <th>File</th>
            <th>Present</th>
            <th>Size</th>
            <th>Last modified</th>
          </tr>
        </thead>
        <tbody>
          <tr :for={c <- @view["core_files"] || []} class={if c["present"], do: "present", else: "missing"}>
            <td><code><%= c["filename"] %></code></td>
            <td><%= if c["present"], do: "✓", else: "—" %></td>
            <td><%= if c["present"], do: human_size(c["size_bytes"]), else: "—" %></td>
            <td><%= c["mtime_iso"] || "—" %></td>
          </tr>
        </tbody>
      </table>
    </section>
    """
  end

  # ── PAM tab redirect ─────────────────────────────────────────────────────

  defp render_pam(assigns) do
    ~H"""
    <section class="ws-pam">
      <p>PAM-13 trajectory has its own dedicated workspace.</p>
      <a href={"/pam/#{@view["id"]}"}>Open PAM trajectory →</a>
    </section>
    """
  end

  # ── helpers ──────────────────────────────────────────────────────────────

  defp demographics_age(view) do
    case get_in(view, ["demographics", "age"]) do
      nil -> nil
      age -> "#{age} y/o"
    end
  end

  defp demographics_sex(view), do: get_in(view, ["demographics", "sex"])
  defp demographics_country(view), do: get_in(view, ["demographics", "country"])

  defp present_core_count(view) do
    (view["core_files"] || [])
    |> Enum.count(& &1["present"])
  end

  defp human_size(nil), do: "—"
  defp human_size(0), do: "0 B"

  defp human_size(b) when is_integer(b) do
    cond do
      b < 1024 -> "#{b} B"
      b < 1024 * 1024 -> "#{Float.round(b / 1024, 1)} KB"
      true -> "#{Float.round(b / (1024 * 1024), 2)} MB"
    end
  end

  defp human_size(_), do: "—"
end
