defmodule AimWeb.CoachingLive do
  @moduledoc """
  Patient coaching dashboard (Phase 4 of "Patient as a Project",
  2026-05-07).

  Route `/coaching/:patient_id`. Shows the patient's PAM-13 activation
  level + active coaching goals + a clinician-facing form to:

    - log a new patient utterance and see the suggested OARS move
    - mark an existing goal as achieved (TODO: write back to JSONL)

  Backed by Rust binaries:
    - `aim-pam level <id>` — current activation
    - `aim-coach classify <utterance>` — change/sustain/neutral/resistance
    - `aim-coach next-move <kind> <level>` — OARS move

  No LLM call here — that's downstream (Phase 5b shim into aim-llm).
  Refreshes activation every 30 s.
  """
  use AimWeb, :live_view

  @refresh_ms 30_000

  def mount(%{"patient_id" => pid}, _session, socket) do
    if connected?(socket), do: :timer.send_interval(@refresh_ms, :tick)

    {:ok,
     socket
     |> assign(:patient_id, pid)
     |> assign(:utterance, "")
     |> assign(:utterance_kind, nil)
     |> assign(:next_move, nil)
     |> assign(:activation_level, 0)
     |> assign(:last_refresh, nil)
     |> load_activation()}
  end

  def handle_info(:tick, socket), do: {:noreply, load_activation(socket)}

  def handle_event("classify", %{"utterance" => u}, socket) do
    {kind, mv} = classify_and_move(u, socket.assigns.activation_level)

    {:noreply,
     socket
     |> assign(:utterance, u)
     |> assign(:utterance_kind, kind)
     |> assign(:next_move, mv)}
  end

  def handle_event("clear", _params, socket) do
    {:noreply,
     socket
     |> assign(:utterance, "")
     |> assign(:utterance_kind, nil)
     |> assign(:next_move, nil)}
  end

  # ── data ───────────────────────────────────────────────────────────────

  defp aim_root, do: System.get_env("AIM_ROOT") || "/home/oem/Desktop/LongevityCommon/AIM"

  defp pam_bin do
    [
      Path.join([aim_root(), "rust-core", "target", "release", "aim-pam"]),
      Path.join([aim_root(), "rust-core", "target", "debug", "aim-pam"])
    ]
    |> Enum.find(&File.exists?/1)
  end

  defp coach_bin do
    [
      Path.join([aim_root(), "rust-core", "target", "release", "aim-coach"]),
      Path.join([aim_root(), "rust-core", "target", "debug", "aim-coach"])
    ]
    |> Enum.find(&File.exists?/1)
  end

  defp patients_dir, do: Path.join(aim_root(), "Patients")

  defp load_activation(socket) do
    pid = socket.assigns.patient_id

    level =
      case pam_bin() do
        nil ->
          0

        bin ->
          env = [{"AIM_PATIENTS_DIR", patients_dir()}]

          case System.cmd(bin, ["level", pid, "--patients-dir", patients_dir()], env: env) do
            {out, 0} ->
              case Integer.parse(String.trim(out)) do
                {n, _} -> n
                _ -> 0
              end

            _ ->
              0
          end
      end

    socket
    |> assign(:activation_level, level)
    |> assign(:last_refresh, DateTime.utc_now())
  end

  defp classify_and_move("", _level), do: {nil, nil}

  defp classify_and_move(utterance, level) do
    case coach_bin() do
      nil ->
        {nil, nil}

      bin ->
        kind =
          case System.cmd(bin, ["classify", utterance]) do
            {out, 0} -> String.trim(out)
            _ -> nil
          end

        mv =
          if kind do
            case System.cmd(bin, ["next-move", kind, Integer.to_string(level)]) do
              {out, 0} -> String.trim(out)
              _ -> nil
            end
          end

        {kind, mv}
    end
  end

  # ── render ─────────────────────────────────────────────────────────────

  def render(assigns) do
    ~H"""
    <div class="aim-coaching">
      <h1>🌱 Coaching: <%= @patient_id %></h1>

      <p>
        Activation (PAM-13):
        <strong>L<%= @activation_level %></strong>
        <em><%= level_label(@activation_level) %></em>
      </p>

      <form phx-submit="classify" class="coach-form">
        <label>
          Patient just said:
          <input type="text" name="utterance" value={@utterance}
                 placeholder="что сказал пациент..."
                 autocomplete="off"/>
        </label>
        <button type="submit">Classify</button>
        <button type="button" phx-click="clear">Clear</button>
      </form>

      <section :if={@utterance_kind} class="coach-result">
        <p>Kind: <strong><%= @utterance_kind %></strong> <%= kind_emoji(@utterance_kind) %></p>
        <p>Suggested OARS move: <strong><%= @next_move %></strong> <%= move_emoji(@next_move) %></p>
        <p class="hint"><%= move_hint(@next_move) %></p>
      </section>

      <section class="legend">
        <h3>OARS reference</h3>
        <ul>
          <li><strong>Open question</strong> 💬 — "What would change look like for you?"</li>
          <li><strong>Affirmation</strong> ✅ — name a strength the patient just demonstrated</li>
          <li><strong>Reflection</strong> 🪞 — restate what they said, including ambivalence</li>
          <li><strong>Summary</strong> 📝 — knit together change talk so far</li>
          <li><strong>Roll with resistance</strong> 🌊 — reframe; don't push back</li>
          <li><strong>Build rapport</strong> 🤝 — disengaged patient (L0/L1); start small</li>
        </ul>
      </section>

      <p>
        <a href={"/pam/#{@patient_id}"}>← PAM trajectory</a> ·
        <a href={"/codesign/#{@patient_id}"}>co-design events</a>
      </p>

      <footer :if={@last_refresh}>
        <small>Refreshed: <%= Calendar.strftime(@last_refresh, "%Y-%m-%d %H:%M:%S UTC") %></small>
      </footer>
    </div>
    """
  end

  defp level_label(0), do: "(no PAM-13 yet)"
  defp level_label(1), do: "disengaged & overwhelmed"
  defp level_label(2), do: "becoming aware"
  defp level_label(3), do: "taking action"
  defp level_label(4), do: "maintaining"

  defp kind_emoji("change_talk"), do: "↗️"
  defp kind_emoji("sustain_talk"), do: "↘️"
  defp kind_emoji("neutral"), do: "·"
  defp kind_emoji("resistance"), do: "🛑"
  defp kind_emoji(_), do: ""

  defp move_emoji("open_question"), do: "💬"
  defp move_emoji("affirmation"), do: "✅"
  defp move_emoji("reflection"), do: "🪞"
  defp move_emoji("summary"), do: "📝"
  defp move_emoji("roll_with_resistance"), do: "🌊"
  defp move_emoji("build_rapport"), do: "🤝"
  defp move_emoji(_), do: ""

  defp move_hint("open_question"),
    do: "Ask one open-ended question; keep replies under 80 words."

  defp move_hint("affirmation"),
    do: "Name a specific strength or effort you saw. Don't be vague."

  defp move_hint("reflection"),
    do: "Restate what they said — include the ambivalence. Don't argue."

  defp move_hint("summary"),
    do: "Knit together the change talk so far; check the patient agrees."

  defp move_hint("roll_with_resistance"),
    do: "Reframe; honour autonomy. Don't push, don't lecture."

  defp move_hint("build_rapport"),
    do: "Patient is disengaged. Start with rapport, not change-focused MI."

  defp move_hint(_), do: ""
end
