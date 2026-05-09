CREATE TABLE IF NOT EXISTS patients (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    folder      TEXT UNIQUE NOT NULL,
    name        TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    lang        TEXT DEFAULT 'ru',
    notes       TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS sessions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id  INTEGER REFERENCES patients(id),
    started_at  TEXT NOT NULL,
    ended_at    TEXT,
    lang        TEXT DEFAULT 'ru',
    summary     TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  INTEGER REFERENCES sessions(id),
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    model       TEXT DEFAULT '',
    provider    TEXT DEFAULT '',
    ts          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS llm_cache (
    hash        TEXT PRIMARY KEY,
    prompt_hash TEXT NOT NULL,
    response    TEXT NOT NULL,
    model       TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ai_events_archive (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    original_id     INTEGER,
    archived_at     TEXT NOT NULL,
    ts              TEXT,
    patient_id      TEXT,
    session_id      TEXT,
    agent           TEXT,
    decision_type   TEXT,
    alternatives_json TEXT,
    chosen_id       TEXT,
    laws_json       TEXT,
    scoring_json    TEXT,
    override_type   TEXT,
    override_reason TEXT
);

CREATE TABLE IF NOT EXISTS ze_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              TEXT NOT NULL,
    decision_id     TEXT NOT NULL,
    action_type     TEXT NOT NULL,
    blocked_at      TEXT,
    impedance_before REAL,
    impedance_after  REAL,
    instant_c       REAL,
    phi_ze          REAL,
    utility         REAL,
    payload_chars   INTEGER,
    output_chars    INTEGER
);

CREATE INDEX IF NOT EXISTS idx_patients_folder ON patients(folder);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
CREATE INDEX IF NOT EXISTS idx_cache_hash ON llm_cache(hash);
CREATE INDEX IF NOT EXISTS idx_archive_patient ON ai_events_archive(patient_id);
CREATE INDEX IF NOT EXISTS idx_archive_ts ON ai_events_archive(ts);
CREATE INDEX IF NOT EXISTS idx_ze_ts          ON ze_events(ts);
CREATE INDEX IF NOT EXISTS idx_ze_action      ON ze_events(action_type);
CREATE INDEX IF NOT EXISTS idx_ze_blocked     ON ze_events(blocked_at);
