import Config

config :aim_web, AimWeb.Endpoint,
  http: [ip: {127, 0, 0, 1}, port: 4102],
  secret_key_base: String.duplicate("a", 64),
  server: false

config :aim_gateway, AimGateway.Endpoint,
  http: [ip: {127, 0, 0, 1}, port: 4103],
  secret_key_base: String.duplicate("a", 64),
  server: false

config :logger, level: :warning
