CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    release_id TEXT NOT NULL,
    workflow_name TEXT NOT NULL,
    workflow_status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS checkpoints (
    checkpoint_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    chapter_number INTEGER,
    block_id TEXT,
    pass_number INTEGER,
    stage_name TEXT NOT NULL,
    checkpoint_status TEXT NOT NULL,
    latest_artifact_ref TEXT,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES runs(run_id)
);

