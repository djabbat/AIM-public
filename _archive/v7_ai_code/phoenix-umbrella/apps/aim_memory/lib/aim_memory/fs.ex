defmodule AimMemory.FS do
  @moduledoc """
  AIM_FS — three-tier filesystem context.

  Uses an Elixir Port to talk to the Rust binary `aim-fs` (one JSON command per
  line on stdin, one reply per line on stdout). Per SPEC.md §10.2.

  The Port lifecycle is owned by `AimMemory.FS.Port` GenServer (started by the
  application supervisor) — this module is a thin façade.
  """
  alias AimMemory.FS.Port, as: P

  @type tenant_id :: String.t()

  @spec propose(tenant_id, map(), keyword()) :: {:ok, map()} | {:error, term()}
  def propose(tenant_id, new_entity, opts \\ []) do
    rationale = Keyword.get(opts, :rationale)
    idempotency_key = Keyword.get(opts, :idempotency_key) || Ecto.UUID.generate()
    policy = Keyword.get(opts, :policy, default_policy())

    result =
      P.call(%{
        op: "propose",
        tenant_id: tenant_id,
        new: new_entity,
        rationale: rationale,
        idempotency_key: idempotency_key,
        policy: policy
      })

    case result do
      {:ok, outcome} = ok ->
        # Push to InboxLive only when the entity is actually pending —
        # auto-approved entries don't need the badge bump.
        if Map.get(outcome, "auto_approved") == false or
             Map.get(outcome, "entity_status") in ["pending", "disputed"] do
          Phoenix.PubSub.broadcast(
            AIM.PubSub,
            "inbox:#{tenant_id}",
            {:proposed, outcome}
          )
        end
        ok
      err -> err
    end
  end

  @spec approve(tenant_id, String.t(), map()) :: {:ok, map()} | {:error, term()}
  def approve(tenant_id, proposal_id, actor) do
    result =
      P.call(%{
        op: "approve",
        tenant_id: tenant_id,
        proposal_id: proposal_id,
        actor: actor
      })

    case result do
      {:ok, _} = ok ->
        Phoenix.PubSub.broadcast(AIM.PubSub, "inbox:#{tenant_id}", {:approved, proposal_id})
        ok
      err -> err
    end
  end

  @spec reject(tenant_id, String.t(), map(), String.t() | nil) ::
          {:ok, map()} | {:error, term()}
  def reject(tenant_id, proposal_id, actor, reason \\ nil) do
    result =
      P.call(%{
        op: "reject",
        tenant_id: tenant_id,
        proposal_id: proposal_id,
        actor: actor,
        reason: reason
      })

    case result do
      {:ok, _} = ok ->
        Phoenix.PubSub.broadcast(AIM.PubSub, "inbox:#{tenant_id}", {:rejected, proposal_id})
        ok
      err -> err
    end
  end

  @spec list_pending(tenant_id, integer()) :: {:ok, list()} | {:error, term()}
  def list_pending(tenant_id, limit \\ 50) do
    P.call(%{op: "list_pending", tenant_id: tenant_id, limit: limit})
  end

  @spec scaffold_project(String.t(), String.t(), String.t()) ::
          {:ok, map()} | {:error, term()}
  def scaffold_project(user_id, slug, concept) do
    P.call(%{op: "scaffold_project", user_id: user_id, slug: slug, concept: concept})
  end

  @spec ensure_patient(String.t(), String.t()) :: {:ok, map()} | {:error, term()}
  def ensure_patient(doctor_id, patient_key) do
    P.call(%{op: "ensure_patient", doctor_id: doctor_id, patient_key: patient_key})
  end

  @spec sweep() :: {:ok, map()} | {:error, term()}
  def sweep, do: P.call(%{op: "sweep"})

  @spec search(tenant_id, String.t(), map(), integer()) ::
          {:ok, list()} | {:error, term()}
  def search(tenant_id, query, scope \\ %{}, limit \\ 20),
    do: P.call(%{op: "search", tenant_id: tenant_id, query: query, scope: scope, limit: limit})

  @spec list_projects(String.t()) :: {:ok, list()} | {:error, term()}
  def list_projects(user_id), do: P.call(%{op: "list_projects", user_id: user_id})

  @spec list_patients(String.t()) :: {:ok, list()} | {:error, term()}
  def list_patients(doctor_id),
    do: P.call(%{op: "list_patients", doctor_id: doctor_id})

  @spec add_link(tenant_id, String.t(), String.t(), String.t()) ::
          {:ok, map()} | {:error, term()}
  def add_link(tenant_id, source_id, target_id, link_type),
    do:
      P.call(%{
        op: "add_link",
        tenant_id: tenant_id,
        source_id: source_id,
        target_id: target_id,
        link_type: link_type
      })

  @spec list_outgoing_links(tenant_id, String.t()) :: {:ok, list()} | {:error, term()}
  def list_outgoing_links(tenant_id, source_id),
    do: P.call(%{op: "list_outgoing", tenant_id: tenant_id, source_id: source_id})

  @spec list_disputes(tenant_id) :: {:ok, list()} | {:error, term()}
  def list_disputes(tenant_id),
    do: P.call(%{op: "list_disputes", tenant_id: tenant_id})

  @spec resolve_dispute(tenant_id, String.t(), String.t(), map()) ::
          {:ok, map()} | {:error, term()}
  def resolve_dispute(tenant_id, winner_id, loser_id, actor) do
    result =
      P.call(%{
        op: "resolve_dispute",
        tenant_id: tenant_id,
        winner_id: winner_id,
        loser_id: loser_id,
        actor: actor
      })

    case result do
      {:ok, _} = ok ->
        Phoenix.PubSub.broadcast(
          AIM.PubSub,
          "inbox:#{tenant_id}",
          {:dispute_resolved, winner_id, loser_id}
        )
        ok
      err -> err
    end
  end

  @spec profile_view(tenant_id) :: {:ok, map()} | {:error, term()}
  def profile_view(tenant_id),
    do: P.call(%{op: "profile_view", tenant_id: tenant_id})

  @spec project_activity(tenant_id, String.t()) :: {:ok, map()} | {:error, term()}
  def project_activity(tenant_id, slug),
    do: P.call(%{op: "project_activity", tenant_id: tenant_id, slug: slug})

  @spec entity_detail(tenant_id, String.t()) :: {:ok, map()} | {:error, term()}
  def entity_detail(tenant_id, id),
    do: P.call(%{op: "entity_detail", tenant_id: tenant_id, id: id})

  @spec stats(tenant_id) :: {:ok, map()} | {:error, term()}
  def stats(tenant_id), do: P.call(%{op: "stats", tenant_id: tenant_id})

  @spec list_events(tenant_id, integer()) :: {:ok, list()} | {:error, term()}
  def list_events(tenant_id, limit \\ 50),
    do: P.call(%{op: "list_events", tenant_id: tenant_id, limit: limit})

  defp default_policy do
    %{
      auto_approve_user_commands: true,
      auto_approve_observational_with_confidence_above: 0.95,
      auto_approve_service_events: true,
      require_approval_for: ~w(feedback proposal recipe diagnosis),
      max_inactivity_days: 30
    }
  end
end
