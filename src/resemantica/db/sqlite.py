from __future__ import annotations

import sqlite3
from pathlib import Path


def open_connection(db_path: str | Path) -> sqlite3.Connection:
    if isinstance(db_path, Path):
        resolved = db_path.resolve()
        resolved.parent.mkdir(parents=True, exist_ok=True)
        target = str(resolved)
    else:
        target = db_path

    conn = sqlite3.connect(target)
    conn.row_factory = sqlite3.Row

    if target != ":memory:":
        conn.execute("PRAGMA journal_mode=WAL;")

    return conn


def ensure_full_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
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

        CREATE TABLE IF NOT EXISTS translation_checkpoints (
            release_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            chapter_number INTEGER NOT NULL,
            pass_name TEXT NOT NULL,
            source_hash TEXT NOT NULL,
            prompt_version TEXT NOT NULL,
            packet_version_hash TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL,
            artifact_path TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (release_id, run_id, chapter_number, pass_name)
        );

        CREATE TABLE IF NOT EXISTS chunk_checkpoints (
            release_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            stage_name TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            chapter_start INTEGER NOT NULL,
            chapter_end INTEGER NOT NULL,
            status TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (release_id, run_id, stage_name, chunk_index)
        );

        CREATE INDEX IF NOT EXISTS idx_chunk_checkpoints_lookup
            ON chunk_checkpoints (release_id, run_id, stage_name, status, chunk_index);

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
            critic_score REAL,
            translator_model_name TEXT,
            translator_prompt_version TEXT,
            analyst_model_name TEXT,
            analyst_prompt_version TEXT,
            schema_version INTEGER NOT NULL DEFAULT 1,
            pos_tags TEXT,
            ner_label TEXT,
            type_prior TEXT,
            source_strategies TEXT,
            chapter_coverage INTEGER,
            corpus_score REAL,
            context_snippets TEXT,
            llm_keep INTEGER,
            llm_type TEXT,
            llm_reason_code TEXT,
            llm_confidence REAL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (release_id, normalized_source_term, category)
        );

        CREATE TABLE IF NOT EXISTS glossary_alias_clusters (
            cluster_id TEXT PRIMARY KEY,
            release_id TEXT NOT NULL,
            canonical_candidate_id TEXT NOT NULL,
            canonical_term TEXT NOT NULL,
            aliases_json TEXT NOT NULL,
            member_ids_json TEXT NOT NULL,
            similarity_score REAL NOT NULL,
            existing_glossary_match TEXT,
            discovery_run_id TEXT NOT NULL,
            schema_version INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (release_id, canonical_candidate_id)
        );

        CREATE TABLE IF NOT EXISTS glossary_translation_votes (
            vote_id TEXT PRIMARY KEY,
            candidate_id TEXT NOT NULL,
            release_id TEXT NOT NULL,
            translation_run_id TEXT NOT NULL,
            model_name TEXT NOT NULL,
            prompt_version TEXT NOT NULL,
            raw_output TEXT NOT NULL,
            cleaned_output TEXT NOT NULL,
            normalized_output TEXT NOT NULL,
            resolution_status TEXT NOT NULL,
            schema_version INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (candidate_id, translation_run_id, model_name)
        );

        CREATE INDEX IF NOT EXISTS idx_glossary_candidates_review_status
            ON glossary_candidates (
                release_id,
                candidate_status,
                candidate_id
            );

        CREATE INDEX IF NOT EXISTS idx_glossary_translation_votes_resume
            ON glossary_translation_votes (
                release_id,
                translation_run_id,
                model_name,
                candidate_id
            );

        CREATE INDEX IF NOT EXISTS idx_glossary_translation_votes_review
            ON glossary_translation_votes (
                release_id,
                candidate_id,
                model_name
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
            UNIQUE (release_id, normalized_source_term, category)
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

        CREATE TABLE IF NOT EXISTS glossary_checkpoints (
            release_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            stage_name TEXT NOT NULL,
            input_hash TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (release_id, run_id)
        );

        CREATE TABLE IF NOT EXISTS glossary_discovery_chapter_state (
            release_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            chapter_number INTEGER NOT NULL,
            chapter_source_hash TEXT NOT NULL,
            input_hash TEXT NOT NULL,
            status TEXT NOT NULL,
            skip_reason TEXT,
            raw_candidates_json TEXT NOT NULL,
            candidate_count INTEGER NOT NULL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (release_id, run_id, chapter_number)
        );

        CREATE TABLE IF NOT EXISTS summary_checkpoints (
            release_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            zh_last_chapter INTEGER NOT NULL DEFAULT 0,
            story_last_chapter INTEGER NOT NULL DEFAULT 0,
            en_last_chapter INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (release_id, run_id)
        );

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
            is_story_chapter INTEGER NOT NULL DEFAULT 1,
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

        CREATE TABLE IF NOT EXISTS idiom_checkpoints (
            release_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            stage_name TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (release_id, run_id)
        );

        CREATE TABLE IF NOT EXISTS idiom_candidates (
            candidate_id TEXT PRIMARY KEY,
            release_id TEXT NOT NULL,
            source_text TEXT NOT NULL,
            normalized_source_text TEXT NOT NULL,
            meaning_zh TEXT NOT NULL,
            meaning_en TEXT NOT NULL DEFAULT '',
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
            analyst_prompt_version TEXT NOT NULL,
            translation_run_id TEXT,
            translator_model_name TEXT,
            translator_prompt_version TEXT,
            schema_version INTEGER NOT NULL DEFAULT 1,
            dictionary_match INTEGER,
            source_strategies TEXT,
            chapter_coverage INTEGER,
            corpus_score REAL,
            context_snippets TEXT,
            literal_meaning_zh TEXT,
            idiomatic_meaning_zh TEXT,
            llm_is_idiom INTEGER,
            llm_usage_type TEXT,
            llm_translation_strategy TEXT,
            llm_reason_code TEXT,
            llm_confidence REAL,
            cluster_id TEXT,
            canonical_source_text TEXT,
            existing_policy_id TEXT,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (release_id, normalized_source_text)
        );

        CREATE TABLE IF NOT EXISTS idiom_policies (
            idiom_id TEXT PRIMARY KEY,
            release_id TEXT NOT NULL,
            source_text TEXT NOT NULL,
            normalized_source_text TEXT NOT NULL,
            meaning_zh TEXT NOT NULL,
            meaning_en TEXT NOT NULL DEFAULT '',
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

        CREATE TABLE IF NOT EXISTS idiom_translation_votes (
            vote_id TEXT PRIMARY KEY,
            candidate_id TEXT NOT NULL,
            release_id TEXT NOT NULL,
            translation_run_id TEXT NOT NULL,
            model_name TEXT NOT NULL,
            prompt_version TEXT NOT NULL,
            vote_kind TEXT NOT NULL,
            raw_output TEXT NOT NULL,
            cleaned_output TEXT NOT NULL,
            normalized_output TEXT NOT NULL,
            resolution_status TEXT NOT NULL,
            schema_version INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (candidate_id, translation_run_id, model_name, vote_kind)
        );

        CREATE INDEX IF NOT EXISTS idx_idiom_translation_votes_resume
            ON idiom_translation_votes (
                release_id,
                translation_run_id,
                model_name,
                candidate_id,
                vote_kind
            );

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

        CREATE TABLE IF NOT EXISTS graph_extraction_drafts (
            draft_id TEXT PRIMARY KEY,
            release_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            chapter_number INTEGER NOT NULL,
            chapter_source_hash TEXT NOT NULL,
            prompt_version TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            schema_version INTEGER NOT NULL DEFAULT 1,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (release_id, run_id, chapter_number, chapter_source_hash, prompt_version)
        );

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

        CREATE TABLE IF NOT EXISTS extracted_chapters (
            chapter_id TEXT PRIMARY KEY,
            release_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            chapter_number INTEGER NOT NULL,
            source_document_path TEXT NOT NULL,
            chapter_source_hash TEXT NOT NULL,
            placeholder_map_ref TEXT NOT NULL,
            created_by_stage TEXT NOT NULL,
            validation_status TEXT NOT NULL,
            schema_version TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS extracted_blocks (
            block_id TEXT PRIMARY KEY,
            chapter_id TEXT NOT NULL,
            release_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            chapter_number INTEGER NOT NULL,
            segment_id TEXT,
            parent_block_id TEXT NOT NULL,
            block_order INTEGER NOT NULL,
            segment_order INTEGER,
            source_text_zh TEXT NOT NULL,
            placeholder_map_ref TEXT NOT NULL,
            chapter_source_hash TEXT NOT NULL,
            schema_version TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_extracted_blocks_release_chapter
            ON extracted_blocks(release_id, chapter_number);
        CREATE INDEX IF NOT EXISTS idx_extracted_chapters_release_run
            ON extracted_chapters(release_id, run_id);
        """
    )

    columns = {
        str(row["name"])
        for row in conn.execute("PRAGMA table_info(summary_checkpoints)").fetchall()
    }
    if "story_last_chapter" not in columns:
        conn.execute(
            "ALTER" + " TABLE summary_checkpoints "
            "ADD COLUMN story_last_chapter INTEGER NOT NULL DEFAULT 0"
        )

    columns = {
        str(row["name"])
        for row in conn.execute("PRAGMA table_info(glossary_checkpoints)").fetchall()
    }
    if "input_hash" not in columns:
        conn.execute(
            "ALTER" + " TABLE glossary_checkpoints "
            "ADD COLUMN input_hash TEXT NOT NULL DEFAULT ''"
        )

    conn.commit()


def ensure_schema(conn: sqlite3.Connection, name: str) -> None:
    ensure_full_schema(conn)

