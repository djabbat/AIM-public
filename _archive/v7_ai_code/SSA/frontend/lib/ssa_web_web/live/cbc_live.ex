defmodule SsaWebWeb.CbcLive do
  use SsaWebWeb, :live_view

  alias SsaWeb.SsaClient

  @params ~w(WBC RBC HGB HCT MCV MCH MCHC RDW PLT MPV NEUT_abs LYMPH_abs MONO_abs EOS_abs BASO_abs RETIC ESR)

  @impl true
  def mount(_params, _session, socket) do
    {:ok,
     socket
     |> assign(:sex, "male")
     |> assign(:age, ">=18")
     |> assign(:values, %{})
     |> assign(:result, nil)
     |> assign(:error, nil)
     |> assign(:params, @params)}
  end

  @impl true
  def handle_event("update", %{"cbc" => attrs}, socket) do
    sex = Map.get(attrs, "sex", socket.assigns.sex)
    age = Map.get(attrs, "age", socket.assigns.age)
    values =
      attrs
      |> Map.drop(["sex", "age"])
      |> Enum.reduce(%{}, fn {k, v}, acc ->
        case Float.parse(v) do
          {f, _} -> Map.put(acc, k, f)
          :error -> acc
        end
      end)

    {:noreply, assign(socket, sex: sex, age: age, values: values)}
  end

  @impl true
  def handle_event("submit", %{"cbc" => attrs}, socket) do
    {:noreply, _} = handle_event("update", %{"cbc" => attrs}, socket)
    case SsaClient.syndromes(socket.assigns.values, socket.assigns.sex, socket.assigns.age) do
      {:ok, body} -> {:noreply, assign(socket, result: body, error: nil)}
      {:error, e} -> {:noreply, assign(socket, error: inspect(e), result: nil)}
    end
  end

  @impl true
  def render(assigns) do
    ~H"""
    <div class="mx-auto max-w-5xl p-6 space-y-6">
      <h1 class="text-2xl font-bold">SSA · ввод полного анализа крови</h1>
      <p class="text-sm text-gray-600">
        5-зонная шкала: <span class="px-1 bg-red-100">L2</span>≪low ·
        <span class="px-1 bg-orange-100">L1</span> low ·
        <span class="px-1 bg-green-100">L0</span> opt ·
        <span class="px-1 bg-orange-100">H1</span> high ·
        <span class="px-1 bg-red-100">H2</span>≫high
      </p>

      <.form for={%{}} as={:cbc} phx-submit="submit" phx-change="update" class="grid grid-cols-2 gap-4">
        <label class="text-sm">Пол:
          <select name="cbc[sex]" class="ml-2 rounded border p-1">
            <option value="male"  selected={@sex == "male"}>муж</option>
            <option value="female" selected={@sex == "female"}>жен</option>
            <option value="any" selected={@sex == "any"}>any</option>
          </select>
        </label>
        <label class="text-sm">Возраст:
          <select name="cbc[age]" class="ml-2 rounded border p-1">
            <option value=">=18" selected>≥18</option>
          </select>
        </label>

        <%= for p <- @params do %>
          <label class="text-sm">
            <span class="inline-block w-24 font-mono"><%= p %></span>
            <input
              name={"cbc[#{p}]"}
              type="text"
              value={Map.get(@values, p, "")}
              class="rounded border p-1 w-32 font-mono text-right"
              placeholder="число"
            />
          </label>
        <% end %>

        <div class="col-span-2">
          <button type="submit" class="rounded bg-blue-600 px-4 py-2 text-white">
            Прогнать SSA
          </button>
        </div>
      </.form>

      <%= if @error do %>
        <div class="rounded border border-red-300 bg-red-50 p-3 text-red-800">
          <strong>Backend error:</strong> <%= @error %>
          <p class="text-xs mt-2">Запусти: <code>cd backend && cargo run</code> (port 8766)</p>
        </div>
      <% end %>

      <%= if @result do %>
        <div class="space-y-4">
          <h2 class="text-xl font-semibold">Результат</h2>
          <p>
            🔴 red: <strong><%= @result["red_count"] %></strong> ·
            🟠 amber: <strong><%= @result["amber_count"] %></strong> ·
            🟢 green: <strong><%= @result["green_count"] %></strong>
          </p>

          <h3 class="text-lg font-semibold">Цифровизованный вектор</h3>
          <div class="grid grid-cols-3 gap-2 font-mono text-xs">
            <%= for v <- @result["digitized"] do %>
              <div class={zone_class(v["zone"])}>
                <%= v["param"] %> = <%= v["value"] %> <%= v["unit"] %> → <strong><%= v["zone"] %></strong>
              </div>
            <% end %>
          </div>

          <h3 class="text-lg font-semibold">Сработавшие синдромальные паттерны</h3>
          <%= if @result["patterns"] == [] do %>
            <p class="text-gray-600">Никакой синдромальный паттерн не сработал.</p>
          <% else %>
            <ol class="space-y-2">
              <%= for p <- @result["patterns"] do %>
                <li class={severity_class(p["severity"])}>
                  <div class="flex justify-between">
                    <strong><%= p["label"] %></strong>
                    <span class="text-xs uppercase"><%= p["severity"] %></span>
                  </div>
                  <div class="text-xs text-gray-500"><%= p["id"] %></div>
                  <div class="text-sm mt-1">
                    <strong>Дифряд:</strong> <%= Enum.join(p["differentials"], ", ") %>
                  </div>
                </li>
              <% end %>
            </ol>
          <% end %>
        </div>
      <% end %>
    </div>
    """
  end

  defp zone_class("L2"), do: "rounded bg-red-100 px-2 py-1"
  defp zone_class("L1"), do: "rounded bg-orange-100 px-2 py-1"
  defp zone_class("L0"), do: "rounded bg-green-100 px-2 py-1"
  defp zone_class("H1"), do: "rounded bg-orange-100 px-2 py-1"
  defp zone_class("H2"), do: "rounded bg-red-100 px-2 py-1"
  defp zone_class(_),    do: "rounded bg-gray-100 px-2 py-1"

  defp severity_class("red"),   do: "rounded border-2 border-red-500 bg-red-50 p-3"
  defp severity_class("amber"), do: "rounded border-2 border-orange-400 bg-orange-50 p-3"
  defp severity_class(_),       do: "rounded border bg-white p-3"
end
