defmodule SsaWebWeb.Router do
  use SsaWebWeb, :router

  pipeline :browser do
    plug :accepts, ["html"]
    plug :fetch_session
    plug :fetch_live_flash
    plug :put_root_layout, html: {SsaWebWeb.Layouts, :root}
    plug :protect_from_forgery
    plug :put_secure_browser_headers
  end

  scope "/", SsaWebWeb do
    pipe_through :browser

    live "/", CbcLive, :index
  end
end
