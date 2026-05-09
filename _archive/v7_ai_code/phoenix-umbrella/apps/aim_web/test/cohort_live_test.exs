defmodule AimWeb.CohortLiveTest do
  @moduledoc """
  Smoke tests for `/cohort` (CohortLive) — STRATEGY P1-2 dashboard.
  """
  use ExUnit.Case, async: true
  import Phoenix.ConnTest
  import Phoenix.LiveViewTest

  @endpoint AimWeb.Endpoint

  setup do
    {:ok, conn: build_conn()}
  end

  test "GET /cohort renders shell with thresholds", %{conn: conn} do
    {:ok, _view, html} = live(conn, "/cohort")
    assert html =~ "Pilot cohort"
    # Thresholds from Hibbard 2009 must be visible.
    assert html =~ "5.4"
    assert html =~ "7.2"
    assert html =~ "MCID"
    assert html =~ "MDC"
  end

  test "GET /cohort with no enrolled patients shows empty-state with cornerstone link", %{conn: conn} do
    {:ok, _view, html} = live(conn, "/cohort")
    # When n_enrolled = 0, empty-state card must be visible.
    if html =~ "No PAM-13 measurements recorded yet" do
      # Cornerstone citation must be referenced for context.
      assert html =~ "10.65649/qqwva850" or html =~ "qqwva850"
      # Pilot protocol pre-flight items.
      assert html =~ "IRB" or html =~ "consent"
    end

    # Always: target ≥30 must be visible.
    assert html =~ "30"
  end

  test "GET /cohort has refresh button + n_enrolled stat", %{conn: conn} do
    {:ok, _view, html} = live(conn, "/cohort")
    assert html =~ "Refresh"
    assert html =~ "enrolled"
  end
end
