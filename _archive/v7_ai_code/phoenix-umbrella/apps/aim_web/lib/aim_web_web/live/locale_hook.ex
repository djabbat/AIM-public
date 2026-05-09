defmodule AimWeb.LocaleHook do
  @moduledoc "Reads :locale from session into LiveView socket assigns."
  import Phoenix.Component, only: [assign: 3]

  def on_mount(:default, _params, session, socket) do
    locale = AimWeb.I18n.parse(session["locale"])
    socket = socket |> assign(:locale, locale) |> assign(:dir, if(AimWeb.I18n.rtl?(locale), do: "rtl", else: "ltr"))
    {:cont, socket}
  end
end
