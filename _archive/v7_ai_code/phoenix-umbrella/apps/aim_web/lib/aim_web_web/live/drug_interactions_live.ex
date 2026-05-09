defmodule AimWeb.DrugInteractionsLive do
  @moduledoc """
  Drug-drug interaction check (m9 in the legacy Python menu).
  Wraps `agents.interactions.check_regimen` via the Rust core's
  aim-interactions crate over the gateway RPC.
  """
  use AimWeb, :live_view

  def mount(_params, _session, socket) do
    {:ok,
     socket
     |> assign(:input, "")
     |> assign(:drugs, [])
     |> assign(:findings, [])
     |> assign(:report, nil)
     |> assign(:checking, false)}
  end

  def handle_event("update_input", %{"value" => v}, socket) do
    {:noreply, assign(socket, :input, v)}
  end

  def handle_event("check", %{"input" => input}, socket) do
    drugs =
      input
      |> String.split([",", ";"])
      |> Enum.map(&String.trim/1)
      |> Enum.reject(&(&1 == ""))

    socket =
      socket
      |> assign(:drugs, drugs)
      |> assign(:input, input)
      |> assign(:checking, true)

    send(self(), {:run_check, drugs})
    {:noreply, socket}
  end

  def handle_event("clear", _params, socket) do
    {:noreply,
     socket
     |> assign(:input, "")
     |> assign(:drugs, [])
     |> assign(:findings, [])
     |> assign(:report, nil)}
  end

  def handle_info({:run_check, drugs}, socket) do
    case Orchestrator.check_drug_regimen(drugs) do
      {:ok, %{findings: findings, report: report}} ->
        {:noreply,
         socket
         |> assign(:findings, findings)
         |> assign(:report, report)
         |> assign(:checking, false)}

      _ ->
        {:noreply, assign(socket, :checking, false)}
    end
  rescue
    _ -> {:noreply, assign(socket, :checking, false)}
  end

  def render(assigns) do
    ~H"""
    <div class="aim-drug-check">
      <h1><%= t("drugs.heading", @locale) %></h1>
      <p><%= t("drugs.prompt", @locale) %></p>

      <form phx-submit="check">
        <textarea
          name="input"
          rows="3"
          placeholder="warfarin, ibuprofen, omeprazole"
          phx-change="update_input"
        ><%= @input %></textarea>
        <div class="actions">
          <button type="submit" disabled={@checking or @input == ""}>
            <%= if @checking, do: t("drugs.checking", @locale), else: t("drugs.check", @locale) %>
          </button>
          <button type="button" phx-click="clear" disabled={@input == ""}>
            <%= t("drugs.clear", @locale) %>
          </button>
        </div>
      </form>

      <section :if={@drugs != []}>
        <h2><%= t("drugs.regimen", @locale) %></h2>
        <ul class="drug-list">
          <li :for={d <- @drugs}><%= d %></li>
        </ul>
      </section>

      <section :if={@findings != []} class="findings">
        <h2><%= t("drugs.findings", @locale) %></h2>
        <table>
          <thead>
            <tr>
              <th>A</th><th>B</th>
              <th><%= t("drugs.severity", @locale) %></th>
              <th><%= t("drugs.note", @locale) %></th>
            </tr>
          </thead>
          <tbody>
            <tr :for={f <- @findings} class={"sev-#{f.severity}"}>
              <td><%= f.a %></td>
              <td><%= f.b %></td>
              <td><%= f.severity %></td>
              <td><%= f.note %></td>
            </tr>
          </tbody>
        </table>
      </section>

      <pre :if={@report} class="report"><%= @report %></pre>
    </div>
    """
  end
end
