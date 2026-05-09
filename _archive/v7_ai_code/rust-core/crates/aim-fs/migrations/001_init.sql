-- AIM_FS schema, derived from SPEC.md §5.1 (v11 ACCEPT).
-- Apply once per fresh aim_fs.db. Idempotent: CREATE IF NOT EXISTS.

PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA journal_size_limit = 65536;
PRAGMA cache_size = -8000;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS entities (
    id                    TEXT PRIMARY KEY,
    tenant_id             TEXT NOT NULL,
    schema                TEXT NOT NULL,
    schema_version        INTEGER NOT NULL DEFAULT 1,
    title                 TEXT,
    description           TEXT,
    body                  TEXT,
    status                TEXT NOT NULL DEFAULT 'pending',
    confidence            REAL,
    source                TEXT NOT NULL DEFAULT 'system',
    user_id               TEXT NOT NULL,
    session_id            TEXT,
    llm_model             TEXT,
    requires_verification INTEGER NOT NULL DEFAULT 0,
    scope_global          INTEGER NOT NULL DEFAULT 0,
    scope_user_ids        TEXT,
    scope_project_ids     TEXT,
    scope_patient_ids     TEXT,
    tags                  TEXT,
    decay_ttl_days        INTEGER,
    decay_expires_at      TEXT,
    decay_on_expire       TEXT DEFAULT 'keep',
    version               INTEGER NOT NULL DEFAULT 1,
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_entities_tenant_status ON entities(tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_entities_tenant_schema ON entities(tenant_id, schema);
CREATE INDEX IF NOT EXISTS idx_entities_expires ON entities(status, decay_expires_at)
    WHERE status = 'active' AND decay_expires_at IS NOT NULL;

CREATE TABLE IF NOT EXISTS versions (
    id          TEXT PRIMARY KEY,
    entity_id   TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    data        TEXT,
    hash        TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    tenant_id   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_versions_entity ON versions(entity_id, created_at);

CREATE TABLE IF NOT EXISTS proposals (
    id                   TEXT PRIMARY KEY,
    tenant_id            TEXT NOT NULL,
    entity_id            TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    proposal_type        TEXT NOT NULL DEFAULT 'create',
    status               TEXT NOT NULL DEFAULT 'pending',
    proposed_data        TEXT,
    rationale            TEXT,
    proposed_by_user_id  TEXT,
    approved_by_user_id  TEXT,
    blocked_reason       TEXT,
    version_at_proposal  INTEGER NOT NULL,
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_proposals_tenant_status ON proposals(tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_proposals_entity ON proposals(entity_id);

CREATE TABLE IF NOT EXISTS events (
    id          TEXT PRIMARY KEY,
    tenant_id   TEXT NOT NULL,
    entity_id   TEXT,
    event_type  TEXT NOT NULL,
    payload     TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_tenant ON events(tenant_id, created_at);

CREATE TABLE IF NOT EXISTS links (
    source_id   TEXT NOT NULL,
    target_id   TEXT NOT NULL,
    link_type   TEXT NOT NULL,
    tenant_id   TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (source_id, target_id, link_type)
);
CREATE INDEX IF NOT EXISTS idx_links_source ON links(source_id, link_type);
CREATE INDEX IF NOT EXISTS idx_links_target ON links(target_id, link_type);

CREATE TABLE IF NOT EXISTS idempotency (
    key         TEXT PRIMARY KEY,
    status      TEXT NOT NULL DEFAULT 'processing',
    result      TEXT,
    tenant_id   TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_idempotency_tenant ON idempotency(tenant_id);

-- ── FTS5 (Phase 2 search) ──────────────────────────────────────────────────
-- Content-less FTS5 virtual table mirroring (id, tenant_id, title, body,
-- description, tags) so we can run BM25 ranking. The triggers below keep it
-- in sync with `entities`. SQLite shipped via `rusqlite/bundled` includes
-- FTS5 by default.
CREATE VIRTUAL TABLE IF NOT EXISTS entities_fts USING fts5(
    id UNINDEXED,
    tenant_id UNINDEXED,
    title,
    body,
    description,
    tags,
    tokenize = "unicode61 remove_diacritics 2"
);

CREATE TRIGGER IF NOT EXISTS entities_ai AFTER INSERT ON entities BEGIN
  INSERT INTO entities_fts(id, tenant_id, title, body, description, tags)
  VALUES (new.id, new.tenant_id, new.title, new.body, new.description, new.tags);
END;
CREATE TRIGGER IF NOT EXISTS entities_au AFTER UPDATE ON entities BEGIN
  DELETE FROM entities_fts WHERE id = old.id;
  INSERT INTO entities_fts(id, tenant_id, title, body, description, tags)
  VALUES (new.id, new.tenant_id, new.title, new.body, new.description, new.tags);
END;
CREATE TRIGGER IF NOT EXISTS entities_ad AFTER DELETE ON entities BEGIN
  DELETE FROM entities_fts WHERE id = old.id;
END;
