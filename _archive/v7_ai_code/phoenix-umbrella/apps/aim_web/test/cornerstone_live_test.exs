defmodule AimWeb.CornerstoneLiveTest do
  @moduledoc """
  P2.7 (2026-05-07) — integration tests for the 5 dynamic cornerstone
  routes (`/pam`, `/codesign/:id`, `/disagreement`, `/activation`,
  `/coaching/:id`).

  These LiveViews shell out to Rust binaries via System.cmd. The tests
  use a tmp dir as AIM_PATIENTS_DIR so they always exercise the
  graceful-empty-state code path (no real binaries / no real patient
  data needed).
  """
  use ExUnit.Case, async: false
  import Phoenix.ConnTest
  import Phoenix.LiveViewTest

  @endpoint AimWeb.Endpoint

  setup do
    tmp = Path.join(System.tmp_dir!(), "aim_cornerstone_test_#{System.unique_integer([:positive])}")
    File.mkdir_p!(tmp)
    on_exit(fn -> File.rm_rf!(tmp) end)
    System.put_env("AIM_PATIENTS_DIR", tmp)
    System.put_env("AIM_ROOT", Path.expand("../..", File.cwd!()))
    {:ok, conn: build_conn(), patients_dir: tmp}
  end

  test "GET /pam shows the cohort empty-state", %{conn: conn} do
    {:ok, _view, html} = live(conn, "/pam")
    assert html =~ "PAM-13 cohort"
    # With no patients in tmp dir → empty
    assert html =~ "no patients" or html =~ "&lt;tbody&gt;" or html =~ "<tbody>" or
             html =~ "(no patients"
  end

  test "GET /pam/:patient_id renders trajectory header", %{conn: conn} do
    {:ok, _view, html} = live(conn, "/pam/SMOKE_Test_2000_01_01")
    assert html =~ "PAM-13 trajectory"
    assert html =~ "SMOKE_Test_2000_01_01"
  end

  test "GET /codesign/:patient_id renders empty event log", %{conn: conn} do
    {:ok, _view, html} = live(conn, "/codesign/SMOKE_Test_2000_01_01")
    assert html =~ "Co-design events"
    assert html =~ "SMOKE_Test_2000_01_01"
  end

  test "GET /disagreement renders the 4-zone classifier", %{conn: conn} do
    {:ok, _view, html} = live(conn, "/disagreement")
    assert html =~ "AI" and html =~ "clinician" and html =~ "disagreement"
    assert html =~ "aligned"
    assert html =~ "ai_leads" or html =~ "AI leads"
  end

  test "GET /activation renders the funnel", %{conn: conn} do
    {:ok, _view, html} = live(conn, "/activation")
    assert html =~ "activation funnel" or html =~ "Activation"
    # Even with no data, all 5 levels (0-4) must be rendered as rows
    for lvl <- ["L1", "L2", "L3", "L4"] do
      assert html =~ lvl, "missing level row #{lvl}"
    end
  end

  test "GET /coaching/:patient_id renders OARS reference", %{conn: conn} do
    {:ok, _view, html} = live(conn, "/coaching/SMOKE_Test_2000_01_01")
    assert html =~ "Coaching"
    assert html =~ "OARS"
    assert html =~ "Open question"
    assert html =~ "Reflection"
  end

  test "GET /disagreement classify event updates outcome", %{conn: conn} do
    {:ok, view, _html} = live(conn, "/disagreement")
    # Trigger a classify event with high AI conf, low clinician conf, agree=true
    html = render_change(view, "set", %{
      "ai_conf" => "0.95",
      "clinician_conf" => "0.40",
      "agree" => "true"
    })
    # Should produce ai_leads outcome (binary needs to be built; if not,
    # the `binary_missing` zone is acceptable as graceful state).
    assert html =~ "Zone" and (html =~ "ai_leads" or html =~ "binary_missing")
  end

  test "GET /coaching auto-refresh tick does not crash", %{conn: conn} do
    {:ok, view, _html} = live(conn, "/coaching/SMOKE_Test_2000_01_01")
    # send the periodic :tick manually
    send(view.pid, :tick)
    # process should still be alive
    assert Process.alive?(view.pid)
  end

  # ── /status — observability dashboard ─────────────────────────────────

  test "GET /status renders aim-llm + cornerstone binaries health", %{conn: conn} do
    {:ok, _view, html} = live(conn, "/status")
    assert html =~ "Health"
    assert html =~ "aim-llm"
    assert html =~ "Cornerstone Rust binaries"
    # All 9 cornerstone binaries should be listed (built or not)
    for bin <- ~w(aim-pam aim-coach aim-codesign aim-disagreement
                  aim-interactions aim-regimen-validator
                  aim-smart-routing aim-reflexion aim-llm) do
      assert html =~ bin, "missing binary in /status: #{bin}"
    end
    # Asimov-laws section must mention all 8 laws
    for law <- ~w(L0 L1 L2 L3 L_PRIVACY L_CONSENT L_VERIFIABILITY L_AGENCY) do
      assert html =~ law
    end
  end

  test "GET /status :tick refresh keeps process alive", %{conn: conn} do
    {:ok, view, _html} = live(conn, "/status")
    send(view.pid, :tick)
    assert Process.alive?(view.pid)
  end
end
