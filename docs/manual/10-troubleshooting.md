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

### Pipeline stuck or very slow

**Cause:** Single-model concurrency (default: 1).

**Try:**
1. Increase `max_concurrent_requests_per_model` in `[llm]`
2. Increase `pass2_concurrency` in `[translation]`
3. Break the chapter range into smaller batches

### Glossary discovery appears stuck after chapters finish

**Cause:** Corpus scoring can be CPU-heavy on large candidate sets. This happens after
`preprocess-glossary.discover.chapter_completed` events and before
`preprocess-glossary.discover.filter_completed`.

**Check:** Look for `preprocess-glossary.discover.scoring.progress` events or messages like
`Scoring glossary candidates: c_value 4200/18000`. If those counts are moving, the run is slow
rather than stuck.

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
