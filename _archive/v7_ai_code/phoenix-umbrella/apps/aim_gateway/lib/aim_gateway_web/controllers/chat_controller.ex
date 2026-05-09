defmodule AimGateway.ChatController do
  use Phoenix.Controller, formats: [:json]

  def create(conn, %{"messages" => messages} = params) do
    opts = if params["model_hint"], do: [model_hint: params["model_hint"]], else: []

    case AimOrchestrator.chat(messages, opts) do
      {:ok, body} -> json(conn, body)
      {:error, reason} -> conn |> put_status(:bad_gateway) |> json(%{error: inspect(reason)})
    end
  end
end
