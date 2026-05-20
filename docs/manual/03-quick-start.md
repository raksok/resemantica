# 3. Quick Start

This walkthrough takes a Chinese web novel EPUB through the full pipeline.

## Prerequisites

- Resemantica installed (see [Installation](02-installation.md))
- llama.cpp server running with required models
- A source EPUB file

## Step 1: Extract

```bash
rsem extract -i path/to/novel.epub -r v1.0
```

This unpacks the EPUB, validates its structure, generates placeholder maps, and produces a lossless reconstructed EPUB to confirm round-trip fidelity.

Output: `artifacts/releases/v1.0/`

## Step 2: Generate Summaries

```bash
rsem preprocess summaries -r v1.0
```

Creates story-so-far, chapter summaries, and arc summaries in SQLite.

## Step 3: Discover and Promote Glossary

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
rsem preprocess glossary-promote -r v1.0
```
```bash
rsem preprocess glossary-promote -r v1.0 -F artifacts/v1.0/glossary/review.csv
```

## Step 4: Detect Idioms

```bash
rsem preprocess idioms -r v1.0
```

Scans for idiomatic expressions and generates policies.

## Step 5: Build Entity Graph

```bash
rsem preprocess graph -r v1.0
```

Extracts entities, aliases, and relationships. Creates `graph.ladybug`.

## Step 6: Build Continuity

```bash
rsem preprocess continuity -r v1.0
```

Refreshes compact story continuity from graph anchors and summaries.

## Step 7: Build Chapter Packets

```bash
rsem packets build -r v1.0 -R run1
```

Compiles enriched context packets per chapter.

## Step 8: Translate

```bash
rsem translate -r v1.0 -R run1 -C 1
```
```bash
rsem translate -r v1.0 -R run1 -s 1 -e 10
```
```bash
rsem translate -r v1.0 -R run1 -s 1 -e 10 --batched
```

## Step 9: Rebuild EPUB

```bash
rsem rebuild -r v1.0 -R run1
```

Restores placeholders and produces the final translated EPUB at `artifacts/releases/v1.0/rebuild/reconstructed.epub`.

## One-Command Production Run

```bash
rsem run production -r v1.0 -R run1
```

Dry-run first to verify the stage plan:
```bash
rsem run production -r v1.0 -R run1 -n
```
