# Resemantica Data Contract

Version: 1.0
Sources: `SPEC.md`, `ARCHITECT.md`
Status: implementation-facing contract baseline

## Purpose

This document defines the data contracts that govern how Resemantica stores, promotes, validates, and consumes data across preprocessing, translation, reconstruction, and operations.

It is not a full physical schema dump. Instead, it defines the contract that each storage layer and artifact class must satisfy so that pipeline stages remain:

- deterministic where required
- resumable and inspectable
- safe against future-knowledge leaks
- explicit about authority versus working state
- reproducible across reruns and cleanup boundaries

## Scope

This contract covers:

- SQLite authority and working-state datasets
- LadybugDB graph datasets
- JSON runtime and operational artifacts
- event stream records
- lifecycle and promotion rules between stages
- versioning, validation, and mutability requirements

This contract does not define:

- model prompt wording beyond required metadata references
- UI widget state
- low-level physical indexing strategy
- concrete SQL DDL for every table

## Contract Principles

### 1. Source-of-Truth Separation

- Source Chinese text is the ultimate truth.
- Locked glossary is naming truth.
- Validated Chinese summaries are continuity truth.
- English summaries are derived artifacts only.
- Idiom policies are authoritative structured assets.
- Graph state is authoritative only for promoted entity and relationship memory.
- Chapter packets and paragraph bundles are runtime memory artifacts, not canonical story truth.

### 2. Promotion is Explicit

Working state must never silently become authority state. Every promotion requires deterministic validation and persisted provenance.

### 3. Runtime Reads Narrowed Context

Translation-time consumers should read chapter packets and paragraph bundles rather than rebuild broad memory or query the graph heavily per paragraph.

### 4. Versioned Everything That Matters

Any dataset or artifact that influences runtime translation must carry enough metadata to reproduce or invalidate it.

### 5. Chapter Safety is Part of the Contract

Any record that can leak future knowledge must expose the fields needed for chapter-safe filtering.

### 6. Inspectability Over Convenience

Each major stage must emit artifacts that make failures, retries, and promotions visible without requiring hidden in-memory state.

## Global Conventions

### Global Required Metadata

Unless a dataset is truly ephemeral, records should carry:

- `schema_version`
- `created_at`
- `updated_at`
- `created_by_stage`
- `run_id`

Where relevant, records should also carry:

- `release_id`
- `chapter_number`
- `artifact_path`
- `source_hash`
- `validation_status`

### Identifier Rules

- Every durable dataset must have a stable primary identifier.
- Human-readable names are not enough for joins or promotion.
- Runtime artifacts should include both a durable ID and a content hash where reproducibility matters.
- Cross-store references must use explicit IDs, not display text.

### Time and Ordering Rules

- Chapter ordering must be explicit through chapter numbers and stable source ordering metadata.
- Event records must be append-only and time-ordered.
- Graph relationships that vary over time must carry chapter-scoped validity fields.

### Mutability Classes

Every dataset belongs to one mutability class:

- `immutable_artifact`: once written, never edited; new version only
- `promotable_working_state`: may be revised until validated and promoted
- `authority_state`: only changes through controlled validation/promotion workflows
- `operational_state`: may update during execution for checkpoints, retries, and run progress

## Data Product Inventory

The platform manages these primary data products:

1. Source EPUB extraction artifacts
2. Glossary candidates
3. Locked glossary
4. Chinese summaries
5. Derived English summaries
6. Idiom policies
7. Graph entities, aliases, and relationships
8. Chapter packets
9. Paragraph bundles
10. Translation pass outputs
11. Validation reports
12. Checkpoints and run metadata
13. Event stream records
14. Cleanup plans and cleanup reports

## Contract by Store

### SQLite Contract

SQLite is the primary structured local store for authority state, promotable working state, and operational state.

SQLite must store at minimum:

- glossary candidates
- locked glossary
- summaries
- idioms
- checkpoints
- translation cache
- packet metadata
- run metadata
- cleanup bookkeeping

SQLite records must support:

- transactional promotion of working state into authority state
- idempotent reruns where the same source chapter is reprocessed
- scoped cleanup by run, release, stage, and chapter where applicable
- inspection of validation failures and conflict states

### LadybugDB Contract

LadybugDB stores graph-native translation-support state:

- entities
- aliases
- appearances
- relationships
- chapter and arc links
- lightweight world-model structure

LadybugDB must support:

- chapter-safe filtering
- reveal-safe filtering
- separation between provisional and confirmed state
- export or snapshot capability sufficient for packet reproducibility

### JSON Artifact Contract

JSON is the transport and inspection format for runtime memory and operational artifacts:

- chapter packets
- paragraph bundles
- validation reports
- event traces
- cleanup plans
- cleanup reports

JSON artifacts must be:

- versioned
- inspectable without executing code
- stored on disk with stable paths or path derivation rules
- referentially linked to `run_id`, `release_id`, `chapter_number`, and source hashes when relevant

## Dataset Contracts

### 1. Source Chapter Extraction

Purpose:

Represent deterministic EPUB ingest output before any model-driven enrichment.

Store:

- filesystem artifacts for extracted XHTML and reports
- SQLite metadata for chapter indexing and extraction state

Mutability:

- extraction artifacts are `immutable_artifact`
- extraction status metadata is `operational_state`

Required fields:

- `chapter_id`
- `chapter_number`
- `source_document_path`
- `block_id`
- `segment_id` nullable — present only when a block was split; format `ch{NNN}_blk{NNN}_seg{NN}`
- `parent_block_id` — references the original `block_id`; equals `block_id` for unsplit blocks
- `block_order`
- `segment_order` nullable — ordinal within the parent block's segments; null for unsplit blocks
- `source_text_zh`
- `placeholder_map_ref` — filesystem path to the placeholder map JSON file: `artifacts/releases/{release_id}/extracted/placeholders/chapter-{chapter_number}.json`. The file is an `immutable_artifact` keyed by `block_id`. Reconstruction (Phase 2) loads this file by path. No BLOB storage, no SQLite inline storage.
- `chapter_source_hash`
- `schema_version`

Validation requirements:

- XHTML parsed or failed with report
- stable block ordering present
- placeholder mapping reversible for supported types
- extracted text traceable back to original block
- segments ordered within parent block; concatenation of all segments for a block must equal the original block text

Downstream consumers:

- glossary discovery
- summary generation
- idiom detection
- graph extraction support
- translation source loading

### 2. Glossary Candidate Registry

Purpose:

Capture discovered term candidates and provisional English renderings before canon is locked.

Store:

- SQLite

Mutability:

- `promotable_working_state`

Required fields:

- `candidate_id`
- `source_term`
- `category`
- `source_language`
- `first_seen_chapter`
- `last_seen_chapter`
- `appearance_count`
- `evidence_snippet`
- `candidate_translation_en` nullable
- `discovery_run_id`
- `schema_version`

Recommended fields:

- `normalized_source_term`
- `candidate_status`
- `conflict_reason`
- `confidence`
- `translator_model_name`
- `translator_prompt_version`

Validation requirements:

- normalized duplicate detection
- category validation against mandatory enum
- explicit conflict recording
- separation between discovered term and approved canon

Mandatory category enum:
- `character`
- `alias`
- `title_honorific`
- `faction`
- `location`
- `technique`
- `item_artifact`
- `realm_concept`
- `creature_race`
- `generic_role`
- `event`
- `idiom`

Promotion rule:

Candidates may only be promoted into locked glossary after deterministic validation and naming-policy checks.

### 3. Locked Glossary

Purpose:

Provide the canonical naming layer for runtime translation and continuity derivation.

Store:

- SQLite

Mutability:

- `authority_state`

Required fields:

- `glossary_entry_id`
- `source_term`
- `target_term`
- `category`
- `status`
- `approved_at`
- `approval_run_id`
- `schema_version`

Recommended fields:

- `normalized_source_term`
- `normalized_target_term`
- `notes`
- `supersedes_entry_id`
- `source_evidence_ref`

Validation requirements:

- uniqueness within naming policy rules
- conflict against existing canon checked before write
- approved mappings stored separately from rejected or provisional variants

Runtime rule:

Locked glossary exact matches have highest retrieval priority.

### 4. Chinese Summary Authority

Purpose:

Provide authoritative continuity memory derived from source chapters.

Store:

- SQLite for structured storage
- JSON exports optional for inspection

Mutability:

- `authority_state` after validation

Required fields:

- `summary_id`
- `chapter_number`
- `summary_type`
- `content_zh`
- `derived_from_chapter_hash`
- `validation_status`
- `schema_version`

Supported summary types:

- `chapter_summary_zh_structured`
- `chapter_summary_zh_short`
- `story_so_far_zh`
- `arc_summary_zh`
- `previous_3_bundle_zh` if materialized

Persistence rule: every supported summary type must be materialized as a distinct row in the summary store at the end of its Phase 0 generation stage. Downstream consumers (packet assembly, translation) must never need to parse a parent JSON object to extract a child field. For example, `chapter_summary_zh_short` is derived from the `narrative_progression` field of the structured summary but is written as its own row with `summary_type = 'chapter_summary_zh_short'` and `content_zh` = the `narrative_progression` string.

Validation requirements:

- schema validation
- terminology validation against locked glossary where applicable
- continuity validation
- future-knowledge leak check

Update rule:

`story_so_far_zh(n)` must derive from the previous validated continuity state plus the current validated chapter summary, not from repaired English output.

### 5. Derived English Summaries

Purpose:

Provide operator-readable inspection summaries derived from authoritative Chinese continuity plus locked glossary.

Store:

- SQLite and/or JSON inspection artifacts

Mutability:

- `immutable_artifact` per version

Required fields:

- `summary_id`
- `chapter_number`
- `summary_type`
- `content_en`
- `source_summary_id`
- `glossary_version_hash`
- `schema_version`

Validation requirements:

- derivation provenance present
- must not be treated as continuity authority

Restriction:

English summaries may inform inspection but must not overwrite authoritative Chinese continuity memory.

### 6. Idiom Policy Store

Purpose:

Store approved idiom meaning and rendering policy outside the graph.

Store:

- SQLite

Mutability:

- `authority_state` once approved

Required fields:

- `idiom_id`
- `source_text`
- `meaning_zh`
- `preferred_rendering_en`
- `policy_status`
- `first_seen_chapter`
- `schema_version`

Recommended fields:

- `usage_notes`
- `category`
- `evidence_snippet`
- `confidence`

Validation requirements:

- duplicate detection
- explicit policy status
- chapter linkage for discovery provenance

Runtime rule:

Deterministic idiom matches outrank graph and fuzzy retrieval.

### 7. Graph Entities

Purpose:

Represent chapter-relevant translation-support entities in LadybugDB.

Store:

- LadybugDB

Mutability:

- confirmed records are `authority_state`
- extracted but unconfirmed records are `promotable_working_state`

Required fields:

- `entity_id`
- `entity_type`
- `canonical_name`
- `glossary_entry_id` — required for entities in glossary-covered categories (character, faction, location, technique, item_artifact, realm_concept, creature_race, event). Must reference a valid locked glossary entry. Nullable only for entity types that have no glossary counterpart (e.g., generic structural nodes).
- `first_seen_chapter`
- `last_seen_chapter`
- `revealed_chapter`
- `status`
- `schema_version`

Identity authority rule:

For glossary-covered categories, the Locked Glossary is the source of truth for identity creation. A graph entity must not be created for a term in a glossary-covered category unless a corresponding locked glossary entry exists. The entity extractor should defer entity creation for unmatched terms and flag them for retry after glossary promotion. This prevents dual-truth scenarios where graph entity names diverge from glossary names.

Recommended fields:

- `description_ref`
- `is_reader_safe`

Validation requirements:

- supported node type
- stable identifier
- canonical link to glossary where applicable — entities in glossary-covered categories must carry a valid `glossary_entry_id`
- no unsupported inferred ontology

### 7b. Deferred Entity Registry

Purpose:

Capture entity extraction discoveries for glossary-covered terms that have no locked glossary entry yet. Prevents dual-truth by deferring graph entity creation until glossary promotion.

Store:

- SQLite

Mutability:

- `promotable_working_state`

Required fields:

- `deferred_id`
- `term_text`
- `category` — must be in the glossary-covered set (character, faction, location, technique, item_artifact, realm_concept, creature_race, event)
- `evidence_snippet`
- `source_chapter`
- `discovered_at`
- `status` — one of: `pending_glossary`, `promoted`, `graph_created`
- `glossary_entry_id` — nullable; set after a matching locked glossary entry is created
- `schema_version`

Validation requirements:

- category must belong to the glossary-covered set (deferred entities are not created for non-glossary categories)
- status transitions must follow the lifecycle: `pending_glossary` → `promoted` → `graph_created`
- `glossary_entry_id` must be null when status is `pending_glossary` and non-null when status is `promoted` or `graph_created`

Promotion rule:

A deferred entity may only be promoted to `promoted` after a matching locked glossary entry exists. After promotion, the graph extraction worker creates the corresponding LadybugDB entity and updates status to `graph_created`.

Runtime rule:

Deferred entities are visible to glossary discovery (M3) as candidate input. They do not feed translation or packet assembly directly.

### 8. Graph Aliases

Purpose:

Represent alternate names, masked identities, and reveal-gated identity forms.

Store:

- LadybugDB

Mutability:

- provisional aliases are `promotable_working_state`
- confirmed aliases are `authority_state`

Required fields:

- `alias_id`
- `entity_id`
- `alias_text`
- `alias_language`
- `first_seen_chapter`
- `last_seen_chapter`
- `revealed_chapter`
- `confidence`
- `is_masked_identity`
- `schema_version`

Validation requirements:

- `entity_id` must resolve
- chapter-safe fields must be present
- masked identity flags must be explicit

### 9. Graph Relationships

Purpose:

Provide reveal-safe, chapter-safe relationship continuity for packet assembly and local translation support.

Store:

- LadybugDB

Mutability:

- provisional relationships are `promotable_working_state`
- confirmed relationships are `authority_state`

Required fields:

- `relationship_id`
- `type`
- `source_entity_id`
- `target_entity_id`
- `source_chapter`
- `start_chapter`
- `end_chapter` nullable
- `revealed_chapter`
- `confidence`
- `status`
- `schema_version`

Optional working-state fields:

- `provisional`
- `suspected`
- `disputed`
- `unconfirmed`
- `reader_unrevealed`
- `identity_masked`
- `state_reason`
- `evidence_strength`
- `notes`

Validation requirements:

- supported relationship type
- entity references resolve
- chapter-safe interval valid
- promotion must satisfy evidence threshold

Runtime rule:

A relationship is eligible for chapter `N` only when:

- `start_chapter <= N`
- `end_chapter` is null or `end_chapter >= N`
- `revealed_chapter <= N`

### 10. Chapter Packet

Purpose:

Provide the runtime-ready chapter memory container used by translation workflows.

Store:

- JSON artifact
- SQLite packet metadata index

Mutability:

- `immutable_artifact`

Required fields:

- `chapter_number`
- `chapter_metadata`
- `chapter_glossary_subset`
- `previous_3_summaries`
- `story_so_far_summary`
- `active_arc_summary`
- `chapter_local_idioms`
- `entity_context`
- `relationship_context`
- `warnings`
- `packet_schema_version`
- `chapter_source_hash`
- `glossary_version_hash`
- `summary_version_hash`
- `graph_snapshot_hash`
- `idiom_policy_hash`
- `packet_builder_version`
- `built_at`

Validation requirements:

- all required version hashes present
- contents are chapter-safe
- packet does not include unrestricted full-graph dump
- referenced assets resolve to known versions

Ownership:

- built by packet assembly workflow
- consumed by translation workflow

### 11. Paragraph Bundle

Purpose:

Provide the minimal local context required for the current paragraph or block.

Store:

- JSON artifact, generated at runtime or persisted for audit

Mutability:

- `immutable_artifact` when persisted

Required fields:

- `bundle_id`
- `chapter_number`
- `block_id`
- `matched_glossary_entries`
- `alias_resolutions`
- `matched_idioms`
- `local_relationships`
- `continuity_notes`
- `retrieval_evidence_summary`
- `risk_classification`
- `packet_ref`
- `schema_version`

Validation requirements:

- all included memory must be chapter-safe
- glossary and alias precedence must be respected
- evidence summary must identify which source layers contributed context

Runtime rule:

Paragraph bundles are the preferred translation-time context container and should replace heavy per-paragraph graph queries.

### 12. Translation Pass Outputs

Purpose:

Persist translation artifacts for audit, validation, retry, and resume.

Store:

- filesystem artifacts
- SQLite metadata and checkpoint references

Mutability:

- pass output artifacts are `immutable_artifact`
- pass status rows are `operational_state`

Required fields:

- `translation_artifact_id`
- `chapter_number`
- `block_id`
- `pass_number`
- `source_text_ref`
- `output_text_en`
- `model_name`
- `prompt_version`
- `bundle_id`
- `run_id`
- `schema_version`

Recommended fields:

- `retry_count`
- `risk_classification`
- `validation_status`
- `artifact_path`

Validation requirements:

- output non-empty unless explicitly skipped with reason
- placeholder restoration status recorded
- pass ordering preserved

Memory update rule:

- Pass 1 outputs never update authority memory
- Pass 2 outputs may update QA or warning artifacts, not authority truth directly
- Pass 3 outputs never update authority memory

### 13. Validation Reports

Purpose:

Capture structural, semantic, and memory-integrity checks in a machine-readable and inspectable form.

Store:

- JSON artifact
- SQLite metadata index optional

Mutability:

- `immutable_artifact`

Required fields:

- `report_id`
- `report_scope`
- `chapter_number` nullable
- `block_id` nullable
- `validation_type`
- `status`
- `severity`
- `flags`
- `artifact_refs`
- `generated_at`
- `schema_version`

Known validation families:

- structural
- semantic
- memory_integrity
- chapter_level

Common flags may include:

- `unsupported_claim`
- `major_omission`
- `wrong_referent`
- `glossary_conflict`
- `premature_reveal`
- `ambiguity_overwritten`
- `continuity_conflict`
- `schema_invalid`

### 14. Checkpoints and Run Metadata

Purpose:

Support resumability, operational visibility, and scoped cleanup.

Store:

- SQLite

Mutability:

- `operational_state`

Required run fields:

- `run_id`
- `release_id` nullable
- `workflow_name`
- `workflow_status`
- `started_at`
- `updated_at`
- `config_version`
- `source_epub_path`

Required checkpoint fields:

- `checkpoint_id`
- `run_id`
- `chapter_number`
- `block_id` nullable
- `pass_number` nullable
- `stage_name`
- `checkpoint_status`
- `latest_artifact_ref`
- `manual_approval_flag` (boolean, explicit operator override)
- `updated_at`
- `schema_version`

Validation requirements:

- only one active latest checkpoint per run and stage scope
- checkpoint references must resolve to real artifacts

### 15. Event Stream Records

Purpose:

Provide a shared visibility contract for CLI, TUI, and MLflow.

Store:

- append-only JSON lines, SQLite, or both

Mutability:

- `immutable_artifact`

Required fields:

- `event_id`
- `event_type`
- `event_time`
- `run_id`
- `release_id` nullable
- `stage_name`
- `chapter_number` nullable
- `block_id` nullable
- `severity`
- `message`
- `payload`
- `schema_version`

Expected event types:

- `stage_started`
- `stage_completed`
- `chapter_started`
- `chapter_completed`
- `paragraph_retry`
- `packet_assembled`
- `validation_failed`
- `cleanup_candidate_detected`
- `artifact_written`
- `warning_emitted`
- `run_finalized`

Contract rule:

Events are for visibility and diagnostics. They do not replace authority stores.

### 16. Cleanup Plans and Reports

Purpose:

Make destructive operations explicit, previewable, and auditable.

Store:

- JSON artifact
- SQLite cleanup bookkeeping

Mutability:

- plans and reports are `immutable_artifact`

Required plan fields:

- `cleanup_plan_id`
- `scope`
- `dry_run`
- `run_id` nullable
- `release_id` nullable
- `targets`
- `preserved_targets`
- `generated_at`
- `schema_version`

Required report fields:

- `cleanup_report_id`
- `cleanup_plan_id`
- `status`
- `deleted_targets`
- `preserved_targets`
- `warnings`
- `completed_at`
- `schema_version`

Validation requirements:

- cleanup scope explicit
- dry-run preview available
- preserved inputs, config, prompts, and manual overrides recorded by default unless scope says otherwise

## Cross-Stage Promotion Contracts

### Discovery to Canonical Glossary

- Input: glossary candidates
- Gate: normalization, duplicate detection, naming policy, conflict checks
- Output: locked glossary entries
- Forbidden: direct model write into locked glossary

### Structured Summary to Validated Continuity

- Input: draft or structured Chinese summaries
- Gate: schema, fidelity, continuity, terminology, future-knowledge checks
- Output: validated Chinese summaries
- Forbidden: using English repair output as continuity authority

### Provisional Graph State to Confirmed Graph State

- Input: extracted aliases and relationships
- Gate: entity resolution, evidence threshold, chapter-safe fields, reveal-safe rules
- Output: confirmed graph state
- Forbidden: treating provisional edges as runtime truth without promotion

### Authority Assets to Chapter Packet

- Input: locked glossary, validated summaries, confirmed idioms, confirmed graph state
- Gate: chapter-safe filtering, packet size control, asset version capture
- Output: immutable chapter packet
- Forbidden: dumping full subgraph or stale asset versions

### Chapter Packet to Paragraph Bundle

- Input: chapter packet plus local block context
- Gate: retrieval precedence, local relevance, risk classification
- Output: paragraph bundle
- Forbidden: broad full-chapter context injection into Pass 1 by default

## Validation Contract

Every stage that writes a durable artifact must record:

- what was validated
- which validator version ran
- pass or fail status
- blocking flags or warnings
- references to the affected artifact(s)

Minimum validation layers:

- structural
- semantic
- memory integrity
- chapter-level completion

Hard-failure conditions should include:

- unresolved placeholder failures
- invalid chapter-unsafe packet contents
- corrupted XHTML restoration
- invalid authority promotion

## Versioning and Reproducibility Contract

At minimum, runtime-relevant artifacts must support invalidation and rebuild using:

- `chapter_source_hash`
- `glossary_version_hash`
- `summary_version_hash`
- `graph_snapshot_hash`
- `idiom_policy_hash`
- builder or validator version identifiers
- generation timestamp

If any upstream authority hash changes, downstream dependent artifacts must be considered stale unless explicitly proven compatible.

## Retention and Cleanup Contract

- Authority data must not be deleted by cleanup unless the chosen scope explicitly includes it.
- Cleanup must support `run`, `translation`, `preprocess`, `cache`, and `all`.
- Cleanup must be release-aware where possible.
- Every destructive execution must have a previewable plan and a final report.

## Operational SLA Expectations

These are qualitative baseline expectations derived from the design:

- preprocessing outputs should be stable enough to reuse across translation runs until upstream authority changes
- translation checkpoints should be frequent enough to resume at chapter, paragraph, and pass granularity
- event records should be emitted for every meaningful workflow transition
- validation artifacts should be written early enough to diagnose failure without rerunning the entire workflow

## Implementation Guidance

- Start by encoding these contracts as typed schemas before filling in rich behavior.
- Prefer explicit status enums over null-heavy implicit state.
- Keep working-state and authority-state tables or status models clearly separable.
- Record provenance for every promotion edge between datasets.
- Do not let convenience caching become an alternate source of truth.

## Definition of Data Contract Compliance

Resemantica is compliant with this contract when:

1. every major dataset has a stable owner, identifier, version, and validation boundary
2. authority and working state cannot be confused in normal operation
3. chapter packets and paragraph bundles are reproducible from explicit upstream versions
4. runtime translation cannot silently consume future-unsafe or lower-priority conflicting memory
5. runs can be resumed, inspected, and cleaned up without corrupting authority data
