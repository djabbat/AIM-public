defmodule DiffdxWebWeb.SourcesLive do
  use DiffdxWebWeb, :live_view

  alias DiffdxWeb.DiffdxClient

  @impl true
  def mount(_params, _session, socket) do
    {sources, error} =
      case DiffdxClient.list_sources() do
        {:ok, body} -> {body, nil}
        {:error, e} -> {[], inspect(e)}
      end

    {:ok, assign(socket, sources: sources, error: error)}
  end

  @impl true
  def render(assigns) do
    ~H"""
    <div class="mx-auto max-w-3xl p-6 space-y-4">
      <h1 class="text-2xl font-bold">Канонические источники</h1>

      <%= if @error do %>
        <p class="text-red-700"><%= @error %></p>
      <% end %>

      <ul class="list-disc pl-5">
        <%= for s <- @sources do %>
          <li><%= s %></li>
        <% end %>
      </ul>
    </div>
    """
  end
end
