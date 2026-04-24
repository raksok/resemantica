# Handover Next Session

## Current Session: M14C — Summary Pipeline Drift Fixes

### Problem

Summary pipeline (`src/resemantica/summaries/`) drifted from SPEC §10:

1. **Missing chapter exclusion** — `titlepage.xhtml`, `nav.xhtml`, `book-2-divider.xhtml` in EPUB spine get processed as chapters
2. **Missing LLM content validation** — SPEC §10.6 requires content fidelity + continuity validation, but only schema + glossary checks exist. 5 of 8 SPEC §10.7 flags never set: `unsupported_claim`, `major_omission`, `wrong_referent`, `premature_reveal`, `ambiguity_overwritten`
3. **Wrong `derived_from_chapter_hash`** — `story_so_far_zh` uses only current chapter hash (line 159), but derives from ALL chapters ≤ N
4. **Non-incremental `story_so_far_zh`** — rebuilds all chapters from scratch each time instead of appending to `story_so_far_zh(n-1)` per SPEC §10.5

### Implemented

- **Chapter exclusion filter** via `[summaries] exclude_chapter_patterns` config; patterns matched against `source_document_path` filename
- **LLM content fidelity validation** — new `summary_zh_validate.txt` prompt; `validate_chinese_summary_content()` in `validators.py` calls analyst model; non-blocking flags stored in `zh_artifact` JSON
- **Composite hash fix** — `story_so_far_zh.derived_from_chapter_hash` now `sha256("|".join(sorted(all_hashes)))` of all contributing chapters
- **Incremental story_so_far** — loads `story_so_far_zh(n-1)` from DB, appends current chapter short summary; falls back to full rebuild when prior doesn't exist
- **`SummariesConfig`** dataclass in `settings.py`, wired through `load_config()`
- **Mock LLM updated** — `ScriptedSummaryLLM` handles `SUMMARY_ZH_VALIDATE` prompts, returns empty flags
- **4 test additions/updates** — chapter exclusion test, composite hash assertion, LLM flags in artifact test, incremental determinism preserved

### Verification

```
uv run pytest tests/ -q         → 141 passed
uv run ruff check src/ tests/   → 0 errors
uv run mypy src/                → no issues
```

### Working Tree State

New files:
- `src/resemantica/llm/prompts/summary_zh_validate.txt` — content fidelity validation prompt

Modified:
- `DATA_CONTRACT.md` — validation requirements, supported summary types
- `resemantica.toml` — added `[summaries]` section
- `src/resemantica/settings.py` — `SummariesConfig` dataclass
- `src/resemantica/summaries/validators.py` — `validate_chinese_summary_content()`
- `src/resemantica/summaries/pipeline.py` — 4 changes: exclusion filter, LLM validation, composite hash, incremental story
- `tests/summaries/test_summary_pipeline.py` — mock + 4 test updates

### Next Objective

Proceed with **M14B** (Batch Pilot):
- Task brief: `docs/40-tasks/task-14b-pilot.md`
- LLD: `docs/20-lld/lld-14b-pilot.md`
- Command: `python scripts/pilot/run.py --start 4 --end 4` (single chapter smoke)
- Full pilot: `python scripts/pilot/run.py --start 4 --end 13`

No push performed.

---

## Previous Session: M14A — Graph LLM Drift Fix

### Problem

Graph extractor used deterministic CJK keyword heuristics (suffix scanning `门`, `山`, `人`, `剑`, `诀` etc.) to infer entity categories and relationships. This drifted from SPEC §5.2, §12.3, §13.4 which mandate an analyst-model LLM for entity/relationship extraction. Heuristics produced wrong categories (e.g. `青云门` → "location" instead of "faction"), missed relationships entirely, and could not adapt to novel term patterns.

### Implemented

- **Analyst-model extraction**: per-chapter LLM call via `graph_extract.txt` prompt (12 SPEC edge types, JSON output format, glossary integration)
- **All heuristics removed** from `extractor.py`: `_CJK_TERM_RE`, suffix-guess maps, `_is_relationship_word()`, `_infer_category()`, `_INTRINSIC_CATEGORY_OVERRIDES`, hardcoded relationship hints
- **Prompt template** at `src/resemantica/llm/prompts/graph_extract.txt`: `{{`/`}}` escaping for `str.format()` compatibility
- **Expanded `WORLD_MODEL_EDGE_TYPES`** to all 12 SPEC edge types
- **`_build_llm_client()`** factory in `pipeline.py`; `preprocess_graph()` accepts optional `llm_client` param
- **Confidence tracking**: `_WorldModelObservation` gains `confidence` field; relationship merge uses max confidence
- **Mock LLM** (`ScriptedGraphLLM`) in `test_graph_pipeline.py`
- **4 integration tests** wired with mock
- **Milestone renumbering**: M14A inserted in task list, SPEC §26, ARCHITECT.md build order; original M14 → M14B

### Verification

```
uv run pytest tests/ -q         → 137 passed
uv run ruff check src/resemantica/graph/ tests/graph/  → 0 errors
uv run mypy src/resemantica/graph/                     → no issues
```

---

## Previous Session: Pipeline Split & Phased Batching (fix before M14 rerun)

### Problem

First M14 attempt with serial chapter-by-chapter translation caused ~30 s model swapping overhead per chapter, overwhelming the 8 GiB prompt cache. Needed to batch by phase: all pass1 across chapters → all pass2 → all pass3.

### Implemented

- **3-phase pipeline split**: per-pass functions with own checkpoint save/load
- **Pass1 prompt v2.0**: rewritten to canonical section-header format
- **Non-fatal pass1 validation**: failed blocks get `status: "failed"` in artifact
- **`_strip_artifacts()`** in `pass1.py`
- **`_prevalidate_source()`** in `pipeline.py`
- **Phased batching in `scripts/pilot/run.py`**
- **CLI/runner updated**
- **Config files added**: `resemantica.toml`, `__main__.py`, `run.py`

---

## Previous Session: M13 — Tracking & Evaluation

### Implemented

- **MLflow tracking** in `src/resemantica/tracking/mlflow.py`
- **Golden-set evaluation** in `src/resemantica/tracking/evaluation.py`
- **Quality summaries** in `src/resemantica/tracking/quality.py`
- **Golden-set fixtures** in `tests/golden_set/paragraphs.json` (7 paragraphs)
- **Tests**: 9 mlflow, 12 evaluation, 4 quality
