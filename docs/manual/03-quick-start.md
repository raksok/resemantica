# 3. Quick Start

This walkthrough takes a Chinese web novel EPUB through the full pipeline.

## Prerequisites

- Resemantica installed (see [Installation](02-installation.md))
- llama.cpp server running with required models
- A source EPUB file

## Step 1: Extract

```bash
uv run rsem extract -i path/to/novel.epub -r v1.0
```

This unpacks the EPUB, validates its structure, generates placeholder maps, and produces a lossless reconstructed EPUB to confirm round-trip fidelity.

Output: `artifacts/releases/v1.0/`

## Step 2: Generate Summaries

```bash
uv run rsem preprocess summaries -r v1.0
```

Creates story-so-far, chapter summaries, and arc summaries in SQLite.

## Step 3: Discover and Promote Glossary

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
uv run rsem preprocess glossary-promote -r v1.0
```
```bash
uv run rsem preprocess glossary-promote -r v1.0 -F artifacts/v1.0/glossary/review.csv
```

## Step 4: Detect Idioms

```bash
uv run rsem preprocess idioms -r v1.0
```

Scans for idiomatic expressions and generates policies.

## Step 5: Build Entity Graph

```bash
uv run rsem preprocess graph -r v1.0
```

Extracts entities, aliases, and relationships. Creates `graph.ladybug`.

## Step 6: Build Continuity

```bash
uv run rsem preprocess continuity -r v1.0
```

Refreshes compact story continuity from graph anchors and summaries.

## Step 7: Build Chapter Packets

```bash
uv run rsem packets build -r v1.0 -R run1
```

Compiles enriched context packets per chapter.

## Step 8: Translate

```bash
uv run rsem translate -r v1.0 -R run1 -C 1
```
```bash
uv run rsem translate -r v1.0 -R run1 -s 1 -e 10
```
```bash
uv run rsem translate -r v1.0 -R run1 -s 1 -e 10 --batched
```

## Step 9: Rebuild EPUB

```bash
uv run rsem rebuild -r v1.0 -R run1
```

Restores placeholders and produces the final translated EPUB at `artifacts/releases/v1.0/rebuild/reconstructed.epub`.

## One-Command Production Run

```bash
uv run rsem run production -r v1.0 -R run1
```

Dry-run first to verify the stage plan:
```bash
uv run rsem run production -r v1.0 -R run1 -n
```
