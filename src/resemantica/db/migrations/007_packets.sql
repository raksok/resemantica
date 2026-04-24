CREATE TABLE IF NOT EXISTS packet_metadata (
    packet_id TEXT PRIMARY KEY,
    release_id TEXT NOT NULL,
    chapter_number INTEGER NOT NULL,
    run_id TEXT NOT NULL,
    packet_path TEXT NOT NULL,
    bundle_path TEXT NOT NULL,
    packet_hash TEXT NOT NULL,
    chapter_source_hash TEXT NOT NULL,
    glossary_version_hash TEXT NOT NULL,
    summary_version_hash TEXT NOT NULL,
    graph_snapshot_hash TEXT NOT NULL,
    idiom_policy_hash TEXT NOT NULL,
    packet_builder_version TEXT NOT NULL,
    packet_schema_version INTEGER NOT NULL DEFAULT 1,
    built_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (release_id, chapter_number, packet_hash)
);

CREATE INDEX IF NOT EXISTS idx_packet_metadata_release_chapter_built
ON packet_metadata (release_id, chapter_number, built_at DESC, packet_id DESC);

