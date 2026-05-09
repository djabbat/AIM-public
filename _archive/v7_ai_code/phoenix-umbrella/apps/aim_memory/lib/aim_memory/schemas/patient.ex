defmodule AimMemory.Patient do
  use Ecto.Schema
  import Ecto.Changeset

  @primary_key {:id, :id, autogenerate: true}
  schema "patients" do
    field :folder,     :string
    field :name,       :string
    field :created_at, :string
    field :lang,       :string, default: "ru"
    field :notes,      :string, default: ""

    has_many :sessions, AimMemory.Session, foreign_key: :patient_id
  end

  def changeset(p, attrs) do
    p
    |> cast(attrs, [:folder, :name, :created_at, :lang, :notes])
    |> validate_required([:folder, :name, :created_at])
    |> unique_constraint(:folder)
  end
end
