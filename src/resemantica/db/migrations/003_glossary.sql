CREATE TABLE IF NOT EXISTS glossary_candidates (
    candidate_id TEXT PRIMARY KEY,
    release_id TEXT NOT NULL,
    source_term TEXT NOT NULL,
    normalized_source_term TEXT NOT NULL,
    category TEXT NOT NULL,
    source_language TEXT NOT NULL,
    first_seen_chapter INTEGER NOT NULL,
    last_seen_chapter INTEGER NOT NULL,
    appearance_count INTEGER NOT NULL,
    evidence_snippet TEXT NOT NULL,
    candidate_translation_en TEXT,
    normalized_target_term TEXT,
    discovery_run_id TEXT NOT NULL,
    translation_run_id TEXT,
    candidate_status TEXT NOT NULL,
    validation_status TEXT NOT NULL,
    conflict_reason TEXT,
    translator_model_name TEXT,
    translator_prompt_version TEXT,
    schema_version INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (release_id, normalized_source_term, category)
);

CREATE TABLE IF NOT EXISTS locked_glossary (
    glossary_entry_id TEXT PRIMARY KEY,
    release_id TEXT NOT NULL,
    source_term TEXT NOT NULL,
    normalized_source_term TEXT NOT NULL,
    target_term TEXT NOT NULL,
    normalized_target_term TEXT NOT NULL,
    category TEXT NOT NULL,
    status TEXT NOT NULL,
    approved_at TEXT NOT NULL,
    approval_run_id TEXT NOT NULL,
    source_candidate_id TEXT NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1,
    UNIQUE (release_id, normalized_source_term, category),
    UNIQUE (release_id, normalized_target_term, category)
);

CREATE TABLE IF NOT EXISTS glossary_conflicts (
    conflict_id TEXT PRIMARY KEY,
    release_id TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    conflict_type TEXT NOT NULL,
    conflict_reason TEXT NOT NULL,
    existing_glossary_id TEXT,
    schema_version INTEGER NOT NULL DEFAULT 1,
    detected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

