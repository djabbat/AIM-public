defmodule AimMemory.PatientIndex do
  use Ecto.Schema
  import Ecto.Changeset

  @primary_key {:patient_id, :string, autogenerate: false}
  schema "patient_index" do
    field :age,             :integer
    field :sex,             :string
    field :allergies_json,  :string
    field :conditions_json, :string
    field :last_updated,    :string
  end

  def changeset(p, attrs) do
    p
    |> cast(attrs, [:patient_id, :age, :sex, :allergies_json, :conditions_json, :last_updated])
    |> validate_required([:patient_id])
  end
end
