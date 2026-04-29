defmodule DiffdxWebWeb.CaseLiveTest do
  use DiffdxWebWeb.ConnCase
  import Phoenix.LiveViewTest

  test "GET / renders DiffDiagnosis input form", %{conn: conn} do
    {:ok, _view, html} = live(conn, ~p"/")
    assert html =~ "DiffDiagnosis"
    assert html =~ "Прогнать дифдиагностику"
  end

  test "GET /sources renders sources list (with backend down it shows error gracefully)", %{conn: conn} do
    {:ok, _view, html} = live(conn, ~p"/sources")
    assert html =~ "Канонические источники"
  end

  test "GET /algorithms renders algorithms list", %{conn: conn} do
    {:ok, _view, html} = live(conn, ~p"/algorithms")
    assert html =~ "Banк алгоритмов"
  end
end
