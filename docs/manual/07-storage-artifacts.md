# 7. Storage & Artifacts

## Filesystem Layout

```text
{artifact_root}/releases/{release_id}/
├── work/
│   └── unpacked/              # Extracted EPUB contents (XHTML, images, CSS)
├── extracted/
│   ├── chapters/              # Per-chapter JSON extraction artifacts
│   │   └── chapter-{N}.json
│   ├── placeholders/          # Placeholder map JSON files
│   ├── reports/               # Validation reports
│   └── chapter-manifest.json  # Ordered chapter index
├── glossary/
│   ├── candidates.json        # Discovered glossary candidates
│   ├── conflicts.json         # Promotion conflicts
│   └── review.json            # Human review input/output
├── idioms/
│   ├── candidates.json        # Discovered idiom candidates
│   ├── policies.json          # Promoted idiom policies
│   ├── conflicts.json         # Promotion conflicts
│   └── review.json            # Human review input/output
├── summaries/                 # Summary JSON artifacts (one per chapter)
├── graph/
│   ├── snapshot.json          # Entity-relationship snapshot (debug)
│   └── warnings.json          # Extraction warnings
├── packets/                   # Chapter packets (one per chapter)
├── rebuild/
│   └── reconstructed.epub     # Final translated EPUB
├── graph.ladybug              # LadybugDB embedded graph database
├── resemantica.db             # Main SQLite database
├── resemantica.tracking.db    # Event tracking database
└── logs/                      # Loguru structured log files
```

## Database Overview

Three databases are used:

| Database | Type | Location | Source |
|----------|------|----------|--------|
| `resemantica.db` | SQLite (WAL mode) | `release_root/` | `db/sqlite.py` — 25 tables |
| `resemantica.tracking.db` | SQLite (WAL mode) | `release_root/` | `tracking/repo.py` — 2 tables |
| `graph.ladybug` | LadybugDB (embedded) | `release_root/` | `graph/client.py` — 4 node tables |

All SQLite connections use WAL mode. The `ensure_full_schema()` function creates all 25 tables at once; modular `ensure_schema(name)` calls from individual modules are pass-throughs.

---

## SQLite: `resemantica.db` (25 tables)

### Extraction

| Table | PK | Key Columns | Notes |
|-------|----|-------------|-------|
| `extracted_chapters` | `chapter_id` | `release_id`, `run_id`, `chapter_number`, `chapter_source_hash`, `placeholder_map_ref` | Indexed on `(release_id, run_id)` |
| `extracted_blocks` | `block_id` | `chapter_id`, `release_id`, `chapter_number`, `block_order`, `source_text_zh`, `placeholder_map_ref` | Indexed on `(release_id, chapter_number)` |

### Glossary System

| Table | PK / Unique | Key Columns |
|-------|-------------|-------------|
| `glossary_candidates` | `candidate_id` | `release_id`, `source_term`, `candidate_translation_en`, `candidate_status`, `llm_keep`; UNIQUE `(release_id, normalized_source_term, category)` |
| `glossary_alias_clusters` | `cluster_id` | `release_id`, `canonical_candidate_id`, `aliases_json`, `similarity_score` |
| `glossary_translation_votes` | `vote_id` | `release_id`, `translation_run_id`, `candidate_id`, `model_name`, `cleaned_output`, `resolution_status`; UNIQUE `(candidate_id, translation_run_id, model_name)`, indexed for ID-first resume on `(release_id, translation_run_id, model_name, candidate_id)` |
| `locked_glossary` | `glossary_entry_id` | `release_id`, `source_term`, `target_term`, `category`; UNIQUE `(release_id, normalized_source_term, category)` and `(release_id, normalized_target_term, category)` |
| `glossary_conflicts` | `conflict_id` | `release_id`, `candidate_id`, `conflict_type`, `conflict_reason` |
| `glossary_checkpoints` | `(release_id, run_id)` | `stage_name` |

Vote-resume candidate hydration must use `candidate_id` primary-key batches. The `UNIQUE (release_id, normalized_source_term, category)` index is for term identity, not for hydrating large resume ID lists.

### Summary System

| Table | PK / Unique | Key Columns |
|-------|-------------|-------------|
| `summary_drafts` | `draft_id`; UNIQUE `(release_id, chapter_number, summary_type)` | `content_json`, `chapter_source_hash`, `validation_status`, `is_story_chapter` |
| `validated_summaries_zh` | `summary_id`; UNIQUE `(release_id, chapter_number, summary_type)` | `content_zh`, `derived_from_chapter_hash`, `validation_status` |
| `derived_summaries_en` | `summary_id`; UNIQUE `(release_id, chapter_number, summary_type)` | `content_en`, `source_summary_hash`, `glossary_version_hash` |
| `summary_checkpoints` | `(release_id, run_id)` | `zh_last_chapter`, `story_last_chapter`, `en_last_chapter` |

### Idiom System

| Table | PK / Unique | Key Columns |
|-------|-------------|-------------|
| `idiom_candidates` | `candidate_id`; UNIQUE `(release_id, normalized_source_text)` | `source_text`, `preferred_rendering_en`, `meaning_zh`, `meaning_en`, `candidate_status` |
| `idiom_policies` | `idiom_id`; UNIQUE `(release_id, normalized_source_text)` | `source_text`, `preferred_rendering_en`, `meaning_zh`, `meaning_en`, `policy_status` |
| `idiom_conflicts` | `conflict_id` | `release_id`, `candidate_id`, `conflict_type`, `conflict_reason` |
| `idiom_translation_votes` | `vote_id`; UNIQUE `(candidate_id, translation_run_id, model_name, vote_kind)` | `vote_kind` ('rendering' or 'meaning'), `cleaned_output`, `resolution_status` |
| `idiom_checkpoints` | `(release_id, run_id)` | `stage_name` |

### Graph System

| Table | PK / Unique | Key Columns |
|-------|-------------|-------------|
| `graph_snapshots` | `snapshot_id`; UNIQUE `(release_id, snapshot_hash)` | `graph_db_path`, `entity_count`, `alias_count`, `relationship_count` |
| `graph_extraction_drafts` | `draft_id`; UNIQUE `(release_id, run_id, chapter_number, chapter_source_hash, prompt_version)` | `payload_json` |
| `deferred_entities` | `deferred_id`; UNIQUE `(release_id, normalized_term_text, category)` | `term_text`, `category`, `status` (for entities not yet in LadybugDB) |

### Packet System

| Table | PK / Unique | Key Columns |
|-------|-------------|-------------|
| `packet_metadata` | `packet_id`; UNIQUE `(release_id, chapter_number, packet_hash)` | `packet_path`, `bundle_path`, `glossary_version_hash`, `summary_version_hash`, `graph_snapshot_hash`, `idiom_policy_hash` |

### Checkpoints & Run Management

| Table | PK | Key Columns |
|-------|----|-------------|
| `runs` | `run_id` | `release_id`, `workflow_name`, `workflow_status` |
| `checkpoints` | `checkpoint_id` | `run_id`, `stage_name`, `chapter_number`, `checkpoint_status` |
| `translation_checkpoints` | `(release_id, run_id, chapter_number, pass_name)` | `source_hash`, `status`, `artifact_path`, `packet_version_hash` |
| `chunk_checkpoints` | `(release_id, run_id, stage_name, chunk_index)` | `chapter_start`, `chapter_end`, `status`, `metadata_json` |

---

## Tracking Database: `resemantica.tracking.db` (2 tables)

Created by `_init_tracking_schema()` in `tracking/repo.py`.

| Table | PK | Key Columns |
|-------|----|-------------|
| `run_state` | `run_id` | `release_id`, `stage_name`, `status`, `checkpoint_json`, `metadata_json` |
| `events` | `event_id` | `event_type`, `run_id`, `release_id`, `stage_name`, `chapter_number`, `severity`, `message`, `payload_json`. Indexed on `run_id`, `release_id`, `event_time`. |

---

## LadybugDB: `graph.ladybug` (4 node tables)

Created by `LadybugGraphBackend._ensure_schema()` in `graph/client.py`. These are **LadybugDB/Cypher node tables**, not SQLite.

| Table | PK | Columns |
|-------|----|---------|
| `GraphEntity` | `entity_id` | `status`, `revealed_chapter`, `first_seen_chapter`, `payload` |
| `GraphAlias` | `alias_id` | `status`, `entity_id`, `revealed_chapter`, `first_seen_chapter`, `payload` |
| `GraphAppearance` | `appearance_id` | `status`, `entity_id`, `chapter_number`, `payload` |
| `GraphRelationship` | `relationship_id` | `status`, `source_entity_id`, `target_entity_id`, `revealed_chapter`, `start_chapter`, `end_chapter`, `payload` |

Edges between nodes are managed through Cypher queries in `graph/client.py`.

---

## Placeholder System

Structural elements (images, links, MathML, ruby annotations) are replaced with placeholders during extraction and restored during rebuild.

Format: `⫷TYPE_N⫸` / `⫸/TYPE_N⫷`

Type codes: `IMG`, `LINK`, `MATH`, `RUBY`, `NOTE`, `CITE`, `FN` (footnote).

## Hashing Protocol

Artifacts are identified by hash chains:
- `chapter_source_hash` — SHA-256 of original chapter XHTML
- Packet staleness is detected by comparing upstream hashes (glossary, summary, graph, idiom) against values stored in `packet_metadata`

## Schema Coverage

Tables are created via the following `ensure_schema()` callers across the codebase:

| Module | Schema Names Used |
|--------|-------------------|
| `db/glossary_repo.py` | `"glossary"` |
| `db/summary_repo.py` | `"summaries"` |
| `db/graph_repo.py` | `"graph"` |
| `db/idiom_repo.py` | `"idioms"` |
| `db/extraction_repo.py` | `"extraction"` |
| `db/packet_repo.py` | `"packets"` |
| `translation/checkpoints.py` | `"translation"` |
| `orchestration/chunk_checkpoints.py` | `"chunk_checkpoints"` |
| `tracking/repo.py` | (own `_init_tracking_schema`) |
| `graph/client.py` | (own `_ensure_schema` for LadybugDB) |
