# LLD 19c: Pipeline Event Emissions

## Summary
Add granular EventBus emissions to the 5 currently-silent pipelines (summaries, glossary, idioms, graph, packets) so that the CLI progress subscriber and future consumers can display real-time progress during long-running sessions.

## Problem Statement
Only `runner.py` and `translation/pipeline.py` emit EventBus events. The remaining 5 pipeline types (summaries, glossary, idioms, graph, packets) run completely silently — no events, no progress indication. A `preprocess` command across all stages shows nothing per-chapter or per-operation.

## Technical Design

### 1. Implementation Pattern
Each pipeline adds a local helper to reduce boilerplate:

```python
from resemantica.orchestration.events import emit_event

def _emit(event_type, **kw):
    emit_event(run_id, release_id, event_type, stage_name, **kw)
```

All pipelines already receive `run_id` and `release_id` in their function signatures. No parameter changes needed. The `_emit` helper captures them in closure scope.

### 2. Event Naming Convention

All events follow the convention defined in LLD 19b:
- Stage lifecycle: `{stage_name}_started`, `{stage_name}_completed`
- Per-chapter: `{stage_name}.chapter_started`, `{stage_name}.chapter_completed`, `{stage_name}.chapter_skipped`
- Per-operation: `{stage_name}.{operation}.started/completed` (for multi-phase pipelines like glossary)
- Info events: `{stage_name}.{noun}_{verb}` (e.g., `preprocess-graph.entity_extracted`)

### 3. Event Specifications

#### Summaries pipeline — stage name: `preprocess-summaries`

| Event | When | Payload |
|---|---|---|
| `preprocess-summaries.started` | Pipeline begins | `total_chapters: int` |
| `preprocess-summaries.chapter_started` | Per chapter begin | `chapter_number` |
| `preprocess-summaries.draft_generated` | LLM returns parsed JSON | `chapter_number` |
| `preprocess-summaries.validation_completed` | Validation done | `chapter_number`, `status: str` |
| `preprocess-summaries.summary_generation_started` | A materialized summary row begins generation or deterministic derivation | `chapter_number`, `summary_type`, optional `model_name` |
| `preprocess-summaries.summary_generation_completed` | A materialized summary row is saved | `chapter_number`, `summary_type`, optional `model_name`, `summary_id`, row source hash fields |
| `preprocess-summaries.chapter_completed` | Chapter fully processed | `chapter_number` |
| `preprocess-summaries.chapter_skipped` | Non-story or failed | `chapter_number`, `reason: str` |
| `preprocess-summaries.completed` | Pipeline ends | `done: int`, `skipped: int`, `failed: int` |

Emission points in `summaries/pipeline.py`:
- `preprocess-summaries.started` at pipeline entry (after chapter enumeration).
- `preprocess-summaries.chapter_started` at the start of each chapter loop iteration.
- `preprocess-summaries.draft_generated` after successful LLM response parsing in `generate_chapter_summary`.
- `preprocess-summaries.validation_completed` after `validate_chinese_summary` returns.
- `preprocess-summaries.summary_generation_started` and `preprocess-summaries.summary_generation_completed` around the ordered story summary rows:
  - `story_so_far_zh` deterministic assembly and `save_validated_summary()`.
  - `story_so_far_zh_compact` compaction and `save_validated_summary()`.
  - `story_so_far_en` English derivation and `save_derived_summary()`.
- `preprocess-summaries.chapter_completed` on successful summary materialization.
- `preprocess-summaries.chapter_skipped` on `is_story_chapter: false` or generation failure.
- `preprocess-summaries.completed` at pipeline return with aggregate counts.

The `summary_generation_completed` payload must include enough identity to audit the saved row. Chinese validated summary rows include `summary_id` and `derived_from_chapter_hash`; derived English summary rows include `summary_id`, `source_summary_id`, `source_summary_hash`, and `glossary_version_hash`. Events keep the same chapter order as the pipeline: full Chinese story, compact Chinese story, English story, then `preprocess-summaries.chapter_completed`.

#### Glossary pipeline — stage name: `preprocess-glossary`

| Event | When | Payload |
|---|---|---|
| `preprocess-glossary.started` | Pipeline begins | `total_chapters: int` |
| `preprocess-glossary.discover.chapter_started/completed` | Per chapter in discovery | `chapter_number` |
| `preprocess-glossary.discover.term_found` | New term discovered | `term: str`, `chapter_number` |
| `preprocess-glossary.discover.prefilter.started/completed` | Pre-score df>=2 filter | candidate/filter counts |
| `preprocess-glossary.discover.scoring.started/progress/completed` | Corpus scoring | candidate/progress/score summary payloads |
| `preprocess-glossary.discover.filter.started/completed/persisted` | Deterministic filter and candidate save | candidate/filter counts, skip metadata on resume |
| `preprocess-glossary.discover.eval.started/completed/persisted` | LLM candidate evaluation phase | model, candidate, pending, kept/rejected counts |
| `preprocess-glossary.discover.eval.batch_started/completed/cached/failed` | LLM evaluation batches | batch index/counts, warning severity on failed batches |
| `preprocess-glossary.discover.dedup.started/completed/persisted` | Alias clustering and persistence | candidate, cluster, alias counts |
| `preprocess-glossary.discover.checkpoint.completed` | Filter/eval/dedup checkpoint saved or reused | `checkpoint_stage`, input hash, candidate count, skip metadata |
| `preprocess-glossary.discover.snapshot.artifact_written` | Discovery candidate snapshot written | `artifact_path`, `candidate_count` |
| `preprocess-glossary.discover.failed` | Fatal discovery subphase failure | severity `error`, `phase`, `error` |
| `preprocess-glossary.translate.loading_started/completed` | Translation DB prepare and pending-candidate load | `force`, `model_count`, `load_strategy`, pending counts and elapsed timings on completed |
| `preprocess-glossary.translate.model_started/completed` | Per translator model missing-vote batch | `model_name`, `pending_count`, `candidate_count`, `skipped_count` |
| `preprocess-glossary.translate.resolution.started/completed` | Vote resolution and canonical save phase | `pending_count`, `candidate_count`, translated/unresolved counts on completed |
| `preprocess-glossary.translate.chapter_started/completed` | Per chapter during vote resolution and canonical save | `chapter_number`, counts on completed |
| `preprocess-glossary.translate.unresolved` | Candidate vote did not resolve | severity `debug`, `candidate_id`, `source_term`, `unresolved_count` |
| `preprocess-glossary.translate.failed` | Model voting or resolution failed | severity `error`, `model_name`, `candidate_id`, `phase`, `error` |
| `preprocess-glossary.translate.snapshot.artifact_written` | Translation candidate snapshot written | `artifact_path`, `candidate_count` |
| `preprocess-glossary.resolve.started/completed` | Saved glossary vote replay | `translation_run_id`, candidate and resolved/unresolved counts on completed |
| `preprocess-glossary.resolve.unresolved` | Saved votes did not resolve | severity `debug`, `candidate_id`, `source_term`, `unresolved_count` |
| `preprocess-glossary.resolve.snapshot.artifact_written` | Resolve-only candidate snapshot written | `artifact_path`, `artifact_format`, `candidate_count` |
| `preprocess-glossary.resolve.failed` | Resolve-only replay failed | severity `error`, `phase`, `error` |
| `preprocess-glossary.fill.started/completed` | Optional unresolved-vote filler pass | `translation_run_id`, candidate/vote counts, `force` on started |
| `preprocess-glossary.fill.loading_completed` | Filler candidate selection completed | `candidate_count`, `filler_model_count`, `force` |
| `preprocess-glossary.fill.model_started/completed` | Per filler model missing-vote batch | `model_name`, `candidate_count`, `skipped_count` |
| `preprocess-glossary.fill.resolution.started/completed` | Filler-assisted deterministic resolution | candidate, translated, unresolved, skipped-vote counts |
| `preprocess-glossary.fill.unresolved` | Filler-assisted votes still did not resolve | severity `debug`, `candidate_id`, `source_term`, `unresolved_count` |
| `preprocess-glossary.fill.failed` | Filler vote generation or resolution failed | severity `error`, `phase`, `model_name`, `candidate_id`, `error` |
| `preprocess-glossary.review.started/completed` | Human-review file generation | `entries_written`, review paths on completed |
| `preprocess-glossary.review.json/csv.artifact_written` | Review JSON/CSV written | `artifact_path`, `artifact_format`, `entries_written` |
| `preprocess-glossary.review.failed` | Review generation failed | severity `error`, `phase`, `error` |
| `preprocess-glossary.promote.started/completed` | Promotion phase | `promoted_count`, `conflict_count` on completed |
| `preprocess-glossary.promote.candidates/conflicts.artifact_written` | Promotion snapshots written | `artifact_path`, `artifact_format`, count payload |
| `preprocess-glossary.promote.failed` | Promotion failed | severity `error`, `phase`, `error` |
| `preprocess-glossary.completed` | Pipeline ends | `discovered: int`, `translated: int`, `promoted: int` |

The glossary pipeline has 3 distinct phases. Each phase emits its own `chapter_started`/`chapter_completed` events under the phase namespace so the subscriber can distinguish them.
Glossary discovery keeps legacy `preprocess-glossary.discover.filter_completed`, `dedup_started`, `dedup_completed`, and `preprocess-glossary.eval.eval_batch_*` events for compatibility; scoped `discover.*` events are the preferred operator-visible boundaries.
For glossary translation, chapter events belong to the resolution/save phase. Model vote generation is model-first and emits per-model start/completion events before resolution begins. Reruns skip existing votes for the same release, run, and model unless forced. If prior run telemetry and complete model votes prove the pending set, loading may use `vote_resume` to avoid a full pending-candidate scan by reconstructing candidate IDs from saved votes. `glossary-resolve` emits the separate `resolve.*` family because it replays existing votes without model generation. `glossary-fill` emits the `fill.*` family because it performs targeted filler model calls and database/vote-status updates without writing a candidate snapshot artifact.

`loading_started` marks DB preparation and pending-candidate loading before model work begins. `loading_completed` reports the selected `load_strategy`, the loaded pending count, and elapsed load timings. For `vote_resume`, the loaded pending count is the resume ID universe; candidate rows are hydrated later in `candidate_id` primary-key chunks, not by scanning the release's candidate set. `model_completed.skipped_count` is the number of loaded candidates skipped for that model because durable votes already existed for `(release_id, run_id, model_name)`. A `preprocess-glossary.translate.failed` event after a model-server crash, including llama.cpp-backed local model crashes, records the failed phase/model/candidate but does not imply saved votes were rolled back or discarded. Operators can rerun the same release, run, and config without `--force` to continue from missing votes.

#### Idioms pipeline — stage name: `preprocess-idioms`

| Event | When | Payload |
|---|---|---|
| `preprocess-idioms.started` | Pipeline begins | `total_chapters: int` |
| `preprocess-idioms.chapter_started/completed` | Per chapter | `chapter_number` |
| `preprocess-idioms.chapter_skipped` | On skip | `chapter_number`, `reason: str` |
| `preprocess-idioms.review.started/completed` | Human-review file generation | `entries_written`, review paths on completed |
| `preprocess-idioms.review.json/csv.artifact_written` | Review JSON/CSV written | `artifact_path`, `artifact_format`, `entries_written` |
| `preprocess-idioms.review.failed` | Review generation failed | severity `error`, `phase`, `error` |
| `preprocess-idioms.promote.started/completed` | Promotion phase | `promoted_count`, `conflict_count` on completed |
| `preprocess-idioms.promote.candidates/policies/conflicts.artifact_written` | Promotion snapshots written | `artifact_path`, `artifact_format`, count payload |
| `preprocess-idioms.promote.failed` | Promotion failed | severity `error`, `phase`, `error` |
| `preprocess-idioms.completed` | Pipeline ends | `extracted: int`, `skipped: int` |

#### Graph pipeline — stage name: `preprocess-graph`

| Event | When | Payload |
|---|---|---|
| `preprocess-graph.started` | Pipeline begins | `total_chapters: int` |
| `preprocess-graph.chapter_started/completed` | Per chapter | `chapter_number` |
| `preprocess-graph.entity_extracted` | New entity found | `entity_name: str`, `chapter_number` |
| `preprocess-graph.chapter_skipped` | On skip | `chapter_number`, `reason: str` |
| `preprocess-graph.completed` | Pipeline ends | `extracted: int`, `skipped: int` |

#### Packets builder — stage name: `packets-build`

| Event | When | Payload |
|---|---|---|
| `packets-build.started` | Build begins | `total_chapters: int` |
| `packets-build.chapter_started/completed` | Per chapter | `chapter_number` |
| `packets-build.chapter_skipped` | Non-story or stale | `chapter_number`, `reason: str` |
| `packets-build.completed` | Build ends | `built: int`, `skipped: int` |

Emission points in `packets/builder.py`:
- `packets-build.started` at build entry.
- `packets-build.chapter_started/completed` around each `build_chapter_packet` call.
- `packets-build.chapter_skipped` when `build_chapter_packet` returns `status="skipped"`.
- `packets-build.completed` at build return with aggregate counts.

### 4. Behavioral Contract
- Events are fire-and-forget side-effects. Pipeline logic must not depend on event delivery.
- Event emission failures (e.g., EventBus subscriber exceptions) must not crash pipelines.
- The existing `EventBus.publish` already catches subscriber exceptions and logs warnings.
- No new EventBus subscriptions are added in this task — only emissions.
- Any run-context pipeline warning or error must be paired with `emit_event()`, a local `_emit()` wrapper, or a helper callback that emits in the caller. Loguru-only warning/error diagnostics are allowed only for helpers without run context or explicitly allowlisted low-level diagnostics.
- Expected control flow is informational: disabled Pass 3, stale packet rebuilds, non-story packet/EPUB skips, and empty extracted-record/frontmatter skips use `info`. Missing story summaries, exhausted translation retries, incomplete artifacts, and failure-driven skips remain warning or error events.
- Repair/fallback/failure events are first-class operational signals. Candidate-level unresolved events are debug diagnostics; the corresponding phase completion event is the single warning when its `unresolved_count` is non-zero. Current additions include `preprocess-summaries.story_compact_repaired`, `preprocess-summaries.story_compact_repair_failed`, `preprocess-glossary.translate.unresolved`, `preprocess-glossary.translate.failed`, `preprocess-graph.validation_failed`, `preprocess-continuity.chapter_failed`, `translate-chapter.pass1.failed`, `translate-chapter.pass2.failed`, `translate-chapter.pass3.failed`, and `translate-chapter.bundle_context_missing`.

## Data Flow
1. Pipeline function receives `run_id`, `release_id` from caller.
2. Pipeline calls `_emit("*.started", total_chapters=N)`.
3. For each chapter: `_emit("*.chapter_started", chapter_number=N)`.
4. On completion/skip: `_emit("*.chapter_completed" or "*.chapter_skipped", ...)`.
5. At end: `_emit("*.completed", done=N, skipped=N)`.
6. EventBus persists to SQLite tracking DB and notifies subscribers (CLI progress in Task 19b).

## Out of Scope
- Modifying EventBus API or Event model.
- Adding events to `runner.py` or `translation/pipeline.py` (already emit events).
- CLI subscriber logic (Task 19b).
- Changing pipeline function signatures.
