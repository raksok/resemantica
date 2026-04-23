CREATE TABLE IF NOT EXISTS translation_checkpoints (
    release_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    chapter_number INTEGER NOT NULL,
    pass_name TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    status TEXT NOT NULL,
    artifact_path TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (release_id, run_id, chapter_number, pass_name)
);

