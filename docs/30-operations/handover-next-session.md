# Handover Next Session

## M13 Status: COMPLETE

### Implemented

- **MLflow tracking** in `src/resemantica/tracking/mlflow.py`:
  - `start_run_tracking(release_id, run_id)`: sets tracking URI (`sqlite:///{artifact_root}/mlflow.db`), creates experiment, starts run, subscribes to event bus
  - `stop_run_tracking()`: ends MLflow run
  - `track_run_metadata(run_id, release_id, metadata)`: logs params (str <250 chars), metrics (int/float), and long text as artifacts
  - `log_artifact(local_path, artifact_path)`: delegates to `mlflow.log_artifact`
  - `_on_stage_event(event)`: auto-subscriber — logs `stage.{name}.started` param, computes `stage.{name}.latency_seconds` metric on completion, logs status/message/payload items
  - Auto-subscribes once to `stage.started`, `stage.completed`, `stage.failed` events

- **Golden-set evaluation** in `src/resemantica/tracking/evaluation.py`:
  - `score_fidelity(translated, expected) → float`: `SequenceMatcher.ratio()`
  - `score_terminology(translated, terms) → float`: case-insensitive term presence ratio
  - `score_readability(text) → float`: heuristic based on avg word length (target 5) and avg sentence length (target 17)
  - `run_benchmark(golden_set_path, translate_fn, *, terms) → dict`: loads JSON items, runs `translate_fn` per item, returns aggregated scores + per-item results

- **Quality summaries** in `src/resemantica/tracking/quality.py`:
  - `get_stage_summary(release_id)`: stage-wise completed/failed/error counts from tracking DB
  - `get_warning_trends(release_id, limit)`: recent warning/error events with severity, message, timestamp
  - `get_metric_totals(release_id)`: total events, warning count, error count, distinct stages run

- **Golden-set fixtures** in `tests/golden_set/paragraphs.json`:
  - 7 paragraphs covering: honorific, idiom, lore_exposition, pronoun_ambiguity, identity_concealment, relationship_reversal, xhtml_heavy
  - Each with `source_zh`, `expected_en`, `category`, `difficulty` fields

### Tests Added

- `tests/tracking/test_mlflow.py`: 9 tests — start/stop tracking, event bus subscription, metadata logging, stage event handler (start/completion), artifact logging
- `tests/tracking/test_evaluation.py`: 4 test classes (12 tests) — score_fidelity edge cases, score_terminology (present/missing/case), score_readability, run_benchmark (keys/aggregation/terminology/fixture load)
- `tests/tracking/test_quality.py`: 3 test classes (4 tests) — stage summary counts, warning trends (filtering/limit), metric totals
- `tests/tracking/__init__.py`: package marker

### Verification

```
uv run ruff check src/ tests/   → all checks passed (0 errors)
uv run mypy src/                → no issues (81 source files)
uv run pytest tests/ -q         → 137 passed
```

### Working Tree State

New files:
- `src/resemantica/tracking/mlflow.py`
- `src/resemantica/tracking/evaluation.py`
- `src/resemantica/tracking/quality.py`
- `tests/tracking/__init__.py`
- `tests/tracking/test_mlflow.py`
- `tests/tracking/test_evaluation.py`
- `tests/tracking/test_quality.py`
- `tests/golden_set/paragraphs.json`

Modified files:
- `pyproject.toml` (added `mlflow` dependency)

### Next Objective

Start **M14** (Batch Pilot):

- Task brief: `docs/40-tasks/task-14-pilot.md`
- Depends on: M10–M13

No push performed.
