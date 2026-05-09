defmodule DiffdxWebWeb.CaseLive.Show do
  use DiffdxWebWeb, :live_view

  @impl true
  def mount(_params, _session, socket) do
    {:ok, socket}
  end

  @impl true
  def render(assigns) do
    ~H"""
    <div class="mx-auto max-w-3xl p-6">
      <h1 class="text-2xl font-bold">Случай</h1>
      <p>Stub: индивидуальный просмотр случая будет реализован, когда добавим Case persistence.</p>
      <.link navigate={~p"/"} class="text-blue-600 underline">← новый случай</.link>
    </div>
    """
  end
end
