defmodule AimWeb.Endpoint do
  use Phoenix.Endpoint, otp_app: :aim_web

  @session_options [
    store: :cookie,
    key: "_aim_web_key",
    signing_salt: "aimweb01",
    same_site: "Lax"
  ]

  socket "/live", Phoenix.LiveView.Socket,
    websocket: [connect_info: [session: @session_options]]

  plug Plug.Static,
    at: "/",
    from: :aim_web,
    gzip: false,
    only: AimWeb.static_paths()

  plug Plug.RequestId
  plug Plug.Telemetry, event_prefix: [:phoenix, :endpoint]

  plug Plug.Parsers,
    parsers: [:urlencoded, :multipart, :json],
    pass: ["*/*"],
    json_decoder: Phoenix.json_library()

  plug Plug.MethodOverride
  plug Plug.Head
  plug Plug.Session, @session_options

  plug AimWeb.Router
end
