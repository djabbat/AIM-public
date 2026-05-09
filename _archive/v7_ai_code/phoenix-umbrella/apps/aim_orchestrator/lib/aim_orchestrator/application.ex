defmodule AimOrchestrator.Application do
  @moduledoc false
  use Application

  @impl true
  def start(_type, _args) do
    children = [
      AimOrchestrator.HubClient,
      {Task.Supervisor, name: AimOrchestrator.TaskSup}
    ]

    Supervisor.start_link(children, strategy: :one_for_one, name: AimOrchestrator.Supervisor)
  end
end
