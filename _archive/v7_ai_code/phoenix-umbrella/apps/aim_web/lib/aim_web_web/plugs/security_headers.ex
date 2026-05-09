defmodule AimWeb.Plugs.SecurityHeaders do
  @moduledoc """
  Adds CSP, HSTS (in prod), Referrer-Policy, X-Content-Type-Options,
  X-Frame-Options. CSP is permissive enough for LiveView WebSocket + inline
  styles but blocks third-party scripts.
  """
  import Plug.Conn

  # eco-inject.js is served from the parent domain longevity.ge and
  # provides the cross-subdomain nav + theme + lang switcher. It must
  # be allow-listed in script-src; its embedded styles in <style> use
  # 'unsafe-inline' which is already on. It also loads Google Fonts.
  @longevity_origin "https://longevity.ge"
  @gfonts "https://fonts.googleapis.com https://fonts.gstatic.com"

  @csp_dev "default-src 'self' #{@longevity_origin}; " <>
           "script-src 'self' 'unsafe-inline' 'unsafe-eval' #{@longevity_origin}; " <>
           "style-src 'self' 'unsafe-inline' #{@gfonts}; " <>
           "img-src 'self' data: blob: #{@longevity_origin}; " <>
           "font-src 'self' data: #{@gfonts}; " <>
           "connect-src 'self' ws: wss: #{@longevity_origin}; " <>
           "object-src 'none'; " <>
           "base-uri 'self'"

  @csp_prod "default-src 'self' #{@longevity_origin}; " <>
            "script-src 'self' #{@longevity_origin}; " <>
            "style-src 'self' 'unsafe-inline' #{@gfonts}; " <>
            "img-src 'self' data: #{@longevity_origin}; " <>
            "font-src 'self' #{@gfonts}; " <>
            "connect-src 'self' wss: #{@longevity_origin}; " <>
            "object-src 'none'; " <>
            "base-uri 'self'; " <>
            "frame-ancestors 'none'"

  def init(opts), do: opts

  def call(conn, _opts) do
    prod? = Application.get_env(:aim_web, :env, :dev) == :prod || System.get_env("AIM_ENV") == "prod"

    conn
    |> put_resp_header("content-security-policy", if(prod?, do: @csp_prod, else: @csp_dev))
    |> put_resp_header("x-content-type-options", "nosniff")
    |> put_resp_header("referrer-policy", "strict-origin-when-cross-origin")
    |> put_resp_header("x-frame-options", "DENY")
    |> maybe_hsts(prod?)
  end

  defp maybe_hsts(conn, true),
    do: put_resp_header(conn, "strict-transport-security", "max-age=63072000; includeSubDomains")
  defp maybe_hsts(conn, false), do: conn
end
