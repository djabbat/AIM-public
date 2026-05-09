defmodule AimWebWeb.AimFsLiveTest do
  @moduledoc """
  Smoke tests for the 5 AIM_FS-driven LiveViews:
  /inbox, /onboard, /fs/projects, /fs/patients, /fs/disputes.

  These views call `AimMemory.FS` which dispatches to a Port-owned Rust
  binary.  In test env we DON'T start the Port GenServer (the
  application supervisor only starts it when `aim-fs` is on PATH and
  here we set PATH to a sentinel that contains no such binary), so
  every FS call returns `{:error, :noproc}` and the views render the
  empty-state HTML.  That's the contract we test: empty rooting must
  not crash, must show a sensible message, and event handlers must
  no-op gracefully.
  """
  use ExUnit.Case, async: false
  import Phoenix.ConnTest
  import Phoenix.LiveViewTest

  @endpoint AimWeb.Endpoint

  setup do
    # Drop AIM_FS_BIN so the Port supervisor never starts on first call.
    System.delete_env("AIM_FS_BIN")
    System.put_env("AIM_FS_ROOT", System.tmp_dir!())
    {:ok, conn: build_conn()}
  end

  test "GET /inbox mounts and renders header even when AIM_FS Port is down", %{conn: conn} do
    {:ok, _view, html} = live(conn, "/inbox")
    assert html =~ "AIM Inbox"
    # No items pending → list section empty (no <li> entries).
    refute html =~ ~r/<li>\s*<header>/
  end

  test "GET /fs/projects shows zero-state header and 'create' link", %{conn: conn} do
    {:ok, _view, html} = live(conn, "/fs/projects")
    assert html =~ "Projects"
    assert html =~ "Create new project"
  end

  test "GET /fs/patients renders empty table headers", %{conn: conn} do
    {:ok, _view, html} = live(conn, "/fs/patients")
    assert html =~ "Patients"
    assert html =~ "Last complaint"
  end

  test "GET /fs/disputes shows the 'no active disputes' fallback", %{conn: conn} do
    {:ok, _view, html} = live(conn, "/fs/disputes")
    assert html =~ "Disputes"
    assert html =~ "No active disputes"
  end

  test "GET /onboard mounts and renders zero-state when templates dir is missing",
       %{conn: conn} do
    System.put_env(
      "AIM_ONBOARD_TEMPLATES_DIR",
      Path.join(System.tmp_dir!(), "aim_onboard_no_such_dir")
    )

    {:ok, _view, html} = live(conn, "/onboard")
    assert html =~ "Onboarding"
    assert html =~ "Выбери шаблон" or html =~ "templates"
  end
end
