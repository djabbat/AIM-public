defmodule AimMemory.TelegramLink do
  use Ecto.Schema
  import Ecto.Changeset

  @primary_key {:code, :string, autogenerate: false}
  schema "telegram_links" do
    field :username,    :string
    field :issued_at,   :string
    field :expires_at,  :string
    field :consumed_at, :string
    field :chat_id,     :integer
  end

  def changeset(t, attrs) do
    t
    |> cast(attrs, [:code, :username, :issued_at, :expires_at, :consumed_at, :chat_id])
    |> validate_required([:code, :username, :issued_at, :expires_at])
    |> validate_format(:code, ~r/^\d{6}$/)
  end
end
