defmodule AimGateway.Plugs.AuthTokenTest do
  use ExUnit.Case
  import Plug.Test
  import Plug.Conn
  alias AimGateway.Plugs.AuthToken
  alias AimMemory.Repo
  import Ecto.Query

  setup do
    Repo.delete_all(from t in AimMemory.AuthToken, where: like(t.username, "test_%"))
    System.delete_env("AIM_REQUIRE_AUTH")
    :ok
  end

  test "in dev (require=0), no token → anonymous" do
    out = conn(:get, "/x") |> AuthToken.call([])
    assert out.assigns.auth.anonymous == true
  end

  test "with valid token → assigns username/role" do
    {:ok, raw} = AimMemory.issue_token("test_alice", "user")
    out =
      conn(:get, "/x")
      |> put_req_header("authorization", "Bearer #{raw}")
      |> AuthToken.call([])
    assert out.assigns.auth.username == "test_alice"
    assert out.assigns.auth.role == "user"
    refute out.assigns.auth.anonymous
  end

  test "with invalid token → 401 + halt" do
    out =
      conn(:get, "/x")
      |> put_req_header("authorization", "Bearer not-real")
      |> AuthToken.call([])
    assert out.status == 401
    assert out.halted
  end

  test "in prod (require=1), no token → 401" do
    System.put_env("AIM_REQUIRE_AUTH", "1")
    out = conn(:get, "/x") |> AuthToken.call([])
    assert out.status == 401
    assert out.halted
  end

  test "?token= query param accepted" do
    {:ok, raw} = AimMemory.issue_token("test_qparam", "user")
    out =
      conn(:get, "/x?token=#{raw}")
      |> Plug.Conn.fetch_query_params()
      |> AuthToken.call([])
    assert out.assigns.auth.username == "test_qparam"
  end
end
