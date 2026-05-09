defmodule AimWeb.Plugs.Locale do
  @moduledoc """
  Resolves locale from (in order): query param `?locale=`, session, Accept-Language,
  default. Stores in session and assigns `:locale` on the conn.
  """
  import Plug.Conn

  def init(opts), do: opts

  def call(conn, _opts) do
    locale =
      pick(conn.params["locale"]) ||
        pick(get_session(conn, :locale)) ||
        pick(accept_lang(conn)) ||
        AimWeb.I18n.default()

    conn
    |> put_session(:locale, Atom.to_string(locale))
    |> assign(:locale, locale)
  end

  defp pick(nil), do: nil
  defp pick(""), do: nil
  defp pick(val) do
    parsed = AimWeb.I18n.parse(val)
    if parsed in AimWeb.I18n.locales(), do: parsed
  end

  defp accept_lang(conn) do
    case get_req_header(conn, "accept-language") do
      [v | _] -> v |> String.split(",") |> hd() |> String.trim()
      _ -> nil
    end
  end
end
