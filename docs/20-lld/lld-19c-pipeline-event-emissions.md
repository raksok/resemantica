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
| `preprocess-summaries.chapter_completed` | Chapter fully processed | `chapter_number` |
| `preprocess-summaries.chapter_skipped` | Non-story or failed | `chapter_number`, `reason: str` |
| `preprocess-summaries.completed` | Pipeline ends | `done: int`, `skipped: int`, `failed: int` |

Emission points in `summaries/pipeline.py`:
- `preprocess-summaries.started` at pipeline entry (after chapter enumeration).
- `preprocess-summaries.chapter_started` at the start of each chapter loop iteration.
- `preprocess-summaries.draft_generated` after successful LLM response parsing in `generate_chapter_summary`.
- `preprocess-summaries.validation_completed` after `validate_chinese_summary` returns.
- `preprocess-summaries.chapter_completed` on successful summary materialization.
- `preprocess-summaries.chapter_skipped` on `is_story_chapter: false` or generation failure.
- `preprocess-summaries.completed` at pipeline return with aggregate counts.

#### Glossary pipeline — stage name: `preprocess-glossary`

| Event | When | Payload |
|---|---|---|
| `preprocess-glossary.started` | Pipeline begins | `total_chapters: int` |
| `preprocess-glossary.discover.chapter_started/completed` | Per chapter in discovery | `chapter_number` |
| `preprocess-glossary.discover.term_found` | New term discovered | `term: str`, `chapter_number` |
| `preprocess-glossary.translate.chapter_started/completed` | Per chapter in translation | `chapter_number` |
| `preprocess-glossary.promote.started/completed` | Promotion phase | `promoted_count: int` (on completed) |
| `preprocess-glossary.completed` | Pipeline ends | `discovered: int`, `translated: int`, `promoted: int` |

The glossary pipeline has 3 distinct phases. Each phase emits its own `chapter_started`/`chapter_completed` events under the phase namespace so the subscriber can distinguish them.

#### Idioms pipeline — stage name: `preprocess-idioms`

| Event | When | Payload |
|---|---|---|
| `preprocess-idioms.started` | Pipeline begins | `total_chapters: int` |
| `preprocess-idioms.chapter_started/completed` | Per chapter | `chapter_number` |
| `preprocess-idioms.chapter_skipped` | On skip | `chapter_number`, `reason: str` |
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
