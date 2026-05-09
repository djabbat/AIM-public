defmodule AimWeb.CasesLive do
  use AimWeb, :live_view

  def mount(_params, _session, socket) do
    cases = case AimOrchestrator.Doctor.list_cases() do
      {:ok, ids} when is_list(ids) -> ids
      _ -> []
    end
    {:ok, assign(socket, cases: cases, error: nil)}
  end

  def render(assigns) do
    ~H"""
    <h2><%= t("cases.heading", @locale) %></h2>

    <%= if @cases == [] do %>
      <p>No cases yet. <a href="/intake">Open intake →</a></p>
    <% else %>
      <ul>
        <li :for={id <- @cases}>
          <a href={"/cases/" <> id}><%= id %></a>
        </li>
      </ul>
    <% end %>
    """
  end
end
