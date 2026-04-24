CREATE TABLE IF NOT EXISTS idiom_candidates (
    candidate_id TEXT PRIMARY KEY,
    release_id TEXT NOT NULL,
    source_text TEXT NOT NULL,
    normalized_source_text TEXT NOT NULL,
    meaning_zh TEXT NOT NULL,
    preferred_rendering_en TEXT NOT NULL,
    usage_notes TEXT,
    first_seen_chapter INTEGER NOT NULL,
    last_seen_chapter INTEGER NOT NULL,
    appearance_count INTEGER NOT NULL,
    evidence_snippet TEXT NOT NULL,
    detection_run_id TEXT NOT NULL,
    candidate_status TEXT NOT NULL,
    validation_status TEXT NOT NULL,
    conflict_reason TEXT,
    analyst_model_name TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS idiom_policies (
    idiom_id TEXT PRIMARY KEY,
    release_id TEXT NOT NULL,
    source_text TEXT NOT NULL,
    normalized_source_text TEXT NOT NULL,
    meaning_zh TEXT NOT NULL,
    preferred_rendering_en TEXT NOT NULL,
    usage_notes TEXT,
    policy_status TEXT NOT NULL,
    first_seen_chapter INTEGER NOT NULL,
    last_seen_chapter INTEGER NOT NULL,
    appearance_count INTEGER NOT NULL,
    promoted_from_candidate_id TEXT NOT NULL,
    approval_run_id TEXT NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (release_id, normalized_source_text)
);

CREATE TABLE IF NOT EXISTS idiom_conflicts (
    conflict_id TEXT PRIMARY KEY,
    release_id TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    conflict_type TEXT NOT NULL,
    conflict_reason TEXT NOT NULL,
    existing_idiom_id TEXT,
    schema_version INTEGER NOT NULL DEFAULT 1,
    detected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

