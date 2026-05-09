defmodule AimWebWeb.ProfileLive do
  @moduledoc """
  Aggregated user profile view derived from AIM_FS user_fact / feedback /
  contact entities. Closes the "AIM studies the user" use case from the
  ONBOARDING.md spec — by reading the same store the agent writes to.
  """
  use AimWebWeb, :live_view
  alias AimMemory.FS

  @impl true
  def mount(_params, session, socket) do
    tenant_id = session["user_id"] || "djabbat"
    {:ok, socket |> assign(:tenant_id, tenant_id) |> reload()}
  end

  defp reload(socket) do
    case FS.profile_view(socket.assigns.tenant_id) do
      {:ok, p} -> assign(socket, :profile, p)
      _ -> assign(socket, :profile, nil)
    end
  end

  @impl true
  def render(assigns) do
    ~H"""
    <div class="profile">
      <h1>User profile · <code><%= @tenant_id %></code></h1>

      <%= if @profile do %>
        <section class="counts">
          <div><strong><%= @profile["counts"]["user_facts"] %></strong> user_facts</div>
          <div><strong><%= @profile["counts"]["feedback_rules"] %></strong> feedback_rules</div>
          <div><strong><%= @profile["counts"]["projects"] %></strong> projects</div>
          <div><strong><%= @profile["counts"]["patients"] %></strong> patients</div>
          <div><strong><%= @profile["counts"]["contacts"] %></strong> contacts</div>
        </section>

        <h2>Identity facts (top 30)</h2>
        <%= for e <- @profile["identity_facts"] do %>
          <div class="entry">
            <p class="title"><%= e["title"] || "(no title)" %></p>
            <p class="snippet"><%= e["snippet"] || "" %></p>
          </div>
        <% end %>

        <h2>Feedback rules (top 30)</h2>
        <%= for e <- @profile["feedback_rules"] do %>
          <div class="entry">
            <p class="title"><%= e["title"] || "(no title)" %></p>
            <%= if e["scope_project_ids"] do %>
              <p class="scope">scope: <%= Enum.join(e["scope_project_ids"], ", ") %></p>
            <% end %>
            <p class="snippet"><%= e["snippet"] || "" %></p>
          </div>
        <% end %>

        <h2>Contacts</h2>
        <%= for e <- @profile["contacts"] do %>
          <div class="entry contact">
            <p class="title"><%= e["title"] || "(no title)" %></p>
            <p class="snippet"><%= e["snippet"] || "" %></p>
          </div>
        <% end %>

        <h2>Recent decisions (top 20)</h2>
        <%= for e <- @profile["recent_decisions"] do %>
          <div class="entry">
            <p class="title"><%= e["title"] || "(no title)" %> <small>(<%= e["schema"] %>)</small></p>
            <p class="snippet"><%= e["snippet"] || "" %></p>
          </div>
        <% end %>
      <% else %>
        <p>(profile data unavailable)</p>
      <% end %>
    </div>

    <style>
      .profile { max-width: 880px; margin: 1.5rem auto; font-family: system-ui; }
      .profile h1 { font-size: 1.4rem; }
      .profile h2 { font-size: 1.1rem; margin-top: 2rem; border-bottom: 1px solid #ccc; }
      .profile section.counts { display: flex; gap: 1.5rem; margin: 1rem 0; }
      .profile section.counts > div { background: #f0f0f8; padding: .5rem 1rem; border-radius: 6px; }
      .profile .entry { padding: .35rem .5rem; border-bottom: 1px dashed #eee; }
      .profile .title { font-weight: 600; margin: .15rem 0; }
      .profile .scope { font-size: .8em; color: #888; }
      .profile .snippet { font-size: .85em; color: #555; margin: .15rem 0; }
      .profile .contact { background: #f8f8ee; }
    </style>
    """
  end
end
