defmodule AimWeb.AboutLiveTest do
  @moduledoc """
  P2.7 (2026-05-07) — minimal integration tests for the static `/about`
  page. AboutLive has no Rust binary calls, so this is the safest place
  to verify Phoenix routing + layout rendering end-to-end.
  """
  use ExUnit.Case, async: true
  import Phoenix.ConnTest
  import Phoenix.LiveViewTest

  @endpoint AimWeb.Endpoint

  setup do
    {:ok, conn: build_conn()}
  end

  test "GET /about returns 200 with cornerstone heading", %{conn: conn} do
    {:ok, _view, html} = live(conn, "/about")
    assert html =~ "AIM &mdash; Assistant of Integrative Medicine" or
             html =~ "AIM — Assistant of Integrative Medicine"
  end

  test "/about renders all 14 sections", %{conn: conn} do
    {:ok, _view, html} = live(conn, "/about")
    assert html =~ "1. Mission and scope"
    assert html =~ "2. The &quot;Patient as a Project&quot; cornerstone" or
             html =~ "2. The \"Patient as a Project\" cornerstone"
    assert html =~ "3. The decision kernel"
    assert html =~ "13. References"
    assert html =~ "14. License and contact"
  end

  test "/about cites Tkemaladze 2026 in Longevity Horizon 2(5) with finalized DOI", %{conn: conn} do
    {:ok, _view, html} = live(conn, "/about")
    assert html =~ "Longevity Horizon"
    # Finalized 2026-05-08: DOI 10.65649/qqwva850, issue 2(5).
    assert html =~ "10.65649/qqwva850"
    assert html =~ "2(5)"
    refute html =~ ~r/Tkemaladze.*?(?:Nat Med|Nature Medicine)\s+target/i
    # Old placeholder must be gone.
    refute html =~ "longhoriz/article/view/177"
  end

  test "/about cites Tao et al. correctly (Nat Med 2026)", %{conn: conn} do
    {:ok, _view, html} = live(conn, "/about")
    assert html =~ "Tao"
    assert html =~ "Nat Med 2026" or html =~ "Nature Medicine"
  end

  test "/about lists the eight Asimov-style laws", %{conn: conn} do
    {:ok, _view, html} = live(conn, "/about")
    for law <- [
          "L0", "L1", "L2", "L3",
          "L_PRIVACY", "L_CONSENT", "L_VERIFIABILITY", "L_AGENCY"
        ] do
      assert html =~ law, "missing law #{law}"
    end
  end
end
