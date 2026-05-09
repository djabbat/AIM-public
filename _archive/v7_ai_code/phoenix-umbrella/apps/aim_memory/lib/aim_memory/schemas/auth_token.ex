defmodule AimMemory.AuthToken do
  use Ecto.Schema
  import Ecto.Changeset

  @primary_key {:token_hash, :string, autogenerate: false}
  schema "auth_tokens" do
    field :username,     :string
    field :role,         :string, default: "user"
    field :created_at,   :string
    field :expires_at,   :string
    field :last_used_at, :string
    field :note,         :string, default: ""
  end

  def changeset(t, attrs) do
    t
    |> cast(attrs, [:token_hash, :username, :role, :created_at, :expires_at, :last_used_at, :note])
    |> validate_required([:token_hash, :username, :created_at])
    |> validate_inclusion(:role, ~w(admin user readonly))
    |> validate_iso8601(:expires_at)
    |> validate_iso8601(:last_used_at)
  end

  defp validate_iso8601(changeset, field) do
    validate_change(changeset, field, fn ^field, value ->
      cond do
        value in [nil, ""] -> []
        match?({:ok, _, _}, DateTime.from_iso8601(value)) -> []
        true -> [{field, "must be ISO8601 datetime (e.g. 2026-12-31T00:00:00Z)"}]
      end
    end)
  end
end
