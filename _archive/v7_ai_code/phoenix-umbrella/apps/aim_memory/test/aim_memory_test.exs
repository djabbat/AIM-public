defmodule AimMemoryTest do
  use ExUnit.Case
  alias AimMemory.{Repo, AuthToken}
  import Ecto.Query

  setup do
    # Clean test tokens before each test (preserve real admin token).
    Repo.delete_all(from t in AuthToken, where: like(t.username, "test_%"))
    :ok
  end

  describe "issue_token/3 + lookup_token/1" do
    test "round-trips a freshly issued token" do
      {:ok, raw} = AimMemory.issue_token("test_alice", "user")
      assert is_binary(raw)
      assert String.length(raw) >= 40

      hash = AimMemory.hash_token(raw)
      assert %AuthToken{username: "test_alice", role: "user"} = AimMemory.lookup_token(hash)
    end

    test "rejects fabricated tokens" do
      bad = AimMemory.hash_token("not-a-real-token-#{:rand.uniform(99999)}")
      assert AimMemory.lookup_token(bad) == nil
    end

    test "different raw tokens produce different hashes" do
      {:ok, a} = AimMemory.issue_token("test_a")
      {:ok, b} = AimMemory.issue_token("test_b")
      refute a == b
      refute AimMemory.hash_token(a) == AimMemory.hash_token(b)
    end

    test "validates role" do
      assert {:error, %Ecto.Changeset{} = cs} = AimMemory.issue_token("test_x", "evil_role")
      refute cs.valid?
    end
  end

  describe "expires_at validation" do
    test "rejects malformed ISO" do
      cs = AuthToken.changeset(%AuthToken{}, %{
        token_hash: "x",
        username: "test_y",
        role: "user",
        created_at: DateTime.utc_now() |> DateTime.to_iso8601(),
        expires_at: "tomorrow"
      })
      refute cs.valid?
    end

    test "accepts proper ISO8601" do
      cs = AuthToken.changeset(%AuthToken{}, %{
        token_hash: "x",
        username: "test_z",
        role: "user",
        created_at: DateTime.utc_now() |> DateTime.to_iso8601(),
        expires_at: "2027-01-01T00:00:00Z"
      })
      assert cs.valid?
    end

    test "accepts nil/empty expires_at" do
      base = %{token_hash: "x", username: "test_n", role: "user",
               created_at: DateTime.utc_now() |> DateTime.to_iso8601()}
      assert AuthToken.changeset(%AuthToken{}, base).valid?
      assert AuthToken.changeset(%AuthToken{}, Map.put(base, :expires_at, "")).valid?
    end
  end
end
