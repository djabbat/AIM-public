defmodule AimMemory.Session do
  use Ecto.Schema
  import Ecto.Changeset

  @primary_key {:id, :id, autogenerate: true}
  schema "sessions" do
    field :started_at, :string
    field :ended_at,   :string
    field :lang,       :string, default: "ru"
    field :summary,    :string, default: ""

    belongs_to :patient, AimMemory.Patient
    has_many :messages, AimMemory.Message, foreign_key: :session_id
  end

  def changeset(s, attrs) do
    s
    |> cast(attrs, [:patient_id, :started_at, :ended_at, :lang, :summary])
    |> validate_required([:started_at])
  end
end
