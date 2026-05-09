defmodule AimGateway.Application do
  @moduledoc false
  use Application

  @impl true
  def start(_type, _args) do
    children = [
      AimGateway.Endpoint
    ]

    Supervisor.start_link(children, strategy: :one_for_one, name: AimGateway.Supervisor)
  end

  @impl true
  def config_change(changed, _new, removed) do
    AimGateway.Endpoint.config_change(changed, removed)
    :ok
  end
end
