import Config

# We don't run a server during test. If one is required,
# you can enable the server option below.
config :aim_web, AimWebWeb.Endpoint,
  http: [ip: {127, 0, 0, 1}, port: 4002],
  secret_key_base: "+Oc2HXxl05IuZlcNdWm6f30Zg0SFb0q5AEsqt1U1pisAg36XuZyx3Of3lhM0sH//",
  server: false

# Print only warnings and errors during test
config :logger, level: :warning

# Initialize plugs at runtime for faster test compilation
config :phoenix, :plug_init_mode, :runtime

# Enable helpful, but potentially expensive runtime checks
config :phoenix_live_view,
  enable_expensive_runtime_checks: true

# Sort query params output of verified routes for robust url comparisons
config :phoenix,
  sort_verified_routes_query_params: true
