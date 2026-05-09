defmodule AimWeb.IntakeLive do
  use AimWeb, :live_view

  def mount(_params, _session, socket) do
    {:ok, assign(socket, complaint: "", language: "ru", busy?: false, result: nil, error: nil)}
  end

  def handle_event("update", %{"complaint" => c, "language" => l}, socket) do
    {:noreply, assign(socket, complaint: c, language: l)}
  end

  def handle_event("submit", %{"complaint" => c, "language" => l}, socket) do
    if String.trim(c) == "" do
      {:noreply, socket}
    else
      send(self(), {:run_intake, c, l})
      {:noreply, assign(socket, busy?: true, error: nil, result: nil)}
    end
  end

  def handle_info({:run_intake, c, l}, socket) do
    case AimOrchestrator.Doctor.intake(c, l) do
      {:ok, body} -> {:noreply, assign(socket, busy?: false, result: body)}
      {:error, r} -> {:noreply, assign(socket, busy?: false, error: inspect(r))}
    end
  end

  def render(assigns) do
    ~H"""
    <h2><%= t("intake.heading", @locale) %></h2>

    <form phx-submit="submit" phx-change="update">
      <textarea name="complaint" rows="5" required disabled={@busy?}><%= @complaint %></textarea>
      <select name="language" disabled={@busy?}>
        <option value="ru" selected={@language == "ru"}>Русский</option>
        <option value="en" selected={@language == "en"}>English</option>
        <option value="ka" selected={@language == "ka"}>ქართული</option>
      </select>
      <button type="submit" disabled={@busy?}>
        <%= if @busy?, do: "…", else: "→" %>
      </button>
    </form>

    <%= if @error do %>
      <div class="error">⚠ <%= @error %></div>
    <% end %>

    <%= if @result do %>
      <h3>Case ID: <code><%= @result["case_id"] %></code></h3>
      <a href={"/cases/" <> @result["case_id"]}>Открыть случай →</a>
      <pre><%= Jason.encode!(@result["structured"], pretty: true) %></pre>
    <% end %>
    """
  end
end
