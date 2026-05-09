defmodule AimGateway.Endpoint do
  use Phoenix.Endpoint, otp_app: :aim_gateway

  plug Plug.Parsers,
    parsers: [:urlencoded, :multipart, :json],
    pass: ["*/*"],
    json_decoder: Phoenix.json_library()

  plug Plug.MethodOverride
  plug Plug.Head
  plug AimGateway.Router
end
