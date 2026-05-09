defmodule AimWeb.DisagreementLive do
  @moduledoc """
  Interactive Blumenthal-Lee 4-zone disagreement classifier
  (Phase 7+, 2026-05-07).

  Route `/disagreement`. The clinician adjusts the AI confidence,
  their own self-rated confidence, and the agreement flag; the page
  shows which zone applies and the corresponding UI action. Backed by
  the `aim-disagreement classify` Rust binary.
  """
  use AimWeb, :live_view

  def mount(_params, _session, socket) do
    {:ok,
     socket
     |> assign(:ai_conf, 0.85)
     |> assign(:clinician_conf, 0.70)
     |> assign(:agree, true)
     |> assign(:outcome, nil)
     |> classify()}
  end

  def handle_event("set", params, socket) do
    socket =
      socket
      |> maybe_assign_float(params, "ai_conf")
      |> maybe_assign_float(params, "clinician_conf")
      |> maybe_assign_bool(params, "agree")
      |> classify()

    {:noreply, socket}
  end

  defp maybe_assign_float(socket, params, key) do
    case Map.get(params, key) do
      nil -> socket
      v ->
        case Float.parse(to_string(v)) do
          {f, _} -> assign(socket, String.to_existing_atom(key), max(0.0, min(1.0, f)))
          _ -> socket
        end
    end
  end

  defp maybe_assign_bool(socket, params, key) do
    case Map.get(params, key) do
      nil -> socket
      v -> assign(socket, String.to_existing_atom(key), v in [true, "true", "on", "1"])
    end
  end

  # ── data ───────────────────────────────────────────────────────────────

  defp aim_root, do: System.get_env("AIM_ROOT") || "/home/oem/Desktop/LongevityCommon/AIM"

  defp disagreement_bin do
    [
      Path.join([aim_root(), "rust-core", "target", "release", "aim-disagreement"]),
      Path.join([aim_root(), "rust-core", "target", "debug", "aim-disagreement"])
    ]
    |> Enum.find(&File.exists?/1)
  end

  defp classify(socket) do
    case disagreement_bin() do
      nil ->
        assign(socket, :outcome, %{"zone" => "binary_missing", "summary" => "Build aim-disagreement"})

      bin ->
        ai = Float.to_string(socket.assigns.ai_conf)
        cl = Float.to_string(socket.assigns.clinician_conf)
        ag = if socket.assigns.agree, do: "true", else: "false"

        case System.cmd(bin, ["classify", ai, cl, ag]) do
          {out, 0} ->
            case Jason.decode(String.trim(out)) do
              {:ok, j} -> assign(socket, :outcome, j)
              _ -> assign(socket, :outcome, nil)
            end

          _ ->
            assign(socket, :outcome, nil)
        end
    end
  end

  # ── render ─────────────────────────────────────────────────────────────

  def render(assigns) do
    ~H"""
    <div class="aim-disagreement">
      <h1>⚖️ AI / clinician disagreement</h1>

      <form phx-change="set" class="disagreement-form">
        <label>
          AI confidence: <strong><%= Float.round(@ai_conf, 2) %></strong>
          <input type="range" min="0" max="1" step="0.05" name="ai_conf" value={@ai_conf}/>
        </label>
        <label>
          Clinician confidence: <strong><%= Float.round(@clinician_conf, 2) %></strong>
          <input type="range" min="0" max="1" step="0.05" name="clinician_conf" value={@clinician_conf}/>
        </label>
        <label>
          <input type="checkbox" name="agree" checked={@agree}/>
          Agree on the recommended action
        </label>
      </form>

      <section :if={@outcome} class={"outcome zone-#{@outcome["zone"]}"}>
        <h2>Zone: <%= @outcome["zone"] %></h2>
        <p>UI action: <code><%= @outcome["ui_action"] %></code></p>
        <p><em><%= @outcome["summary"] %></em></p>
      </section>

      <section class="legend">
        <h3>Legend</h3>
        <ul>
          <li><strong>aligned</strong> — both confident + agree → auto-execute</li>
          <li><strong>conflict_high_stakes</strong> — both confident + disagree → MDT review</li>
          <li><strong>ai_leads</strong> — AI high, clinician low → show evidence, confirm</li>
          <li><strong>clinician_leads</strong> — AI low, clinician high → defer, record</li>
          <li><strong>escalate</strong> — both unsure → wait / MDT / more data</li>
        </ul>
      </section>
    </div>
    """
  end
end
