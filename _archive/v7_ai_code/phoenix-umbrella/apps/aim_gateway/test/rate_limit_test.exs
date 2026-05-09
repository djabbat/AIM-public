defmodule AimGateway.Plugs.RateLimitTest do
  use ExUnit.Case
  import Plug.Test
  import Plug.Conn
  alias AimGateway.Plugs.RateLimit

  setup do
    System.delete_env("AIM_RATE_LIMIT_DISABLE")
    System.put_env("AIM_RPM_IP", "3")
    # Clear any existing ETS entries so tests are independent.
    if :ets.info(:aim_rate_limit) != :undefined do
      :ets.delete_all_objects(:aim_rate_limit)
    end
    :ok
  end

  defp make_conn(ip \\ {127, 0, 0, 99}) do
    %{conn(:get, "/x") | remote_ip: ip}
    |> assign(:auth, %{anonymous: true})
  end

  test "allows up to limit per IP" do
    Enum.each(1..3, fn _ ->
      out = RateLimit.call(make_conn(), [])
      refute out.halted
    end)
  end

  test "halts on 4th request (limit=3)" do
    Enum.each(1..3, fn _ -> RateLimit.call(make_conn(), []) end)
    out = RateLimit.call(make_conn(), [])
    assert out.halted
    assert out.status == 429
  end

  test "different IPs have independent buckets" do
    Enum.each(1..3, fn _ -> RateLimit.call(make_conn({127, 0, 0, 1}), []) end)
    out = RateLimit.call(make_conn({127, 0, 0, 2}), [])
    refute out.halted
  end

  test "disabled flag bypasses limiter" do
    System.put_env("AIM_RATE_LIMIT_DISABLE", "1")
    Enum.each(1..10, fn _ ->
      out = RateLimit.call(make_conn(), [])
      refute out.halted
    end)
  end
end
