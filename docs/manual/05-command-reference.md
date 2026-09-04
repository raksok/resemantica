# 5. Command Reference

## Global Options

These options are available on most commands:

| Option | Description |
|--------|-------------|
| `-c, --config PATH` | Path to config TOML (default: `./resemantica.toml`) |
| `-v, --verbose` | Increase verbosity; repeat for DEBUG (`-vvv`/`-vvvv`) |
| `-r, --release ID` | Release identifier; creates `artifacts/releases/<ID>/` |
| `-R, --run ID` | Run identifier for checkpoint/artifact scoping |
| `-f, --force` | Rebuild instead of resuming |
| `-w, --allow-rewind` | Allow running even if later stages started |
| `-C, --chapter N` | Single chapter number (mutually exclusive with `--start`) |
| `-s, --start N` | First chapter in range (inclusive) |
| `-e, --end N` | Last chapter in range (inclusive) |
| `-b, --batched, --batched-model-order` | Run all chapters pass1-first, then pass2/3 |

---

## `extract` (alias: `ext`)

Unpack, validate, and round-trip an EPUB.

```bash
uv run rsem extract -i <epub> -r <release> [options]
```

| Option | Required | Description |
|--------|----------|-------------|
| `-i, --input PATH` | Yes | Path to source EPUB file |

Produces: validation report, placeholder maps, and a lossless reconstructed EPUB.

Exit behavior: always prints `status`, `release_root`, `rebuilt_epub`, `validation_report`.

---

## `translate` (alias: `tra`)

Two-pass translation of extracted chapters.

```bash
uv run rsem translate -r <release> -R <run> (-C <N> | -s <N> [-e <N>]) [options]
```

| Option | Required | Description |
|--------|----------|-------------|
| `-r, --release ID` | Yes | Release identifier |
| `-R, --run ID` | Yes | Artifact scoping identifier |
| `-C, --chapter N` | * | Single chapter (* mutually exclusive) |
| `-s, --start N` | * | Range start |
| `-e, --end N` | No | Range end (requires `--start`) |
| `-f, --force, --force-pass1` | No | Ignore checkpoints, re-run |
| `-b, --batched` | No | Batched model order |

Output: pass1 and pass2 artifacts per chapter.

---

## `preprocess` (alias: `pre`)

Preprocessing sub-stages. Requires a subcommand.

### `glossary-discover` (alias: `gls-discover`)

Scan chapters for candidate glossary terms.

```bash
uv run rsem preprocess glossary-discover -r <release> [options]
```

| Option | Description |
|--------|-------------|
| `-p, --pruning-threshold FLOAT` | Min corpus score (override config) |
| `--eval-batch-size INT` | Batch size for LLM evaluation |
| `--skip-llm-eval` | Skip LLM candidate evaluation |
| `--dedup-threshold FLOAT` | Embedding similarity for alias clustering |
| `-f, --force` | Rebuild instead of resume |

Output: `candidates.json`

Resume is the default. Discovery reuses completed per-chapter raw candidate state when the chapter source hash, summary seed content, and discovery settings still match. Missing or stale chapters are re-extracted; corpus scoring, filtering, LLM evaluation, and deduplication then continue from the rebuilt aggregate. `--force` clears discovery state for the run and rebuilds all chapters.

### `glossary-translate` (alias: `gls-translate`)

Translate candidates to provisional English.

```bash
uv run rsem preprocess glossary-translate -r <release> [-R <run>] [options]
```

| Option | Description |
|--------|-------------|
| `-R, --run ID` | Vote/checkpoint scope (default: `glossary-translate`) |
| `-f, --force` | Regenerate votes instead of skipping existing per-model votes |

Resume is the default. Glossary translation skips existing votes for the same release, run, and configured model, so rerunning after a local model-server crash continues from the first missing vote. Use the same `-r`, same `-R`, and same config without `--force` to resume. When a complete seed model vote set exists, resume avoids a full candidate-table scan and loads candidate rows later by `candidate_id` primary key. Change the configured model list only when intentionally abandoning a crashing model.

### `glossary-resolve` (alias: `gls-resolve`)

Re-run the deterministic glossary voter over saved translation votes without
calling translation models.

```bash
uv run rsem preprocess glossary-resolve -r <release> [-R <translation-run>]
```

Output: updated `candidates.json`

The default run scope is `glossary-translate`, matching the default
`glossary-translate` vote scope. Use this command after improving voter logic or
changing deterministic style rules, then regenerate review files:

```bash
uv run rsem preprocess glossary-resolve -r <release> -R glossary-translate
uv run rsem preprocess glossary-review -r <release>
```

Existing vote rows are not regenerated. Only candidate canonical translation
fields and vote `resolution_status` values are updated.

### `glossary-fill` (alias: `gls-fill`)

Call filler model(s) only for unresolved glossary vote cases.

```bash
uv run rsem preprocess glossary-fill -r <release> [-R <translation-run>] --model <filler-model> [--model <filler-model>] [--force] [--pick-existing]
```

| Option | Description |
|--------|-------------|
| `-R, --run ID` | Vote scope to fill (default: `glossary-translate`) |
| `--model NAME` | Filler model name; repeat for multiple filler models |
| `-f, --force` | Regenerate existing filler votes for the selected filler model name(s) |
| `--pick-existing` | Use the filler model as an adjudicator that must choose one existing alternative |

`glossary-fill` loads candidates that are still unresolved after deterministic
saved-vote resolution and have no canonical glossary translation. It writes each
filler output as a normal `glossary_translation_votes` row, then re-runs the
deterministic resolver with configured translator models first and filler models
last. It does not rerun full glossary translation and does not rewrite
`candidates.json`; regenerate review files afterward if needed.

With `--pick-existing`, `glossary-fill` does not add a normal filler vote.
Instead, the model must pick one existing vote alternative. Accepted picks update
the candidate translation and write an auditable `<model>:picker` vote with
`resolution_status = "picked"`. Invalid or invented picker outputs leave the
candidate unresolved. Locked glossary entries are still protected by promotion
validation.

### `glossary-review` (alias: `gls-review`)

Generate review files for human editing.

```bash
uv run rsem preprocess glossary-review -r <release> [options]
```

Output: `review.json` and `review.csv`

This command reads translated/voted glossary candidates from SQLite, writes the
two review files, and does not call LLMs.

### `glossary-promote` (alias: `gls-promote`)

Validate and promote candidates into locked glossary.

```bash
uv run rsem preprocess glossary-promote -r <release> [options]
```

| Option | Description |
|--------|-------------|
| `-F, --review, --review-file PATH` | Apply user edits from review file |
| `-f, --force` | Re-promote even if already promoted |

Output: promoted entries in SQLite, `conflicts.json` if conflicts found.

### `summaries` (alias: `sum`)

Generate chapter summaries.

```bash
uv run rsem preprocess summaries -r <release> [options]
```

Produces: `story_so_far_zh`, `chapter_summary_zh_short`, `arc_summary_zh` per chapter in SQLite.

### `idioms`

Detect and validate idiom policies.

```bash
uv run rsem preprocess idioms -r <release> [options]
```

### `idiom-resolve` (alias: `idi-resolve`)

Re-run the deterministic idiom voter over saved translation votes without
calling translation models.

```bash
uv run rsem preprocess idiom-resolve -r <release> [-R <translation-run>]
```

Output: updated `idioms/candidates.json`

The default run scope is `idioms`, matching the normal `preprocess idioms`
vote scope. Rendering votes decide whether a candidate can promote; meaning
votes are also replayed when saved votes already have a majority.

### `idiom-fill` (alias: `idi-fill`)

Call filler model(s) only for unresolved idiom rendering vote cases.

```bash
uv run rsem preprocess idiom-fill -r <release> [-R <translation-run>] --model <filler-model> [--model <filler-model>] [--force]
```

| Option | Description |
|--------|-------------|
| `-R, --run ID` | Vote scope to fill (default: `idioms`) |
| `--model NAME` | Filler model name; repeat for multiple filler models |
| `-f, --force` | Regenerate existing filler rendering votes for the selected filler model name(s) |

`idiom-fill` targets rendering only, because rendering is what blocks idiom
promotion. It writes filler outputs as normal `idiom_translation_votes` rows
with `vote_kind = "rendering"` and then re-runs deterministic resolution with
configured translator models first and filler models last.

### `idiom-review` (alias: `idi-review`)

Generate idiom review files.

```bash
uv run rsem preprocess idiom-review -r <release> [options]
```

Output: `review.json` and `review.csv`

### `idiom-promote` (alias: `idi-promote`)

Validate and promote idiom policies.

```bash
uv run rsem preprocess idiom-promote -r <release> [options]
```

| Option | Description |
|--------|-------------|
| `-F, --review, --review-file PATH` | Apply user edits from review file |

### `graph`

Build entity-relationship graph.

```bash
uv run rsem preprocess graph -r <release> [options]
```

Output: `graph.ladybug` (LadybugDB), `snapshot.json`, `warnings.json`

Graph extraction resumes by default from matching per-chapter drafts. A draft is
reusable only when release, run, chapter number, chapter source hash, and
`graph_extract.txt` prompt version match. `--force` deletes scoped drafts before
rebuilding. Console progress shows chapter position, cache hits, extracted
entity/relationship counts, and deferred glossary terms.

The graph prompt includes a chapter-local locked glossary context: only
graph-relevant locked source terms that literally appear in the current chapter
source text are rendered. Deterministic post-LLM matching still uses the full
graph-relevant locked glossary loaded for the release.

### `continuity`

Refresh graph-grounded compact continuity.

```bash
uv run rsem preprocess continuity -r <release> [options]
```

The Chinese graph compact row is derived from previous continuity, recent
validated summaries, and chapter-safe graph anchors. The English inspection row
uses source-local locked glossary context, so `SUMMARY_EN_DERIVE` includes only
locked source terms that literally appear in the compact Chinese continuity.
Prompt budget is checked before the translator model call.

---

## `packets build` (alias: `pac build`)

Build chapter packets from validated upstream state.

```bash
uv run rsem packets build -r <release> -R <run> [options]
```

Assembles `ChapterPacket` per chapter with glossary, summaries, idioms, graph context. Derives `ParagraphBundle` per block.

---

## `rebuild` (alias: `reb`)

Rebuild EPUB from translated pass artifacts.

```bash
uv run rsem rebuild -r <release> -R <run> [options]
```

Output: `rebuild/reconstructed.epub`

Rebuild always enforces a direct-input gate and preflights placeholder maps plus complete, non-empty Pass 2/3 block coverage before changing reconstruction outputs. It does not require historical glossary votes, summary files, graph snapshots, or packets after final translations exist. If preflight fails, the existing work tree and EPUB are preserved; repair the reported translation chapters first.

---

## `run`

Orchestration workflow control.

### `production` (alias: `prod`)

Execute full pipeline in canonical order.

```bash
uv run rsem run production -r <release> -R <run> [options]
```

Stage order: `preprocess-summaries` → `preprocess-glossary` → `preprocess-idioms` → `preprocess-graph` → `preprocess-continuity` → `packets-build` → `translate-range` → `epub-rebuild`

| Option | Description |
|--------|-------------|
| `-n, --dry-run` | Print stage plan without executing |

### `resume`

Resume from last checkpoint.

```bash
uv run rsem run resume -r <release> -R <run> [options]
```

| Option | Description |
|--------|-------------|
| `-t, --stage, --from-stage STAGE` | Override resume point |

### `retry-failed`

Retry failed pipeline units. The system classifies failures as **retryable** (auto-recovered) or **non-retryable** (require human intervention):

| Stage | Retryable if... | Non-retryable if... |
|-------|-----------------|---------------------|
| `preprocess-summaries` | Chapter has `validation_status = 'failed'` or missing `validated_summaries_zh` rows | — |
| `preprocess-glossary` | Candidate not in a terminal state | Entries in `glossary_conflicts` table for policy/source conflicts (need human review) |
| `preprocess-idioms` | Candidate not in a terminal state | Entries in `idiom_conflicts` table (need human review) |
| `preprocess-graph` | Chapter missing fresh `graph_extraction_drafts`, stale graph prompt/source hash, or failed events | — |
| `preprocess-continuity` | Chapter missing compact continuity summary or has failed events | — |
| `packets-build` | Chapter missing `packet_metadata` or has failed events | — |
| `translate-range` | Chapter has failed or incomplete translation checkpoints | — |

```bash
uv run rsem run retry-failed -r <release> -R <run> [options]
```

| Option | Description |
|--------|-------------|
| `-t, --stage` | Stage to retry: `preprocess-summaries`, `preprocess-glossary`, `preprocess-idioms`, `preprocess-graph`, `preprocess-continuity`, `packets-build`, `translate-range`, `all` |
| `-n, --dry-run` | Report retryable/non-retryable units without mutation |

### `cleanup-plan` (alias: `cln-plan`)

Preview deletable artifacts.

```bash
uv run rsem run cleanup-plan -r <release> -R <run> [options]
```

| Option | Description |
|--------|-------------|
| `-S, --scope` | Cleanup scope (default: `run`) |

Scopes: `run`, `translation`, `preprocess`, `cache`, `keep-extracted`, `last-good-chunk`, `all`, `factory`

### `cleanup-apply` (alias: `cln-apply`)

Execute cleanup.

```bash
uv run rsem run cleanup-apply -r <release> -R <run> [options]
```

| Option | Description |
|--------|-------------|
| `-S, --scope` | Same scopes as cleanup-plan |
| `-f, --force` | Skip scope-mismatch safety check |

---

## `tui`

Launch the Textual TUI.

```bash
uv run rsem tui [options]
```

| Option | Description |
|--------|-------------|
| `-r, --release` | Release to pre-load |
| `-R, --run` | Run to pre-load |
| `-c, --config PATH` | Config path |
| `-s, --start` / `-e, --end` / `-C, --chapter` | Chapter scope |

---

## `set-chapter-flag` (alias: `scf`)

Override chapter story/non-story classification.

```bash
uv run rsem set-chapter-flag -r <release> -C <N> (--story | --non-story)
```

| Option | Description |
|--------|-------------|
| `--story` | Mark as narrative content |
| `--non-story` | Mark as non-narrative (front-matter, afterword, etc.) |

Requires extracted chapter metadata for creating non-story flags (run `extract` first).
