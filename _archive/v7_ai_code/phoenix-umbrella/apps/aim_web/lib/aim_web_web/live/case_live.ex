defmodule AimWeb.CaseLive do
  use AimWeb, :live_view

  def mount(%{"id" => id}, _session, socket) do
    {case_data, error} =
      case AimOrchestrator.Doctor.get_case(id) do
        {:ok, c} -> {c, nil}
        {:error, e} -> {nil, inspect(e)}
      end
    {:ok, assign(socket, case_id: id, case_data: case_data, error: error,
                          busy?: false, diagnosis: nil)}
  end

  def handle_event("diagnose", _, socket) do
    send(self(), {:run_diagnose, socket.assigns.case_id})
    {:noreply, assign(socket, busy?: true)}
  end

  def handle_info({:run_diagnose, id}, socket) do
    case AimOrchestrator.Doctor.diagnose(id) do
      {:ok, d} -> {:noreply, assign(socket, busy?: false, diagnosis: d)}
      {:error, e} -> {:noreply, assign(socket, busy?: false, error: inspect(e))}
    end
  end

  def render(assigns) do
    ~H"""
    <h2><%= t("case.heading", @locale) %> <%= @case_id %></h2>

    <%= if @error do %>
      <div class="error">⚠ <%= @error %></div>
    <% end %>

    <%= if @case_data do %>
      <h3>Intake</h3>
      <pre><%= Jason.encode!(@case_data["structured"], pretty: true) %></pre>

      <button phx-click="diagnose" disabled={@busy?}>
        <%= if @busy?, do: "Анализ…", else: "Запустить диагностику" %>
      </button>
    <% end %>

    <%= if @diagnosis do %>
      <h3>Differentials</h3>
      <pre><%= Jason.encode!(@diagnosis["differentials"], pretty: true) %></pre>
      <h3>Plan</h3>
      <pre><%= @diagnosis["plan"] %></pre>
      <%= if @diagnosis["errors"] not in [nil, []] do %>
        <h3>Upstream errors</h3>
        <pre><%= Jason.encode!(@diagnosis["errors"], pretty: true) %></pre>
      <% end %>
    <% end %>
    """
  end
end
