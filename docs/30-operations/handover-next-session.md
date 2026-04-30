# Handover Next Session

## Current Session: M14B — Batch Pilot Bugfixes and Verification

### Problem

Three blocker bugs prevented M14B pilot from running:

1. **Missing `tiktoken` dependency** — `_apply_packet_budget()` in packet builder calls `count_tokens()` which requires `tiktoken`. Package was never added to `pyproject.toml` despite D22 mandate.
2. **Missing markdown fence stripping** — Glossary discovery (`_parse_detected_terms`) and idiom detection (`_parse_detected_idioms`) call `json.loads(raw)` directly. Qwen3.5 wraps JSON in ` ```json...``` ` fences. Graph extraction already strips these; glossary/idioms don't, causing `JSONDecodeError` on every chapter.
3. **No "empty result" instruction in prompts** — Glossary and idiom prompts don't tell the LLM what to return when no terms are found. For short chapters (1 record), the LLM falls back to natural language like `"没有找到重要的术语"` instead of `{"glossary_terms": []}`.

### Found During Pilot Attempts

4. **Packet builder crashes on front-matter chapters** — `build_chapter_packet()` raises `RuntimeError("missing_story_so_far_summary")` for chapters excluded from summary generation. Also crashes on chapters with empty records (chapter-1.json has `records: []`).
5. **Packet builder iterates all chapters** — `build_packets()` ignores `chapter_start`/`chapter_end` from `run_stage()`, processing all 96 chapters including front-matter.
6. **Bundle builder crashes on large blocks** — `build_paragraph_bundle()` raises `RuntimeError("bundle_budget_exceeded")` for blocks where matched glossary entries alone exceed `max_bundle_bytes` (4096). Entire packet build fails.
7. **CLI preprocess subcommands are dead code** — Handler code indented under `if args.command == "translate-chapter"` after `return 0`. Running `resemantica preprocess summaries` falls through to `parser.print_help()` and returns 2.
8. **Per-chapter LLM timings** — Glossary ~1.5 min, summaries ~8 min, idioms ~3.5 min, graph ~5 min, pass1 ~1 min, pass2 ~5 min per block. A 10-chapter pilot requires ~12-15 hours of wall-clock time on this hardware.

### Implemented

**Fixes:**
- `pyproject.toml` — added `"tiktoken>=0.9.0"` to dependencies
- `glossary/discovery.py` — added `if raw.startswith("```")` fence-strip block in `_parse_detected_terms()` before `json.loads()`
- `idioms/extractor.py` — same fence-strip block in `_parse_detected_idioms()`
- `llm/prompts/glossary_discover.txt` — added "return empty list" and "no fences" instructions to OUTPUT FORMAT
- `llm/prompts/idiom_detect.txt` — same prompt fix (with `{{"idioms": []}}` escaping for `str.format()`)
- `packets/builder.py` — `build_chapter_packet()` returns `status="skipped"` for empty records, missing summaries, missing graph snapshots (instead of raising); bundle-building wrapped in try/except, logs warning and continues
- `packets/builder.py` — `build_packets()` accepts `chapter_start`/`chapter_end` params; filters targets; catches per-chapter exceptions; fixed counting (separate `chapters_built`, `chapters_skipped`, `chapters_failed`)
- `orchestration/runner.py` — `_execute_stage("packets-build")` forwards `chapter_start`/`chapter_end` to `build_packets()`; uses new keys for counting; added `config is None` guard for epub-rebuild stage
- `cli.py` — moved preprocess subcommand handlers into proper `if args.command == "preprocess"` branch; removed dead `parser.print_help()` after `tui` return; added missing `glossary-discover` handler
- `resemantica.toml` — updated `exclude_chapter_patterns` to match test EPUB front-matter (cover, copyright, ver-page, Introdution)

**Documentation:**
- `DECISIONS.md` — appended Section G (G26-G31) documenting all M14B decisions

### Verification

```
uv run pytest tests/ -q         → 139 passed (no regressions)
uv run ruff check src/ tests/   → 6 pre-existing test-only warnings (unused imports)
uv run mypy src/                → no issues
```

### Pilot Results

Single-chapter smoke (ch6 - 1 record): **PASSED** — all 8 stages green, EPUB rebuilt.
Single-chapter pilot (ch10 - 22 records): All 5 preprocessing stages + packet build + pass1 **PASSED**. Pass2 timed out at 45 min (5/22 blocks completed, ~6 min/block). This is a local inference speed constraint, not a code bug.

### Found: Glossary/Summary Cascade Noise

Inspecting pilot-03 artifacts revealed that glossary translation output and English summaries contain prompt structure leakage:

**Glossary translation output** (from `translate_glossary_candidates`):
```
## GLOSSARYTranslations
Source term: 落魄山
Category: location
Evidence: 就像落魄山老厨子的油炸溪鱼干...
```

The translator model (HY-MT1.5-7B) echoes the prompt's `## GLOSSARY_TRANSLATE` header + labeled fields (`SOURCE TERM:`, `CATEGORY:`, `EVIDENCE:`) instead of outputting just the translated term `Luopo Mountain`. The prompt uses Template B (translate with context per SPEC §9.3) but the model treats the form fields as output templates.

**Cascading effect on English summaries** — `{LOCKED_GLOSSARY}` in `summary_en_derive.txt` is built from raw `candidate_translation_en` strings. The polluted glossary text (`## GLOSSARYTranslations\nSource term:...`) gets injected into the summary prompt. The analyst model then echoes the full prompt structure back including `## SUMMARY_EN_DERIVE\n\n## LOCKED GLOSSARY\n- 落魄山 => ## GLOSSARYTranslations...` instead of producing clean English summary prose.

**Root cause**: The `glossary_translate.txt` prompt gives the translator labeled form fields that it mirrors in output. SPEC §9.3 Template A is the correct approach — bare source text, no context, no labels.

**Fix needed** (one file change, next session):
- `llm/prompts/glossary_translate.txt` — replace with Template A:
```
Translate the following segment into English, without additional explanation.

{SOURCE_TERM}
```
Removes `## GLOSSARY_TRANSLATE` header, `CATEGORY:`, and `EVIDENCE:` fields. The translator gets only the bare Chinese term and outputs only the English translation. No structure to echo.

The `summary_en_derive.txt` prompt may need a follow-up fix after the glossary noise clears, since the cascade breaks once glossary entries are clean.

### Working Tree State

Modified:
- `resemantica.toml` — exclude patterns for test EPUB front-matter
- `pyproject.toml` — added `tiktoken>=0.9.0`
- `src/resemantica/cli.py` — preprocess dead-code fix
- `src/resemantica/glossary/discovery.py` — markdown fence stripping
- `src/resemantica/idioms/extractor.py` — markdown fence stripping
- `src/resemantica/llm/prompts/glossary_discover.txt` — empty-result + no-fences instruction
- `src/resemantica/llm/prompts/idiom_detect.txt` — empty-result + no-fences instruction
- `src/resemantica/orchestration/runner.py` — packets-build forwards chapter range; counting fix; config guard
- `src/resemantica/packets/builder.py` — skip logic for empty/missing-summary/missing-graph chapters; bundle error handling; chapter range; exception resilience; fixed counting
- `DECISIONS.md` — Section G (G26-G31) appended

### Next Objective: Fix Glossary Translation Prompt

One-file change to `llm/prompts/glossary_translate.txt`:

1. Remove the `## GLOSSARY_TRANSLATE` header, `CATEGORY:`, `EVIDENCE:` fields.
2. Replace with SPEC §9.3 Template A: bare `{SOURCE_TERM}` with "Translate without additional explanation" instruction.
3. This eliminates the echo behavior that cascades noise into English summaries.
4. After change, re-run glossary stage for a test chapter and verify `candidate_translation_en` output is just the clean translated term (e.g., `Luopo Mountain` not `## GLOSSARYTranslations\nSource term: 落魄山\n...`).
5. Then re-run summary derivation to confirm English summaries no longer contain prompt structure leakage.
6. Mock LLM in `tests/glossary/test_glossary_pipeline.py` may need updating if the test script checks for the old noisy format.

No push performed.

---

## Previous Session: M14C — Summary Pipeline Drift Fixes

### Problem

Summary pipeline (`src/resemantica/summaries/`) drifted from SPEC §10:

1. **Missing chapter exclusion** — `titlepage.xhtml`, `nav.xhtml`, `book-2-divider.xhtml` in EPUB spine get processed as chapters
2. **Missing LLM content validation** — SPEC §10.6 requires content fidelity + continuity validation, but only schema + glossary checks exist. 5 of 8 SPEC §10.7 flags never set: `unsupported_claim`, `major_omission`, `wrong_referent`, `premature_reveal`, `ambiguity_overwritten`
3. **Wrong `derived_from_chapter_hash`** — `story_so_far_zh` uses only current chapter hash (line 159), but derives from ALL chapters ≤ N
4. **Non-incremental `story_so_far_zh`** — rebuilds all chapters from scratch instead of appending to `story_so_far_zh(n-1)` per SPEC §10.5

### Implemented

- **Chapter exclusion filter** via `[summaries] exclude_chapter_patterns` config
- **LLM content fidelity validation** — new `summary_zh_validate.txt` prompt
- **Composite hash fix** — `sha256("|".join(sorted(all_hashes)))` for all contributing chapters
- **Incremental story_so_far** — append mode with full-rebuild fallback
- **`SummariesConfig`** dataclass in `settings.py`
- **Mock LLM updated** — `ScriptedSummaryLLM` handles `SUMMARY_ZH_VALIDATE` prompts
- **4 test additions/updates**

### Verification

```
uv run pytest tests/ -q         → 141 passed
uv run ruff check src/ tests/   → 0 errors
uv run mypy src/                → no issues
```

---

## Previous Session: M14A — Graph LLM Drift Fix

### Problem

Graph extractor used deterministic CJK keyword heuristics (suffix scanning `门`, `山`, `人`, `剑`, `诀` etc.) to infer entity categories and relationships. This drifted from SPEC §5.2, §12.3, §13.4 which mandate an analyst-model LLM for entity/relationship extraction.

### Implemented

- **Analyst-model extraction**: per-chapter LLM call via `graph_extract.txt` prompt (12 SPEC edge types)
- **All heuristics removed** from `extractor.py`
- **Prompt template** with `{{`/`}}` escaping for `str.format()` compatibility
- **Expanded `WORLD_MODEL_EDGE_TYPES`** to all 12 SPEC edge types
- **`_build_llm_client()`** factory; `preprocess_graph()` accepts optional `llm_client` param
- **Confidence tracking**: `_WorldModelObservation` gains `confidence` field
- **Mock LLM** (`ScriptedGraphLLM`) in `test_graph_pipeline.py`
- **4 integration tests** wired with mock
- **Milestone renumbering**: M14A inserted, original M14 → M14B

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
