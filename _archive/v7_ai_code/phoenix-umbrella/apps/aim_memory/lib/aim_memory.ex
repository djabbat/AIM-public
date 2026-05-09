defmodule AimMemory do
  @moduledoc """
  Memory context — replaces db.py + agents/memory_*.py.

  Schemas mirror live aim.db tables:
    - patients, sessions, messages, patient_index, llm_cache
    - ai_events / ai_events_archive / ze_events not yet wrapped (rare write paths)
  """

  alias AimMemory.{Repo, Patient, Session, Message, PatientIndex, LlmCache, AuthToken, TelegramLink}
  import Ecto.Query

  # ── Patients ────────────────────────────────────────────────────────────────
  def list_patients, do: Repo.all(Patient)
  def get_patient(id), do: Repo.get(Patient, id)
  def get_patient_by_folder(folder), do: Repo.get_by(Patient, folder: folder)

  def upsert_patient(attrs) do
    %Patient{}
    |> Patient.changeset(attrs)
    |> Repo.insert(on_conflict: {:replace_all_except, [:id]}, conflict_target: :folder)
  end

  # ── Sessions / messages ─────────────────────────────────────────────────────
  def start_session(patient_id, lang \\ "ru") do
    %Session{}
    |> Session.changeset(%{
      patient_id: patient_id,
      started_at: now_iso(),
      lang: lang
    })
    |> Repo.insert()
  end

  def end_session(session_id, summary) do
    Repo.get!(Session, session_id)
    |> Session.changeset(%{ended_at: now_iso(), summary: summary})
    |> Repo.update()
  end

  def append_message(session_id, role, content, opts \\ []) do
    %Message{}
    |> Message.changeset(%{
      session_id: session_id,
      role: role,
      content: content,
      model: Keyword.get(opts, :model, ""),
      provider: Keyword.get(opts, :provider, ""),
      ts: now_iso()
    })
    |> Repo.insert()
  end

  def session_messages(session_id) do
    Repo.all(from m in Message, where: m.session_id == ^session_id, order_by: [asc: m.id])
  end

  # ── LLM cache ───────────────────────────────────────────────────────────────
  def cache_get(hash), do: Repo.get(LlmCache, hash)

  def cache_put(hash, prompt_hash, response, model) do
    %LlmCache{}
    |> LlmCache.changeset(%{
      hash: hash,
      prompt_hash: prompt_hash,
      response: response,
      model: model,
      created_at: now_iso()
    })
    |> Repo.insert(on_conflict: :nothing, conflict_target: :hash)
  end

  # ── Patient index ───────────────────────────────────────────────────────────
  def upsert_patient_index(attrs) do
    %PatientIndex{}
    |> PatientIndex.changeset(Map.put(attrs, :last_updated, now_iso()))
    |> Repo.insert(on_conflict: {:replace_all_except, [:patient_id]}, conflict_target: :patient_id)
  end

  # ── Auth tokens ─────────────────────────────────────────────────────────────
  @doc "Look up token (already hashed) and bump last_used_at."
  def lookup_token(hash) do
    case Repo.get(AuthToken, hash) do
      nil -> nil
      %AuthToken{expires_at: exp} = t ->
        if expired?(exp), do: nil, else: touch(t)
    end
  end

  def issue_token(username, role \\ "user", opts \\ []) do
    raw = :crypto.strong_rand_bytes(32) |> Base.url_encode64(padding: false)
    hash = hash_token(raw)
    attrs = %{
      token_hash: hash,
      username: username,
      role: role,
      created_at: now_iso(),
      expires_at: Keyword.get(opts, :expires_at),
      note: Keyword.get(opts, :note, "")
    }
    case %AuthToken{} |> AuthToken.changeset(attrs) |> Repo.insert() do
      {:ok, _} -> {:ok, raw}
      err -> err
    end
  end

  def hash_token(raw) when is_binary(raw) do
    :crypto.hash(:sha256, raw) |> Base.encode16(case: :lower)
  end

  defp touch(%AuthToken{} = t) do
    t
    |> AuthToken.changeset(%{last_used_at: now_iso()})
    |> Repo.update()
    |> case do
      {:ok, t} -> t
      _        -> t
    end
  end

  defp expired?(nil), do: false
  defp expired?(""),  do: false
  defp expired?(iso) do
    case DateTime.from_iso8601(iso) do
      {:ok, dt, _} -> DateTime.compare(dt, DateTime.utc_now()) == :lt
      # Malformed expiry → fail-safe: treat as expired so a corrupt row
      # cannot be a free pass forever.
      _ -> true
    end
  end

  # ── Telegram /link codes ────────────────────────────────────────────────────
  @link_ttl_minutes 30

  def issue_link_code(username) do
    code = Integer.to_string(:rand.uniform(900_000) + 99_999)
    expires =
      DateTime.utc_now()
      |> DateTime.add(@link_ttl_minutes * 60, :second)
      |> DateTime.to_iso8601()

    %TelegramLink{}
    |> TelegramLink.changeset(%{
      code: code, username: username,
      issued_at: now_iso(), expires_at: expires
    })
    |> Repo.insert()
    |> case do
      {:ok, _} -> {:ok, code}
      err -> err
    end
  end

  def redeem_link_code(code, chat_id) do
    case Repo.get(TelegramLink, code) do
      nil -> {:error, :unknown_code}
      %TelegramLink{consumed_at: c} when not is_nil(c) -> {:error, :already_consumed}
      %TelegramLink{expires_at: exp} = link ->
        if expired?(exp) do
          {:error, :expired}
        else
          link
          |> TelegramLink.changeset(%{
            consumed_at: now_iso(),
            chat_id: chat_id
          })
          |> Repo.update()
        end
    end
  end

  def chat_to_user(chat_id) do
    Repo.one(from t in TelegramLink, where: t.chat_id == ^chat_id and not is_nil(t.consumed_at))
  end

  defp now_iso, do: DateTime.utc_now() |> DateTime.to_iso8601()
end
