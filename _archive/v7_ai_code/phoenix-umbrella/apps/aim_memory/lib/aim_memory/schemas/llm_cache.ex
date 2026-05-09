defmodule AimMemory.LlmCache do
  use Ecto.Schema
  import Ecto.Changeset

  @primary_key {:hash, :string, autogenerate: false}
  schema "llm_cache" do
    field :prompt_hash, :string
    field :response,    :string
    field :model,       :string
    field :created_at,  :string
  end

  def changeset(c, attrs) do
    c
    |> cast(attrs, [:hash, :prompt_hash, :response, :model, :created_at])
    |> validate_required([:hash, :prompt_hash, :response, :model, :created_at])
  end
end
