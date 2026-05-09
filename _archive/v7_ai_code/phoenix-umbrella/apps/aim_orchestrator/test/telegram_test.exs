defmodule AimOrchestrator.TelegramTest do
  use ExUnit.Case
  alias AimOrchestrator.Telegram

  setup do
    System.delete_env("TELEGRAM_ALLOWED_IDS")
    System.delete_env("TELEGRAM_WEBHOOK_SECRET")
    :ok
  end

  test "allowed_id?/1 lets everyone through when env is unset" do
    assert Telegram.allowed_id?(123)
  end

  test "allowed_id?/1 enforces explicit list" do
    System.put_env("TELEGRAM_ALLOWED_IDS", "100,200,300")
    assert Telegram.allowed_id?(200)
    refute Telegram.allowed_id?(999)
  end

  test "webhook_secret_ok?/1 ok when env unset" do
    assert Telegram.webhook_secret_ok?(nil)
    assert Telegram.webhook_secret_ok?("anything")
  end

  test "webhook_secret_ok?/1 strict when env set" do
    System.put_env("TELEGRAM_WEBHOOK_SECRET", "s3cr3t")
    refute Telegram.webhook_secret_ok?(nil)
    refute Telegram.webhook_secret_ok?("wrong")
    assert Telegram.webhook_secret_ok?("s3cr3t")
  end

  test "send_message/2 fails gracefully without bot token" do
    System.delete_env("TELEGRAM_BOT_TOKEN")
    assert {:error, :no_token} = Telegram.send_message(1, "hi")
  end
end
