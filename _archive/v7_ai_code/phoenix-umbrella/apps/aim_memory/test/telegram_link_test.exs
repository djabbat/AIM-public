defmodule AimMemory.TelegramLinkTest do
  use ExUnit.Case
  alias AimMemory.Repo
  import Ecto.Query

  setup do
    Repo.delete_all(from t in AimMemory.TelegramLink, where: like(t.username, "test_%"))
    :ok
  end

  test "issue_link_code returns 6-digit numeric code" do
    {:ok, code} = AimMemory.issue_link_code("test_alice")
    assert String.length(code) == 6
    assert code =~ ~r/^\d{6}$/
  end

  test "redeem_link_code with valid code binds chat_id" do
    {:ok, code} = AimMemory.issue_link_code("test_bob")
    assert {:ok, link} = AimMemory.redeem_link_code(code, 555_001)
    assert link.chat_id == 555_001
    assert link.consumed_at != nil
  end

  test "redeem_link_code returns :unknown_code for non-existent" do
    assert {:error, :unknown_code} = AimMemory.redeem_link_code("000000", 1)
  end

  test "redeem_link_code rejects already-consumed code" do
    {:ok, code} = AimMemory.issue_link_code("test_carol")
    {:ok, _} = AimMemory.redeem_link_code(code, 555_002)
    assert {:error, :already_consumed} = AimMemory.redeem_link_code(code, 555_003)
  end

  test "chat_to_user resolves bound chat to link record" do
    {:ok, code} = AimMemory.issue_link_code("test_dave")
    {:ok, _} = AimMemory.redeem_link_code(code, 555_004)
    link = AimMemory.chat_to_user(555_004)
    assert link.username == "test_dave"
  end

  test "chat_to_user returns nil for unbound chat" do
    assert AimMemory.chat_to_user(999_999) == nil
  end
end
