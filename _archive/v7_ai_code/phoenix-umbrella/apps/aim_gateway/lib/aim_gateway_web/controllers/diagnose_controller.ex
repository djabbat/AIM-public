defmodule AimGateway.DiagnoseController do
  use Phoenix.Controller, formats: [:json]

  def create(conn, %{"case_id" => case_id}) do
    case AimOrchestrator.diagnose(case_id) do
      {:ok, body} -> json(conn, body)
      {:error, reason} -> conn |> put_status(:bad_gateway) |> json(%{error: inspect(reason)})
    end
  end
end
