defmodule AimWeb.HealthController do
  use AimWeb, :controller

  def index(conn, _params) do
    json(conn, %{
      status: "ok",
      service: "aim_web",
      version: Application.spec(:aim_web, :vsn) |> to_string(),
      timestamp: DateTime.utc_now() |> DateTime.to_iso8601()
    })
  end
end
