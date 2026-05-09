defmodule AimMemory.Message do
  use Ecto.Schema
  import Ecto.Changeset

  @primary_key {:id, :id, autogenerate: true}
  schema "messages" do
    field :role,     :string
    field :content,  :string
    field :model,    :string, default: ""
    field :provider, :string, default: ""
    field :ts,       :string

    belongs_to :session, AimMemory.Session
  end

  def changeset(m, attrs) do
    m
    |> cast(attrs, [:session_id, :role, :content, :model, :provider, :ts])
    |> validate_required([:role, :content, :ts])
    |> validate_inclusion(:role, ~w(user assistant system tool))
  end
end
