CREATE TABLE IF NOT EXISTS deferred_entities (
    deferred_id TEXT PRIMARY KEY,
    release_id TEXT NOT NULL,
    term_text TEXT NOT NULL,
    normalized_term_text TEXT NOT NULL,
    category TEXT NOT NULL,
    evidence_snippet TEXT NOT NULL,
    source_chapter INTEGER NOT NULL,
    last_seen_chapter INTEGER NOT NULL,
    appearance_count INTEGER NOT NULL,
    discovered_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    status TEXT NOT NULL,
    glossary_entry_id TEXT,
    schema_version INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (release_id, normalized_term_text, category)
);

CREATE TABLE IF NOT EXISTS graph_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    release_id TEXT NOT NULL,
    snapshot_hash TEXT NOT NULL,
    graph_db_path TEXT NOT NULL,
    entity_count INTEGER NOT NULL,
    alias_count INTEGER NOT NULL,
    appearance_count INTEGER NOT NULL,
    relationship_count INTEGER NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (release_id, snapshot_hash)
);

