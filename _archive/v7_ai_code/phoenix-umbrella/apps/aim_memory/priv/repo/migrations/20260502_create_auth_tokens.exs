defmodule AimMemory.Repo.Migrations.CreateAuthTokens do
  use Ecto.Migration

  def change do
    create table(:auth_tokens, primary_key: false) do
      add :token_hash,  :string, primary_key: true
      add :username,    :string, null: false
      add :role,        :string, null: false, default: "user"
      add :created_at,  :string, null: false
      add :expires_at,  :string
      add :last_used_at, :string
      add :note,        :string, default: ""
    end

    create index(:auth_tokens, [:username])
  end
end
