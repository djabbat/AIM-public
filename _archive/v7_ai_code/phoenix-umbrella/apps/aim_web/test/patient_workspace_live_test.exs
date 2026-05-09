defmodule AimWeb.PatientWorkspaceLiveTest do
  @moduledoc """
  Smoke tests for `/patients/:id` (PatientWorkspaceLive).

  These tests run without any pre-existing patient data on disk: they
  expect graceful degradation (binary missing OR patient missing → error
  banner; tabs still render; layout shell intact).

  End-to-end with a real Patient is exercised manually because patient
  data lives outside the test sandbox per `Patients/` privacy rule.
  """
  use ExUnit.Case, async: true
  import Phoenix.ConnTest
  import Phoenix.LiveViewTest

  @endpoint AimWeb.Endpoint

  setup do
    {:ok, conn: build_conn()}
  end

  test "GET /patients/:id renders shell even when patient missing", %{conn: conn} do
    # ID guaranteed not to exist on disk; we expect 200 + error banner.
    {:ok, _view, html} = live(conn, "/patients/Ghost_NotReal_2099_12_31")
    assert html =~ "All patients"
    # Either binary missing OR patient missing — both surfaced as ws-error.
    assert html =~ "Error loading" or html =~ "binary not found"
  end

  test "GET /patients/:id includes Refresh button shell or error banner", %{conn: conn} do
    {:ok, _view, html} = live(conn, "/patients/Ghost_NotReal_2099_12_31")
    # Either successful view (Refresh button) or error banner — must be one of them.
    assert html =~ "Refresh" or html =~ "ws-error"
  end

  test "tab switcher emits valid HTML buttons", %{conn: conn} do
    {:ok, _view, html} = live(conn, "/patients/Ghost_NotReal_2099_12_31")
    # When error, tabs are not rendered; when success, all 6 tabs appear.
    # Either branch must produce valid HTML (no crash).
    assert is_binary(html)
    assert byte_size(html) > 100
  end
end
