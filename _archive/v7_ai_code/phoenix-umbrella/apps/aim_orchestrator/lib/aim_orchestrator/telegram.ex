defmodule AimOrchestrator.Telegram do
  @moduledoc """
  Minimal Telegram Bot API client. Replaces sending paths from telegram_bot.py.

  Bot token: TELEGRAM_BOT_TOKEN env.
  Webhook secret (optional): TELEGRAM_WEBHOOK_SECRET — checked against
  X-Telegram-Bot-Api-Secret-Token header by AimGateway.TelegramController.
  """

  @timeout_ms 20_000

  def send_message(chat_id, text, opts \\ []) do
    with {:ok, token} <- token() do
      body = %{chat_id: chat_id, text: text}
      body = if Keyword.get(opts, :parse_mode), do: Map.put(body, :parse_mode, opts[:parse_mode]), else: body

      Req.post("https://api.telegram.org/bot#{token}/sendMessage",
        json: body, receive_timeout: @timeout_ms)
      |> normalize()
    end
  end

  def allowed_id?(id) when is_integer(id) do
    case System.get_env("TELEGRAM_ALLOWED_IDS") do
      nil -> true
      "" -> true
      v ->
        v
        |> String.split(",", trim: true)
        |> Enum.map(&String.trim/1)
        |> Enum.any?(&(&1 == Integer.to_string(id)))
    end
  end

  def webhook_secret_ok?(provided) do
    case System.get_env("TELEGRAM_WEBHOOK_SECRET") do
      nil -> true
      "" -> true
      expected -> Plug.Crypto.secure_compare(expected, provided || "")
    end
  end

  defp token do
    case System.get_env("TELEGRAM_BOT_TOKEN") do
      nil -> {:error, :no_token}
      "" -> {:error, :no_token}
      t -> {:ok, t}
    end
  end

  defp normalize({:ok, %Req.Response{status: s, body: b}}) when s in 200..299, do: {:ok, b}
  defp normalize({:ok, %Req.Response{status: s, body: b}}), do: {:error, {:upstream, s, b}}
  defp normalize({:error, e}), do: {:error, {:transport, Exception.message(e)}}
end
