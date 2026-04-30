# Task 19c: Pipeline Event Emissions

## Milestone And Depends On

Milestone: M19

Depends on: M19a

## Goal
Add granular EventBus emissions to the 5 currently-silent pipelines so that the CLI progress subscriber (Task 19b) and future consumers can display real-time progress.

## Scope
In:
- Add EventBus emissions to `summaries/pipeline.py`.
- Add EventBus emissions to `glossary/pipeline.py` (3 sub-stages: discover, translate, promote).
- Add EventBus emissions to `idioms/pipeline.py`.
- Add EventBus emissions to `graph/pipeline.py`.
- Add EventBus emissions to `packets/builder.py`.
- All emissions follow the naming convention defined in Task 19b.

Out:
- Modifying EventBus API or Event model.
- Adding events to `runner.py` or `translation/pipeline.py` (already emit events).
- Modifying CLI output or subscriber logic (Task 19b).

## Owned Files Or Modules
- `src/resemantica/summaries/pipeline.py`
- `src/resemantica/glossary/pipeline.py`
- `src/resemantica/idioms/pipeline.py`
- `src/resemantica/graph/pipeline.py`
- `src/resemantica/packets/builder.py`

## Event Specifications

### Summaries pipeline (`preprocess-summaries`)

| Event | When | Payload |
|---|---|---|
| `preprocess-summaries.started` | Pipeline begins | `total_chapters` |
| `preprocess-summaries.chapter_started` | Per chapter | `chapter_number` |
| `preprocess-summaries.draft_generated` | LLM returns JSON | `chapter_number` |
| `preprocess-summaries.validation_completed` | After validation | `chapter_number`, `status` |
| `preprocess-summaries.chapter_completed` | Chapter done | `chapter_number` |
| `preprocess-summaries.chapter_skipped` | Non-story or failed | `chapter_number`, `reason` |
| `preprocess-summaries.completed` | Pipeline ends | `done`, `skipped`, `failed` counts |

### Glossary pipeline (`preprocess-glossary`)

| Event | When |
|---|---|
| `preprocess-glossary.started` | Pipeline begins |
| `preprocess-glossary.discover.chapter_started/completed` | Per chapter in discovery |
| `preprocess-glossary.discover.term_found` | New term discovered |
| `preprocess-glossary.translate.chapter_started/completed` | Per chapter in translation |
| `preprocess-glossary.promote.started/completed` | Promotion phase |
| `preprocess-glossary.completed` | Pipeline ends |

### Idioms pipeline (`preprocess-idioms`)

| Event | When |
|---|---|
| `preprocess-idioms.started` | Pipeline begins |
| `preprocess-idioms.chapter_started/completed` | Per chapter |
| `preprocess-idioms.chapter_skipped` | On skip |
| `preprocess-idioms.completed` | Pipeline ends |

### Graph pipeline (`preprocess-graph`)

| Event | When |
|---|---|
| `preprocess-graph.started` | Pipeline begins |
| `preprocess-graph.chapter_started/completed` | Per chapter |
| `preprocess-graph.entity_extracted` | New entity found |
| `preprocess-graph.chapter_skipped` | On skip |
| `preprocess-graph.completed` | Pipeline ends |

### Packets builder (`packets-build`)

| Event | When |
|---|---|
| `packets-build.started` | Build begins |
| `packets-build.chapter_started/completed` | Per chapter |
| `packets-build.chapter_skipped` | Non-story or stale |
| `packets-build.completed` | Build ends |

## Implementation Pattern
Each pipeline adds a local helper:

```python
from resemantica.orchestration.events import emit_event

def _emit(event_type, **kw):
    emit_event(run_id, release_id, event_type, stage_name, **kw)
```

All pipelines already receive `run_id` and `release_id` — no signature changes needed.

## Tests Or Smoke Checks
- Each pipeline emits expected events in order for a 2-chapter mock run.
- Event payloads contain correct `chapter_number`, `stage_name`, `run_id`.
- Skipped chapters emit `*_skipped` (not `*_completed`).
- Glossary pipeline emits discover → translate → promote in correct sequence.
- Existing tests continue to pass (events are fire-and-forget, no behavioral change).

## Done Criteria
- All 5 pipelines emit `{stage}.started` and `{stage}.completed` events.
- All 5 pipelines emit per-chapter `started`/`completed`/`skipped` events.
- Glossary pipeline emits sub-stage events for discover, translate, promote.
- Event payloads are accurate and match the convention.
- No existing pipeline behavior changes (events are side-effects only).
- Unit tests verify event emission order and payload correctness.
