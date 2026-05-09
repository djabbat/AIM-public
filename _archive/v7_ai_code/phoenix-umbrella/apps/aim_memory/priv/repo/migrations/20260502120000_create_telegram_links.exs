defmodule AimMemory.Repo.Migrations.CreateTelegramLinks do
  use Ecto.Migration

  def change do
    create table(:telegram_links, primary_key: false) do
      add :code,        :string, primary_key: true   # 6-digit code
      add :username,    :string, null: false
      add :issued_at,   :string, null: false
      add :expires_at,  :string, null: false
      add :consumed_at, :string                       # null until /link redeemed
      add :chat_id,     :integer                      # set after redeem
    end

    create unique_index(:telegram_links, [:chat_id], where: "chat_id IS NOT NULL", name: :telegram_links_chat_unique)
  end
end
