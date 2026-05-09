import Config

env = config_env()

# Helper: read SECRET_KEY_BASE; raise in :prod, otherwise auto-generate
# a per-process random secret so accidental exposure on a public port
# can't be silently signed with a known value.
secret_key_base =
  case System.get_env("SECRET_KEY_BASE") do
    val when is_binary(val) and val != "" -> val
    _ ->
      if env == :prod do
        raise "SECRET_KEY_BASE not set"
      else
        :crypto.strong_rand_bytes(48) |> Base.encode64()
      end
  end

host = System.get_env("PHX_HOST") || "127.0.0.1"
prod? = env == :prod

# Releases set PHX_SERVER=true; the umbrella has no Application that
# auto-starts the Endpoints, so without `server: true` the HTTP
# listener never binds. Honour both PHX_SERVER and a default of true
# in :prod so `mix release` boots cleanly.
phx_server? = System.get_env("PHX_SERVER") == "true" or prod?

config :aim_web, AimWeb.Endpoint,
  server: phx_server?,
  url: [host: host, port: if(prod?, do: 443, else: 4002),
        scheme: if(prod?, do: "https", else: "http")],
  http: [
    ip: if(prod?, do: {0, 0, 0, 0}, else: {127, 0, 0, 1}),
    port: String.to_integer(System.get_env("AIM_WEB_PORT") || "4002")
  ],
  secret_key_base: secret_key_base

config :aim_gateway, AimGateway.Endpoint,
  server: phx_server?,
  http: [
    ip: if(prod?, do: {0, 0, 0, 0}, else: {127, 0, 0, 1}),
    port: String.to_integer(System.get_env("AIM_GATEWAY_PORT") || "4003")
  ],
  secret_key_base: secret_key_base
