defmodule AimGateway.TelegramController do
  use Phoenix.Controller, formats: [:json]
  require Logger

  def webhook(conn, params) do
    secret = List.first(get_req_header(conn, "x-telegram-bot-api-secret-token"))

    cond do
      not AimOrchestrator.Telegram.webhook_secret_ok?(secret) ->
        conn |> put_status(:unauthorized) |> json(%{error: "bad_secret"})

      true ->
        Task.start(fn -> handle_update(params) end)
        json(conn, %{ok: true})
    end
  end

  defp handle_update(%{"message" => %{"text" => text, "chat" => %{"id" => chat_id}, "from" => %{"id" => from_id}}}) do
    cond do
      String.starts_with?(text, "/link ") ->
        code = text |> String.trim_leading("/link ") |> String.trim()
        case AimMemory.redeem_link_code(code, chat_id) do
          {:ok, link} ->
            AimOrchestrator.Telegram.send_message(chat_id,
              "✅ Linked to user #{link.username}. You can now chat.")
          {:error, reason} ->
            AimOrchestrator.Telegram.send_message(chat_id, "❌ Link failed: #{reason}")
        end

      not (AimOrchestrator.Telegram.allowed_id?(from_id) or AimMemory.chat_to_user(chat_id)) ->
        AimOrchestrator.Telegram.send_message(chat_id,
          "Доступ ограничен. Запросите код у администратора и пришлите: /link <код>")

      true ->
        reply =
          case AimOrchestrator.chat([%{role: "user", content: text}]) do
            {:ok, %{"reply" => r}} -> r
            {:error, reason} ->
              Logger.error("telegram chat failed: #{inspect(reason)}")
              "⚠ ошибка LLM. Попробуйте ещё раз."
          end
        AimOrchestrator.Telegram.send_message(chat_id, reply)
    end
  end

  defp handle_update(_), do: :ignore
end
