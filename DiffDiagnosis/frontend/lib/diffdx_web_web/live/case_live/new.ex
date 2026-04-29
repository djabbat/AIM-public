defmodule DiffdxWebWeb.CaseLive.New do
  use DiffdxWebWeb, :live_view

  alias DiffdxWeb.DiffdxClient

  @impl true
  def mount(_params, _session, socket) do
    {:ok,
     socket
     |> assign(:free_text, "")
     |> assign(:result, nil)
     |> assign(:error, nil)
     |> assign(:loading, false)}
  end

  @impl true
  def handle_event("update", %{"case" => %{"free_text" => text}}, socket) do
    {:noreply, assign(socket, :free_text, text)}
  end

  @impl true
  def handle_event("submit", %{"case" => %{"free_text" => text}}, socket) do
    socket = assign(socket, loading: true, error: nil)

    case DiffdxClient.diff(text) do
      {:ok, body} ->
        {:noreply, assign(socket, result: body, loading: false)}

      {:error, e} ->
        {:noreply, assign(socket, error: inspect(e), loading: false)}
    end
  end

  @impl true
  def render(assigns) do
    ~H"""
    <div class="mx-auto max-w-3xl p-6 space-y-6">
      <h1 class="text-2xl font-bold">DiffDiagnosis · ввод случая</h1>

      <.form for={%{}} as={:case} phx-submit="submit" phx-change="update" class="space-y-3">
        <textarea
          name="case[free_text]"
          rows="10"
          class="w-full rounded border p-3 font-mono text-sm"
          placeholder="Жалобы, анамнез, статус, минимальная параклиника..."
        ><%= @free_text %></textarea>

        <button type="submit" class="rounded bg-blue-600 px-4 py-2 text-white" disabled={@loading}>
          <%= if @loading, do: "Прогон...", else: "Прогнать дифдиагностику" %>
        </button>
      </.form>

      <%= if @error do %>
        <div class="rounded border border-red-300 bg-red-50 p-3 text-red-800">
          <strong>Ошибка backend:</strong> <%= @error %>
          <p class="text-xs mt-2">Запусти Rust API: <code>cd backend && cargo run</code></p>
        </div>
      <% end %>

      <%= if @result do %>
        <div class="space-y-3">
          <h2 class="text-xl font-semibold">Дифференциальный ряд</h2>

          <%= if @result["red_flags"] && @result["red_flags"] != [] do %>
            <div class="rounded border border-red-400 bg-red-50 p-3">
              <strong>⚠ Red flags:</strong>
              <ul class="list-disc pl-5">
                <%= for rf <- @result["red_flags"] do %>
                  <li><%= rf %></li>
                <% end %>
              </ul>
            </div>
          <% end %>

          <p class="text-sm text-gray-600">
            Сработавшие алгоритмы: <%= Enum.join(@result["algorithms_matched"] || [], ", ") %>
          </p>

          <ol class="space-y-2">
            <%= for d <- @result["differentials"] || [] do %>
              <li class={[
                "rounded border p-3",
                d["red_flag"] && "border-red-400 bg-red-50",
                !d["red_flag"] && "border-gray-200 bg-white"
              ]}>
                <div class="flex justify-between">
                  <strong><%= d["name"] %></strong>
                  <span class="font-mono text-sm">
                    <%= :erlang.float_to_binary(d["probability"] * 1.0, decimals: 2) %>
                  </span>
                </div>
                <div class="text-xs text-gray-500"><%= d["source_algorithm"] %> · <%= d["source_school"] %></div>
                <%= if d["evidence_for"] != [] do %>
                  <div class="text-sm mt-1"><strong>За:</strong> <%= Enum.join(d["evidence_for"], ", ") %></div>
                <% end %>
              </li>
            <% end %>
          </ol>
        </div>
      <% end %>
    </div>
    """
  end
end
