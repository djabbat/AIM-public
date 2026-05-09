defmodule AimWeb.Application do
  @moduledoc false
  use Application

  @impl true
  def start(_type, _args) do
    children = [
      {Phoenix.PubSub, name: AimWeb.PubSub},
      AimWeb.Endpoint
    ]

    Supervisor.start_link(children, strategy: :one_for_one, name: AimWeb.Supervisor)
  end

  @impl true
  def config_change(changed, _new, removed) do
    AimWeb.Endpoint.config_change(changed, removed)
    :ok
  end
end
