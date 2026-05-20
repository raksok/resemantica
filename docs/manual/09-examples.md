# 9. Examples

## Basic Usage

### Extract a new release

```bash
rsem extract -i ~/novels/The_Great_Wall.epub -r v1.0
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
rsem translate -r v1.0 -R run1 -C 42
```

### Translate a chapter range

```bash
rsem translate -r v1.0 -R run1 -s 1 -e 50
```

### Translate with batched model order

```bash
rsem translate -r v1.0 -R run1 -s 1 -e 50 --batched
```

## Preprocessing Workflows

### Full glossary pipeline

```bash
rsem preprocess glossary-discover -r v1.0
```
```bash
rsem preprocess glossary-translate -r v1.0
```
```bash
rsem preprocess glossary-review -r v1.0
```
```bash
rsem preprocess glossary-promote -r v1.0 -F artifacts/v1.0/glossary/review.csv
```

### Glossary with custom parameters

```bash
rsem preprocess glossary-discover -r v1.0 \
  -p 0.25 \
  --eval-batch-size 100 \
  --dedup-threshold 0.9
```

### Full idiom pipeline with review

```bash
rsem preprocess idioms -r v1.0
```
```bash
rsem preprocess idiom-review -r v1.0
```
```bash
rsem preprocess idiom-promote -r v1.0 -F artifacts/v1.0/idioms/review.csv
```

## Production Runs

### Full production pipeline

```bash
rsem run production -r v1.0 -R run1
```

### Dry-run to preview stages

```bash
rsem run production -r v1.0 -R run1 -n
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
rsem run production -r v1.0 -R run1 -s 1 -e 100
```

### Force rebuild production

```bash
rsem run production -r v1.0 -R run1 -f
```

## Recovery Workflows

### Resume from last checkpoint

```bash
rsem run resume -r v1.0 -R run1
```

### Resume from specific stage

```bash
rsem run resume -r v1.0 -R run1 --from-stage packets-build
```

### Retry failed units only

```bash
rsem run retry-failed -r v1.0 -R run1
```

### Retry specific failed stage

```bash
rsem run retry-failed -r v1.0 -R run1 --stage translate-range
```

### Preview retries without executing

```bash
rsem run retry-failed -r v1.0 -R run1 -n
```

## Cleanup

### Preview preprocess artifacts that can be deleted

```bash
rsem run cleanup-plan -r v1.0 -R run1 -S preprocess
```

### Delete run artifacts

```bash
rsem run cleanup-apply -r v1.0 -R run1 -S run
```

### Delete everything except extraction

```bash
rsem run cleanup-apply -r v1.0 -R run1 -S all
```

### Factory reset (including config)

```bash
rsem run cleanup-apply -r v1.0 -R run1 -S factory -f
```

## Chapter Classification

### Mark a chapter as story content

```bash
rsem set-chapter-flag -r v1.0 -C 42 --story
```

### Mark a chapter as non-story

```bash
rsem set-chapter-flag -r v1.0 -C 0 --non-story
```

## TUI

### Launch with a release loaded

```bash
rsem tui -r v1.0
```

### Launch with release and run loaded

```bash
rsem tui -r v1.0 -R run1
```

## Using a Custom Config

```bash
rsem translate -c ./my-config.toml -r v1.0 -R run1 -s 1 -e 10
```

## Incremental Workflow (After Initial Production Run)

### Update glossary and re-translate

```bash
rsem preprocess glossary-discover -r v1.0
```
```bash
rsem preprocess glossary-translate -r v1.0
```
```bash
rsem preprocess glossary-promote -r v1.0
```
```bash
rsem packets build -r v1.0 -R run2 -f
```
```bash
rsem translate -r v1.0 -R run2 -s 1 -e 50 -f
```
```bash
rsem rebuild -r v1.0 -R run2
```

### Check TUI observability

```bash
rsem tui -r v1.0 -R run2
```
