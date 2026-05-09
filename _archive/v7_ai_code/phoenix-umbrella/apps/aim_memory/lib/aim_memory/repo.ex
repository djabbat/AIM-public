defmodule AimMemory.Repo do
  use Ecto.Repo,
    otp_app: :aim_memory,
    adapter: Ecto.Adapters.SQLite3
end
