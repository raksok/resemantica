# Handover Next Session

## Current Session: Pipeline Split & Phased Batching (fix before M14 rerun)

### Problem

First M14 attempt with serial chapter-by-chapter translation caused ~30 s model swapping overhead per chapter, overwhelming the 8 GiB prompt cache. Needed to batch by phase: all pass1 across chapters → all pass2 → all pass3.

### Implemented

- **3-phase pipeline split**: `translate_chapter()` → `translate_chapter_pass1()`, `translate_chapter_pass2()`, `translate_chapter_pass3()`, each independent with own checkpoint save/load
- **Pass1 prompt v2.0**: rewritten to canonical section-header format (`## INSTRUCTIONS` header, bare `{SOURCE_TEXT}` — no `## SOURCE TEXT` header). Model was dropping placeholders without structured instructions.
- **Non-fatal pass1 validation**: failed blocks get `status: "failed"` in artifact; pass2 skips them; no `RuntimeError` abort
- **`_strip_artifacts()`** in `pass1.py`: finds source text in model output, discards echoed preamble
- **`_prevalidate_source()`** in `pipeline.py`: removes orphaned closing placeholders before LLM call
- **Phased batching in `scripts/pilot/run.py`**: 3-phase loops (all pass1 → all pass2 → all pass3) to maximise prompt cache reuse
- **CLI/runner updated**: imports and calls use per-pass functions
- **Test fixes**:
  - Mock detection order: `PASS3` checked before `## INSTRUCTIONS` (pass3 prompt also has `## INSTRUCTIONS`)
  - `FailPass2` detection: checks `Correct the English` (pass2 lacks `## INSTRUCTIONS`)
  - Chapter report now includes `pass3_enabled` and `risk_classifications`
- **Config files added**:
  - `resemantica.toml`: `translator_name = "HY‑MT1.5‑7B"`, `analyst_name = "Qwen3.5‑9B‑GLM5.1"`, `pass3_default = false`
  - `src/resemantica/__main__.py`: entry point
  - `scripts/pilot/run.py`: pilot orchestrator

### Verification

```
uv run pytest tests/ -q         → 137 passed (all 4 previously-failing pass)
```

### Working Tree State

New files:
- `resemantica.toml`
- `scripts/pilot/run.py`
- `src/resemantica/__main__.py`

Modified files:
- `src/resemantica/translation/pipeline.py` — major refactor, per-pass functions
- `src/resemantica/translation/pass1.py` — added `_strip_artifacts()`, context params
- `src/resemantica/llm/prompts/translate_pass1.txt` — version 2.0
- `src/resemantica/orchestration/runner.py` — phased runner
- `src/resemantica/cli.py` — updated imports and calls
- `tests/translation/test_translate_chapter.py`
- `tests/translation/test_pass3_and_risk.py`
- `pyproject.toml` — added `ladybug`, `openai`
- `uv.lock`
- `ARCHITECT.md` — hardware/model assumptions section

### Next Objective

**Rerun M14** (Batch Pilot):

- Task brief: `docs/40-tasks/task-14-pilot.md`
- Command: `python scripts/pilot/run.py --start 4 --end 4` (single chapter)
- Then full pilot if single chapter works: `--start 4 --end 13`
- Key constraint: minimise model swapping = batch all pass1 across chapters first, then all pass2, then all pass3

No push performed.

---

## Previous Session: M13 Status: COMPLETE

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

- `tests/tracking/test_mlflow.py`: 9 tests
- `tests/tracking/test_evaluation.py`: 4 test classes (12 tests)
- `tests/tracking/test_quality.py`: 3 test classes (4 tests)
- `tests/tracking/__init__.py`: package marker

### Verification

```
uv run ruff check src/ tests/   → all checks passed (0 errors)
uv run mypy src/                → no issues (81 source files)
uv run pytest tests/ -q         → 137 passed
```

### Working Tree State (previous)

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
