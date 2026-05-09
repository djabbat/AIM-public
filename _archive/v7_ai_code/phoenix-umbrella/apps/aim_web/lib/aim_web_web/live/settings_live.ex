defmodule AimWeb.SettingsLive do
  @moduledoc """
  Per-user settings: language, provider keys (hidden), node identity.
  Replaces the Python `m8 → settings` menu and the /setkey Telegram flow.
  Provider keys never round-trip back to the browser; only the boolean
  "set" status is shown.
  """
  use AimWeb, :live_view

  @providers ~w(deepseek groq anthropic gemini)

  def mount(_params, _session, socket) do
    {:ok,
     socket
     |> assign(:providers, @providers)
     |> assign(:active, fetch_active_keys())
     |> assign(:status, nil)}
  end

  def handle_event("set_key", %{"provider" => p, "value" => v}, socket) do
    cond do
      p not in @providers ->
        {:noreply, assign(socket, :status, {:error, "unknown provider"})}

      String.length(v) < 8 ->
        {:noreply, assign(socket, :status, {:error, "key too short"})}

      true ->
        Orchestrator.set_user_key(p, v)
        {:noreply,
         socket
         |> assign(:active, fetch_active_keys())
         |> assign(:status, {:ok, "saved #{p}"})}
    end
  rescue
    _ -> {:noreply, assign(socket, :status, {:error, "save failed"})}
  end

  def handle_event("clear_key", %{"provider" => p}, socket) do
    Orchestrator.clear_user_key(p)
    {:noreply,
     socket
     |> assign(:active, fetch_active_keys())
     |> assign(:status, {:ok, "cleared #{p}"})}
  rescue
    _ -> {:noreply, assign(socket, :status, {:error, "clear failed"})}
  end

  def handle_event("clear_all", _params, socket) do
    Enum.each(@providers, &Orchestrator.clear_user_key/1)
    {:noreply,
     socket
     |> assign(:active, [])
     |> assign(:status, {:ok, "all cleared"})}
  rescue
    _ -> {:noreply, assign(socket, :status, {:error, "clear failed"})}
  end

  defp fetch_active_keys do
    case Orchestrator.list_user_keys() do
      {:ok, list} -> list
      _ -> []
    end
  rescue
    _ -> []
  end

  def render(assigns) do
    ~H"""
    <div class="aim-settings">
      <h1><%= t("settings.heading", @locale) %></h1>

      <p :if={@status} class={"status status-#{elem(@status, 0)}"}>
        <%= elem(@status, 1) %>
      </p>

      <section>
        <h2><%= t("settings.keys", @locale) %></h2>
        <p class="hint"><%= t("settings.keys_hint", @locale) %></p>

        <ul class="provider-list">
          <li :for={p <- @providers}>
            <span class="provider-name">
              <%= if p in @active, do: "✓", else: "·" %>
              <%= p %>
            </span>
            <form phx-submit="set_key" class="key-form">
              <input type="hidden" name="provider" value={p} />
              <input
                type="password"
                name="value"
                autocomplete="off"
                placeholder={t("settings.key_placeholder", @locale)}
              />
              <button type="submit"><%= t("settings.save", @locale) %></button>
            </form>
            <button
              :if={p in @active}
              phx-click="clear_key"
              phx-value-provider={p}
              class="clear"
            >
              <%= t("settings.clear", @locale) %>
            </button>
          </li>
        </ul>

        <button phx-click="clear_all" class="clear-all">
          <%= t("settings.clear_all", @locale) %>
        </button>
      </section>
    </div>
    """
  end
end
