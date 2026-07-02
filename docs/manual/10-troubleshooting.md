# 10. Troubleshooting

## Common Issues

### "Connection refused" when running commands

**Cause:** llama.cpp server is not running or not reachable.

**Check:**
1. Verify llama.cpp is running: `curl http://127.0.0.1:8080/v1/models`
2. Check `base_url` in `resemantica.toml` `[llm]` section
3. Ensure port and host match between server and config

**Fix:** Start or restart llama.cpp server with the correct port.

### "Model not found" errors

**Cause:** The model name in `[models]` does not match what llama.cpp has loaded.

**Fix:** Update `translator_name`, `analyst_name`, or `embedding_name` in config to match model filenames loaded in the llama.cpp router.

### "No candidates found" from glossary-discover

**Cause:** Pruning threshold too high, or no new terms beyond the locked glossary.

**Try:** Lower `pruning_threshold` (e.g., `-p 0.1`) or check that extraction succeeded.

### Translation produces garbled or empty output

**Cause:** Context window too small for chapter length, or model not suitable for translation.

**Try:**
1. Increase `context_window` in `[llm]`
2. Increase `max_context_per_pass` in `[budget]`
3. Try a different translator model

### `preprocess-continuity` fails with `SUMMARY_EN_DERIVE` context overflow

**Cause:** Older runs may have built English summary derivation prompts with the
full locked glossary. `summary_en_derive.txt` version `1.1` renders only
source-local locked glossary entries and checks prompt budget before the
translator LLM call.

**Fix:** Rerun the same continuity command after updating. If stale English
derived rows already exist and need regeneration, rerun the affected scope with
`--force`.

### `preprocess-continuity` fails after empty graph continuity output

**Cause:** A previous analyst model call may have returned empty or malformed
`SUMMARY_GRAPH_CONTINUITY_UPDATE` output. Current runs retry fresh invalid
graph-continuity output before failing. Older runs could save invalid raw output
to the LLM cache, causing repeat failures on rerun.

**Fix:** Rerun the same continuity command without `--force`. The stage validates
cached graph continuity output before accepting it; empty, malformed, over-budget,
or otherwise invalid cached output is treated as stale and regenerated. Fresh
invalid attempts are retried, but invalid output is never written back to the
cache. In batch-order continuity, rerun resumes from the failed chunk boundary
and backfills missing English rows and artifacts from any current Chinese graph
compact rows.

### `preprocess-continuity` fails with graph-compact prompt budget exceeded

**Cause:** Older continuity code rendered the full chapter-safe graph into each
`SUMMARY_GRAPH_CONTINUITY_UPDATE` prompt. Late in a long release, the safe graph
can grow to thousands of entities and relationships and exceed the analyst
prompt budget before any model call.

**Fix:** Update to the bounded-anchor continuity code and rerun the same command
without `--force`. Completed chunks remain resumable from their checkpoints; the
failed chunk rebuilds with current/recent graph anchors while the full raw graph
still drives continuity staleness detection. Raising analyst context limits can
temporarily defer the failure, but it does not solve ongoing graph growth.

### `packets-build` or translation fails with prompt budget exceeded

**Cause:** Packet or bundle context grew beyond the configured prompt budget.
Current packet builds bound graph and glossary context before writing packet
artifacts, compact and trim paragraph bundle rows before writing bundle
artifacts, honor `[packets].budget_tokens` and `[packets].max_bundle_bytes`,
and translation passes check rendered prompts before model calls. The legacy
`[budget].max_bundle_bytes` value does not control packet bundles after the
packet-specific config split.

**Fix:** Rerun `packets build` for the affected release so old packet artifacts
rebuild with the current packet builder version. Glossary-heavy chapters should
now bound and trim `chapter_glossary_subset`, and bundle-heavy blocks should
write trimmed bundles instead of `bundle_skip` warnings from
`bundle_budget_exceeded`. Then rerun translation without `--force` unless you
intentionally want to bypass successful checkpoints. If the failure persists,
lower packet context pressure with `[packets].budget_tokens`, raise
`[packets].max_bundle_bytes` only if larger paragraph context is acceptable, or
review unusually large glossary, idiom, or continuity rows for the affected
chapter.

### Pipeline stuck or very slow

**Cause:** Single-model concurrency (default: 1).

**Try:**
1. Increase `max_concurrent_requests_per_model` in `[llm]`
2. Increase `pass2_concurrency` in `[translation]`
3. Break the chapter range into smaller batches

### Qwen overloads when multiple Qwen model IDs are configured

**Cause:** Different configured Qwen names can still route to the same local backend. Without a throttle group, exact model names use independent semaphores and may issue concurrent requests to that shared backend.

**Fix:** Put those exact model IDs in one `[llm.throttle_groups.<name>]` table:

```toml
[llm.throttle_groups.qwen]
model_names = [
  "Qwen3.5-9B-GLM5.1",
  "Qwen3.5-9B-NonThinking-unsloth",
  "Qwopus3.5-9B",
  "Crow3.5-9B",
]
max_concurrent_requests = 1
system_prompt = "You are Qwen, created by Alibaba Cloud. You are a helpful assistant."
```

This serializes those Qwen and Qwen-family fork calls inside one process while leaving unrelated model IDs on their own per-model limits. The system prompt is sent as a fresh `system` message for every matching grouped request.

Existing malformed Qwen glossary votes are already persisted. Regenerate them with `--force` or delete the targeted vote rows before rerunning glossary translation.

### Glossary votes remain unresolved

**Cause:** Configured translator models did not produce a deterministic majority,
or the disagreement is a style-policy split that the resolver intentionally
leaves for human review.

**Try:**
1. Re-run the no-LLM resolver if deterministic rules changed: `uv run rsem preprocess glossary-resolve -r <release> -R glossary-translate`
2. Add auditable filler votes for only unresolved candidates: `uv run rsem preprocess glossary-fill -r <release> -R glossary-translate --model <filler-model>`
3. Regenerate review files: `uv run rsem preprocess glossary-review -r <release>`

`glossary-fill` does not run full glossary translation and does not directly
override canonical translations. If Tao/Dao-style policy disagreements remain
unresolved, edit the review file and promote with `glossary-promote -F`.

If the disagreement should be handled like a first human picker pass, run
`glossary-fill --pick-existing`. Picker mode only accepts an existing vote
alternative; invented output is rejected and the candidate remains unresolved.
Configured `glossary.resolution_alias_families` can collapse project-specific
variants such as English names versus pinyin before saving the preferred display
term.

Long `glossary-fill` runs emit sampled DEBUG records before filler model calls.
The records identify the release, run, model, candidate, source term, chapter,
candidate index, and candidate count. They do not include prompt text or model
output. JSONL logs capture DEBUG by default, but the records are sampled using
`events.progress_sample_every` to avoid one JSONL row per candidate; console
DEBUG output requires `-vvv` or higher.

### Idiom rendering votes remain unresolved

**Cause:** Idiom renderings did not reach a deterministic majority. Meaning-only
disagreements do not block idiom promotion, but unresolved renderings do.

**Try:**
1. Re-run the no-LLM resolver if deterministic rules changed: `uv run rsem preprocess idiom-resolve -r <release> -R idioms`
2. Add auditable filler rendering votes for only unresolved rendering candidates: `uv run rsem preprocess idiom-fill -r <release> -R idioms --model <filler-model>`
3. Regenerate review files: `uv run rsem preprocess idiom-review -r <release>`

`idiom-fill` does not run full idiom translation and does not generate meaning
votes. It writes normal `idiom_translation_votes` rows with
`vote_kind = "rendering"`, then reuses deterministic resolution with filler
models appended after the configured preprocess translators.

### Locked glossary still rejects shared English targets

**Cause:** The release database was created before `locked_glossary` became
source-term unique only. Deleting rows from `locked_glossary` is not enough,
because SQLite keeps the old target-term unique index in the table schema.

**Fix:** Repair the release DB schema, then rerun resolve and promote from the
existing candidates and votes. This avoids rerunning glossary discovery:

```bash
uv run python scripts/repair_locked_glossary_schema.py --release <release> --dry-run
```
```bash
uv run python scripts/repair_locked_glossary_schema.py --release <release> --apply
```
```bash
uv run rsem preprocess glossary-resolve -r <release> -R glossary-translate
```
```bash
uv run rsem preprocess glossary-promote -r <release> --force
```

The helper creates a timestamped copy of `resemantica.db` before applying by
default. It rebuilds only `locked_glossary`, preserves existing locked rows,
clears stale `glossary_conflicts` for the selected release, and resets
translated `promoted`/`conflict` candidates back to `translated` so promotion
can regenerate conflict state under the new rules.

If you are promoting from a reviewed file, run the same repair first and then
promote with the review file:

```bash
uv run rsem preprocess glossary-promote -r <release> -F artifacts/releases/<release>/glossary/review.csv --force
```

### Glossary discovery appears stuck after chapters finish

**Cause:** Corpus scoring can be CPU-heavy on large candidate sets. This happens after
`preprocess-glossary.discover.chapter_completed` events and before
`preprocess-glossary.discover.filter.completed` (legacy:
`preprocess-glossary.discover.filter_completed`).

**Check:** Look for `preprocess-glossary.discover.scoring.progress` events or messages like
`Scoring glossary candidates: c_value 4200/18000`. If those counts are moving, the run is slow
rather than stuck.

### Glossary translation fails after a local model crash

**Cause:** The external llama.cpp model server can exit or drop the request during one model's glossary vote batch. Resemantica emits `preprocess-glossary.translate.failed`, but votes saved before the crash remain in SQLite.

**Fix:** Restart the model server and rerun the same command with the same `-r`, same `-R`, and same config, without `--force`. Existing per-model votes are skipped and the interrupted model continues from its first missing vote. When a complete seed model vote set exists, resume avoids a full candidate-table scan and loads candidate rows later by `candidate_id` primary key. Change the configured model list only when intentionally abandoning the crashing model.

### Graph extraction appears stuck

**Cause:** Graph extraction can spend a long time in chapter LLM calls or in merge/validation after drafts have been loaded.

**Check:** Look for `preprocess-graph.extract.progress` events or console messages like `Graph extract 12/80 chapter=12: entities=4, relationships=2`. The resume summary also reports reusable, stale, and missing draft counts before chapter work starts.

### Graph extraction fails after a local model crash

**Fix:** Restart the model server and rerun the same graph command with the same `-r` and `-R`, without `--force`. Fresh per-chapter drafts are reused; only missing or stale drafts are regenerated. `run retry-failed --stage preprocess-graph` detects stale drafts by chapter source hash and graph prompt version.

### Graph extraction rebuilds drafts after updating

**Cause:** `graph_extract.txt` prompt version `2.4` makes older graph extraction drafts stale once. This is expected because graph draft and LLM cache identities are prompt-version keyed.

**Fix:** Rerun the same graph command. Fresh `2.4` drafts are written and reused on later runs unless the chapter source hash or graph prompt version changes again.

### Checkpoint mismatch after config change

**Cause:** Changing `--run` or config creates a new checkpoint namespace.

**Fix:** Use `--force` to rebuild, or run with a new `--run` identifier.

## Logs

### Locations

```text
artifacts/releases/<release_id>/logs/
├── <run_id>.jsonl            # Structured JSON log
└── tui.jsonl                 # TUI session log (if launched)
```

### Verbosity levels

| `-v` count | Log level | Console format |
|------------|-----------|----------------|
| (none) | WARNING | `HH:mm:ss \| LEVEL \| message` |
| `-v` | INFO | `HH:mm:ss \| LEVEL \| name \| message` |
| `-vv` | DEBUG | `HH:mm:ss.SSS \| LEVEL \| name \| message` (CLI progress) |
| `-vvv` | DEBUG | `HH:mm:ss.SSS \| LEVEL \| name:function:line \| message` (full) |
| `-vvvv` | TRACE | Same format as `-vvv`, all events |

### Stderr Replacement

When running via CLI progress (most commands), the stderr handler is temporarily hijacked to power the interactive progress display. Log messages still appear in the JSONL file and the progress log panel, but may not appear directly on stderr. Running with `--verbose` or checking `logs/<run_id>.jsonl` is recommended for troubleshooting.

## Recovery Procedures

### After an interrupted run

```bash
uv run rsem run retry-failed -r v1.0 -R run1 -n
```
```bash
uv run rsem run resume -r v1.0 -R run1
```
```bash
uv run rsem run retry-failed -r v1.0 -R run1 --stage translate-range
```

### After partial data corruption

```bash
uv run rsem run cleanup-plan -r v1.0 -R run1 -S translation
```
```bash
uv run rsem run cleanup-apply -r v1.0 -R run1 -S translation
```
```bash
uv run rsem translate -r v1.0 -R run1 -s 1 -e 50 -f
```

### Factory reset a release

```bash
uv run rsem run cleanup-apply -r v1.0 -R run1 -S factory -f
```
```bash
uv run rsem extract -i novel.epub -r v1.0
```

## Getting Help

- Man page: `docs/uv run rsem.1.md`
- Full manual: `docs/manual/00-index.md`
- Architecture: `docs/10-architecture/`
- Design decisions: `docs/DECISIONS.md`
- Task briefs: `docs/40-tasks/`
