# 9. Examples

## Basic Usage

### Extract a new release

```bash
uv run rsem extract -i ~/novels/The_Great_Wall.epub -r v1.0
```

Output:
```text
status=success
release_root=artifacts/releases/v1.0
rebuilt_epub=artifacts/releases/v1.0/rebuild/reconstructed.epub
validation_report=artifacts/releases/v1.0/extracted/reports/validation.json
```

### Translate a single chapter

```bash
uv run rsem translate -r v1.0 -R run1 -C 42
```

### Translate a chapter range

```bash
uv run rsem translate -r v1.0 -R run1 -s 1 -e 50
```

### Translate with batched model order

```bash
uv run rsem translate -r v1.0 -R run1 -s 1 -e 50 --batched
```

## Preprocessing Workflows

### Full glossary pipeline

```bash
uv run rsem preprocess glossary-discover -r v1.0
```
```bash
uv run rsem preprocess glossary-translate -r v1.0
```
```bash
uv run rsem preprocess glossary-review -r v1.0
```
```bash
uv run rsem preprocess glossary-promote -r v1.0 -F artifacts/v1.0/glossary/review.csv
```

### Glossary with custom parameters

```bash
uv run rsem preprocess glossary-discover -r v1.0 \
  -p 0.25 \
  --eval-batch-size 100 \
  --dedup-threshold 0.9
```

### Full idiom pipeline with review

```bash
uv run rsem preprocess idioms -r v1.0
```
```bash
uv run rsem preprocess idiom-review -r v1.0
```
```bash
uv run rsem preprocess idiom-promote -r v1.0 -F artifacts/v1.0/idioms/review.csv
```

## Production Runs

### Full production pipeline

```bash
uv run rsem run production -r v1.0 -R run1
```

### Dry-run to preview stages

```bash
uv run rsem run production -r v1.0 -R run1 -n
```

Output:
```text
preprocess-summaries
preprocess-glossary
preprocess-idioms
preprocess-graph
preprocess-continuity
packets-build
translate-range
epub-rebuild
```

### Production with chapter range

```bash
uv run rsem run production -r v1.0 -R run1 -s 1 -e 100
```

### Force rebuild production

```bash
uv run rsem run production -r v1.0 -R run1 -f
```

## Recovery Workflows

### Resume from last checkpoint

```bash
uv run rsem run resume -r v1.0 -R run1
```

### Resume from specific stage

```bash
uv run rsem run resume -r v1.0 -R run1 --from-stage packets-build
```

### Retry failed units only

```bash
uv run rsem run retry-failed -r v1.0 -R run1
```

### Retry specific failed stage

```bash
uv run rsem run retry-failed -r v1.0 -R run1 --stage translate-range
```

### Preview retries without executing

```bash
uv run rsem run retry-failed -r v1.0 -R run1 -n
```

## Cleanup

### Preview preprocess artifacts that can be deleted

```bash
uv run rsem run cleanup-plan -r v1.0 -R run1 -S preprocess
```

### Delete run artifacts

```bash
uv run rsem run cleanup-apply -r v1.0 -R run1 -S run
```

### Delete everything except extraction

```bash
uv run rsem run cleanup-apply -r v1.0 -R run1 -S all
```

### Factory reset (including config)

```bash
uv run rsem run cleanup-apply -r v1.0 -R run1 -S factory -f
```

## Chapter Classification

### Mark a chapter as story content

```bash
uv run rsem set-chapter-flag -r v1.0 -C 42 --story
```

### Mark a chapter as non-story

```bash
uv run rsem set-chapter-flag -r v1.0 -C 0 --non-story
```

## TUI

### Launch with a release loaded

```bash
uv run rsem tui -r v1.0
```

### Launch with release and run loaded

```bash
uv run rsem tui -r v1.0 -R run1
```

## Using a Custom Config

```bash
uv run rsem translate -c ./my-config.toml -r v1.0 -R run1 -s 1 -e 10
```

## Incremental Workflow (After Initial Production Run)

### Update glossary and re-translate

```bash
uv run rsem preprocess glossary-discover -r v1.0
```
```bash
uv run rsem preprocess glossary-translate -r v1.0
```
```bash
uv run rsem preprocess glossary-promote -r v1.0
```
```bash
uv run rsem packets build -r v1.0 -R run2 -f
```
```bash
uv run rsem translate -r v1.0 -R run2 -s 1 -e 50 -f
```
```bash
uv run rsem rebuild -r v1.0 -R run2
```

### Check TUI observability

```bash
uv run rsem tui -r v1.0 -R run2
```
