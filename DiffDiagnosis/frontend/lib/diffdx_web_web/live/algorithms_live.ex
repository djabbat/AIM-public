defmodule DiffdxWebWeb.AlgorithmsLive do
  use DiffdxWebWeb, :live_view

  alias DiffdxWeb.DiffdxClient

  @impl true
  def mount(_params, _session, socket) do
    {algos, error} =
      case DiffdxClient.list_algorithms() do
        {:ok, body} -> {body, nil}
        {:error, e} -> {[], inspect(e)}
      end

    {:ok, assign(socket, algorithms: algos, error: error)}
  end

  @impl true
  def render(assigns) do
    ~H"""
    <div class="mx-auto max-w-3xl p-6 space-y-4">
      <h1 class="text-2xl font-bold">Banк алгоритмов</h1>

      <%= if @error do %>
        <p class="text-red-700"><%= @error %></p>
      <% end %>

      <ul class="space-y-2">
        <%= for a <- @algorithms do %>
          <li class="rounded border p-3">
            <div class="flex justify-between">
              <strong><%= a["id"] %></strong>
              <span class="text-xs text-gray-500"><%= a["system"] %></span>
            </div>
            <div class="text-sm"><%= a["presenting_complaint"] %></div>
            <div class="text-xs text-gray-500"><%= a["differentials_count"] %> диагноза(ов) в дифряду</div>
          </li>
        <% end %>
      </ul>
    </div>
    """
  end
end
