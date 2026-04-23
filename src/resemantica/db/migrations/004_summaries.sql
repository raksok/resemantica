CREATE TABLE IF NOT EXISTS summary_drafts (
    draft_id TEXT PRIMARY KEY,
    release_id TEXT NOT NULL,
    chapter_number INTEGER NOT NULL,
    summary_type TEXT NOT NULL,
    content_json TEXT NOT NULL,
    chapter_source_hash TEXT NOT NULL,
    model_name TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    run_id TEXT NOT NULL,
    validation_status TEXT NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (release_id, chapter_number, summary_type)
);

CREATE TABLE IF NOT EXISTS validated_summaries_zh (
    summary_id TEXT PRIMARY KEY,
    release_id TEXT NOT NULL,
    chapter_number INTEGER NOT NULL,
    summary_type TEXT NOT NULL,
    content_zh TEXT NOT NULL,
    derived_from_chapter_hash TEXT NOT NULL,
    validation_status TEXT NOT NULL,
    run_id TEXT NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (release_id, chapter_number, summary_type)
);

CREATE TABLE IF NOT EXISTS derived_summaries_en (
    summary_id TEXT PRIMARY KEY,
    release_id TEXT NOT NULL,
    chapter_number INTEGER NOT NULL,
    summary_type TEXT NOT NULL,
    content_en TEXT NOT NULL,
    source_summary_id TEXT NOT NULL,
    source_summary_hash TEXT NOT NULL,
    glossary_version_hash TEXT NOT NULL,
    model_name TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    run_id TEXT NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (release_id, chapter_number, summary_type)
);
