defmodule AimWebWeb.PatientsBrowserLive do
  @moduledoc """
  AIM_FS-backed patients browser. Lists folders under
  `<aim_root>/users/<doctor>/patients/` with identity.toml metadata or
  fallback parsing from `<Surname>_<Name>_<YYYY_MM_DD>` folder names.

  Per AIM CLAUDE.md "Patients/" rule — NEVER reads patient body files
  directly; only the identity card and last-visit headline.
  """
  use AimWebWeb, :live_view
  alias AimMemory.FS

  @impl true
  def mount(_params, session, socket) do
    doctor_id = session["user_id"] || "djabbat"
    {:ok, socket |> assign(:doctor_id, doctor_id) |> assign(:q, "") |> reload()}
  end

  @impl true
  def handle_event("filter", %{"q" => q}, socket) do
    {:noreply, socket |> assign(:q, q) |> reload()}
  end

  defp reload(socket) do
    case FS.list_patients(socket.assigns.doctor_id) do
      {:ok, items} ->
        f = String.downcase(socket.assigns.q || "")
        filtered =
          if f == "" do
            items
          else
            Enum.filter(items, fn p ->
              [p["surname"], p["name"], p["dob"], p["key"]]
              |> Enum.any?(fn v -> v && String.contains?(String.downcase(to_string(v)), f) end)
            end)
          end

        assign(socket, :patients, filtered)

      _ ->
        assign(socket, :patients, [])
    end
  end

  @impl true
  def render(assigns) do
    ~H"""
    <div class="patients-browser">
      <h1>Patients · <%= length(@patients) %></h1>

      <form phx-change="filter">
        <input type="text" name="q" value={@q} placeholder="filter by name / DOB" />
      </form>

      <table class="patients">
        <thead>
          <tr>
            <th>Patient</th>
            <th>DOB</th>
            <th>Phone</th>
            <th>Last complaint</th>
          </tr>
        </thead>
        <tbody>
          <%= for p <- @patients do %>
            <tr>
              <td>
                <strong><%= p["surname"] %> <%= p["name"] %></strong>
                <br />
                <small><code><%= p["key"] %></code></small>
              </td>
              <td><%= p["dob"] || "—" %></td>
              <td><%= p["phone"] || "—" %></td>
              <td><%= String.slice(p["last_visit_complaint"] || "", 0, 100) %></td>
            </tr>
          <% end %>
        </tbody>
      </table>

      <p><a href="/onboard">+ Register new patient (guided)</a></p>
    </div>

    <style>
      .patients-browser { max-width: 980px; margin: 1.5rem auto; font-family: system-ui; }
      .patients-browser h1 { font-size: 1.4rem; }
      .patients-browser form input { width: 100%; padding: .25rem .5rem; }
      .patients-browser table.patients { width: 100%; border-collapse: collapse; }
      .patients-browser table.patients th, .patients-browser table.patients td {
        text-align: left; padding: .35rem .5rem; border-bottom: 1px solid #eee;
      }
      .patients-browser code { font-size: .85em; color: #666; }
    </style>
    """
  end
end
