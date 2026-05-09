defmodule AimWeb.Layouts do
  use Phoenix.Component
  import AimWeb.I18n, only: [t: 2]

  embed_templates "layouts/*"
end
