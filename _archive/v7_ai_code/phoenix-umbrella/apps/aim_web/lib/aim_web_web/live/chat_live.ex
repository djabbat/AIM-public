defmodule AimWeb.ChatLive do
  @moduledoc """
  Чат с persistence в aim_memory: каждое сообщение и ответ — отдельная запись
  в `messages` таблице, привязанная к session_id.
  """
  use AimWeb, :live_view

  def mount(_params, _session, socket) do
    {:ok, sess} = AimMemory.start_session(nil, Atom.to_string(socket.assigns.locale))
    {:ok,
     assign(socket,
       messages: [],
       input: "",
       busy?: false,
       error: nil,
       session_id: sess.id
     )}
  end

  def handle_event("update", %{"input" => v}, socket) do
    {:noreply, assign(socket, input: v)}
  end

  def handle_event("send", %{"input" => content}, socket) do
    content = String.trim(content)
    if content == "" do
      {:noreply, socket}
    else
      AimMemory.append_message(socket.assigns.session_id, "user", content)
      msgs = socket.assigns.messages ++ [%{role: "user", content: content}]

      socket =
        socket
        |> assign(messages: msgs, input: "", busy?: true, error: nil)

      send(self(), {:run_llm, msgs})
      {:noreply, socket}
    end
  end

  def handle_info({:run_llm, msgs}, socket) do
    payload = Enum.map(msgs, fn %{role: r, content: c} -> %{role: r, content: c} end)

    case AimOrchestrator.chat(payload) do
      {:ok, %{"reply" => reply} = body} ->
        AimMemory.append_message(
          socket.assigns.session_id, "assistant", reply,
          model: body["model"] || "",
          provider: to_string(body["provider"] || "")
        )
        msgs = socket.assigns.messages ++ [%{role: "assistant", content: reply}]
        {:noreply, assign(socket, messages: msgs, busy?: false)}

      {:error, reason} ->
        {:noreply, assign(socket, busy?: false, error: inspect(reason))}
    end
  end

  def render(assigns) do
    ~H"""
    <style>
      .aim-chat { max-width: 820px; margin: 1.5rem auto; padding: 0 1rem; }
      .aim-chat-head { display:flex; justify-content:space-between; align-items:baseline; margin-bottom:0.5rem; }
      .aim-chat-head h2 { margin:0; font-size: 1.5rem; }
      .aim-chat-meta { color: var(--c-text-muted); font-size: 0.8rem; font-family:"JetBrains Mono",ui-monospace,monospace; }
      .aim-chat-log {
        display:flex; flex-direction:column; gap:0.6rem;
        min-height: 50vh; max-height: 65vh; overflow-y:auto;
        padding: 1rem; background: var(--c-card); border: 1px solid var(--c-border);
        border-radius: var(--radius-lg); margin-bottom: 0.8rem;
      }
      .aim-chat-intro {
        margin: auto 0; padding: 1.2rem; text-align:center; color: var(--c-text-muted);
      }
      .aim-chat-intro h3 { margin:0 0 0.4rem; color: var(--c-text); font-size: 1.05rem; }
      .aim-chat-bubble {
        max-width: 78%; padding: 0.7rem 0.95rem; border-radius: 14px;
        white-space: pre-wrap; word-wrap: break-word; line-height: 1.45;
        font-size: 0.95rem;
      }
      .aim-chat-bubble.user {
        align-self: flex-end; background: var(--c-accent); color: #fff;
        border-bottom-right-radius: 4px;
      }
      .aim-chat-bubble.assistant {
        align-self: flex-start; background: var(--c-accent-soft); color: var(--c-text);
        border: 1px solid var(--c-border); border-bottom-left-radius: 4px;
      }
      .aim-chat-bubble.thinking { opacity: 0.6; font-style: italic; }
      .aim-chat-bubble.thinking::after {
        content: ""; display:inline-block; width:1em;
        animation: aim-chat-dots 1.2s steps(4,end) infinite;
      }
      @keyframes aim-chat-dots { 0%{content:"";} 25%{content:".";} 50%{content:"..";} 75%{content:"...";} 100%{content:"";} }
      .aim-chat-error {
        background:#fee2e2; color:#991b1b; padding:0.5rem 0.8rem;
        border-radius:10px; margin-bottom: 0.6rem; font-size: 0.875rem;
      }
      html[data-theme="dark"] .aim-chat-error { background: rgba(239,68,68,0.18); color: #f87171; }
      html[data-theme="dark"] .aim-chat-bubble.assistant { background: #1a2440; color: #e0e3eb; border-color: #2a2f40; }
      .aim-chat-form { display:flex; gap:0.5rem; align-items:flex-end; }
      .aim-chat-form textarea {
        flex:1; resize: vertical; min-height: 2.6rem; max-height: 12rem;
        padding: 0.65rem 0.85rem; border-radius: 10px; border: 1px solid var(--c-border-strong);
        background: #fff; color: var(--c-text); font-family: inherit; font-size: 0.95rem;
      }
      html[data-theme="dark"] .aim-chat-form textarea { background:#15171f; color:#e0e3eb; border-color:#2a2f40; }
      .aim-chat-form button {
        padding: 0.6rem 1.1rem; min-width: 3rem;
        background: var(--c-accent); color:#fff; border:none; border-radius:10px;
        font-size: 1.1rem; font-weight: 600; cursor: pointer;
      }
      .aim-chat-form button:disabled { opacity: 0.5; cursor: not-allowed; }
    </style>

    <div class="aim-chat">
      <div class="aim-chat-head">
        <h2><%= t("chat.heading", @locale) %></h2>
        <span class="aim-chat-meta">session #<%= @session_id %></span>
      </div>

      <div class="aim-chat-log" id="aim-chat-log">
        <%= if @messages == [] do %>
          <div class="aim-chat-intro">
            <h3>AIM Chat</h3>
            <p>Routed via aim-llm → DeepSeek-V4 (chat) / -reasoner (deep). Type a message and press Enter to send (Shift+Enter for a newline).</p>
          </div>
        <% end %>
        <div :for={m <- @messages} class={"aim-chat-bubble " <> m.role}>
          <%= m.content %>
        </div>
        <%= if @busy? do %>
          <div class="aim-chat-bubble assistant thinking">AI thinking</div>
        <% end %>
      </div>

      <%= if @error do %>
        <div class="aim-chat-error">⚠ <%= @error %></div>
      <% end %>

      <form phx-submit="send" phx-change="update" class="aim-chat-form" id="aim-chat-form">
        <textarea name="input" rows="2" placeholder="Ask AIM…" autofocus disabled={@busy?}><%= @input %></textarea>
        <button type="submit" disabled={@busy? or String.trim(@input) == ""}>
          <%= if @busy?, do: "…", else: "↑" %>
        </button>
      </form>
    </div>
    """
  end
end
