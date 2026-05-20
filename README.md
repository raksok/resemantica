# Resemantica

> Local-first EPUB translation pipeline for Chinese web novels

All inference runs locally via `llama.cpp` router mode. No cloud services.

Full manual: `docs/manual/00-index.md` · Man page: `docs/rsem.1.md`

## Quick Start

```bash
# Extract a release
rsem extract -i novel.epub -r v1.0

# Full production pipeline — dry-run first, then execute
rsem run production -r v1.0 -R run1 -n
rsem run production -r v1.0 -R run1
```

## Features

- **Local-first** — all LLM inference via llama.cpp, no cloud dependency
- **3-pass translation** — source-faithful draft → fidelity correction → optional readability polish
- **Glossary system** — deterministic term extraction, translation voting, human review workflow
- **Entity-relationship graph** — LadybugDB-backed world model with chapter-safe spoiler filters
- **Resumable** — every stage writes durable checkpoints; interrupts pick up where they left off
- **CLI + TUI** — terminal interface and interactive Textual dashboard

## Installation

Requires Python >= 3.13 and a running llama.cpp server.

```bash
git clone <repo-url> && cd resemantica
uv venv && source .venv/bin/activate
uv sync
```

Define models in a `.ini` file and start llama.cpp in router mode:

```bash
llama-server --models-preset models.ini --port 8080
```

First run auto-downloads **BAAI/bge-m3** (embedding model) and **HanLP** (~500MB for Chinese tokenization/POS/NER).

## Pipeline Stages

Executed in this canonical order by `rsem run production`:

| # | Stage | What it does |
|---|-------|-------------|
| 1 | `extract` | Unpack EPUB, validate structure, round-trip rebuild |
| 2 | `preprocess` | Summaries → glossary → idioms → entity graph → continuity |
| 3 | `packets` | Build immutable chapter packets with enriched LLM context |
| 4 | `translate` | Pass 1 (translator) + Pass 2 (analyst) + optional Pass 3 (polish) |
| 5 | `rebuild` | Restore placeholders, reconstruct final EPUB |

## Key Documentation

| Resource | Path |
|----------|------|
| Man page | `docs/rsem.1.md` |
| Full manual | `docs/manual/00-index.md` |
| Architecture | `docs/10-architecture/` |
| Specification | `SPEC.md` |
| Design decisions | `DECISIONS.md` |
| Data contracts | `DATA_CONTRACT.md` |
| Implementation plan | `IMPLEMENTATION_PLAN.md` |

## Entry Points

- `rsem <command>` — primary CLI
- `python -m resemantica <command>` — alternative
- `python -m resemantica.cli <command>` — direct module
