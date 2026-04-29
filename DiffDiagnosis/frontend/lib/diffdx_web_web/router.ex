defmodule DiffdxWebWeb.Router do
  use DiffdxWebWeb, :router

  pipeline :browser do
    plug :accepts, ["html"]
    plug :fetch_session
    plug :fetch_live_flash
    plug :put_root_layout, html: {DiffdxWebWeb.Layouts, :root}
    plug :protect_from_forgery
    plug :put_secure_browser_headers
  end

  pipeline :api do
    plug :accepts, ["json"]
  end

  scope "/", DiffdxWebWeb do
    pipe_through :browser

    live "/", CaseLive.New, :new
    live "/case", CaseLive.Show, :show
    live "/algorithms", AlgorithmsLive, :index
    live "/sources", SourcesLive, :index
  end
end
