# 1. Introduction

Resemantica is a **local-first, multi-stage pipeline** that converts Chinese web novel EPUBs into readable English EPUBs. All inference runs locally via `llama.cpp` in router mode (OpenAI-compatible API). No cloud services required.

## Key Concepts

### Pipeline Phases

The system is organized into 4 phases:

| Phase | Name | Description |
|-------|------|-------------|
| 0 | Preprocessing | Build reusable memory assets offline: glossary, summaries, idioms, entity-relationship graph, chapter packets |
| 1 | Translation | Translate chapter-by-chapter using a controlled 3-pass workflow |
| 2 | EPUB Reconstruction | Restore translated XHTML into valid EPUB format |
| 3 | Operations | Centralized orchestration with event streaming, progress, resumability, cleanup |

### Three-Pass Translation

Each chapter goes through up to 3 LLM passes:

- **Pass 1** (translator model) — Source-faithful English draft. Preserves all placeholders and structural elements. Uses glossary, idioms, summaries, and graph context via chapter packets.
- **Pass 2** (analyst model) — Structured fidelity correction. Reviews the draft against the source text, correcting omissions, terminology violations, and mistranslations.
- **Pass 3** (analyst model, optional) — Readability polish. Improves flow and naturalness for high-risk paragraphs without altering meaning.

### Chapter Packet System

Each chapter is compiled into a **ChapterPacket** — an immutable artifact containing:
- Chapter source text with block segmentation
- Glossary subset (terms appearing in this chapter)
- Summary context (story-so-far, chapter summary, arc summary)
- Idiom matches with policy renderings
- Graph context (entity anchors relevant to this chapter)

Packets are built after all preprocessing completes and are invalidated when upstream hashes change.

### Text Segmentation & Splitting

During extraction, XHTML content is split into blocks and segments (`epub/parser.py`):

1. **Block detection** — Leaf block elements are identified (p, h1-h6, div, li, td) that are NOT parents of other block elements.
2. **Placeholder extraction** — Structural elements (images, links, ruby, MathML) are replaced with placeholders.
3. **Sentence splitting** — Pure text is split at sentence boundaries using regex `[^。！？!?\.]+[。！？!?\.]?`, with a max of 1500 characters per segment.
4. **Overflow handling** — If a segment still exceeds `max_paragraph_chars`, it is character-split at the boundary. Blocks that split get `seg01`, `seg02` suffixes.

### Token Counting

The system uses `tiktoken` with the `cl100k_base` encoding (the encoding used by GPT-4). Token counts are lazily cached via `@lru_cache`. A 5% safety buffer (`* 1.05`) is applied at the packet layer (`packets/bundler.py`, `packets/builder.py`) to ensure prompts stay within the context window.

### Prompt System

Prompts are stored as `.txt` files in `src/resemantica/llm/prompts/` (18 files). Each file uses:
- **First line**: `# version: <VERSION>` (mandatory version identifier)
- **Body**: Python `.format()`-style placeholders like `{GLOSSARY}`, `{SOURCE_TEXT}`, `{CHAPTER_CONTENT}`

Entry points are handled by `load_prompt(name)` which reads the file and returns a `PromptTemplate(name, version, template)`, and `render_named_sections(template, sections)` which fills placeholders.

### Event Granularity

The event bus classifies events into 5 granularity levels:

| Level | Name | Example Events |
|-------|------|----------------|
| 0 | ERROR | `severity=error` only |
| 1 | STAGE | `.started`, `.completed`, `.failed` |
| 2 | CHAPTER | `.chapter_started`, `.chapter_completed` |
| 3 | PARAGRAPH | `.paragraph_started`, `.paragraph_completed` |
| 4 | TOKEN | `.retry`, `.risk_detected`, `.entity_extracted` |

The `[events]` `persistence_mode` controls storage:
- `"normal"`: persist everything
- `"reduced"`: persist only critical events (warnings, errors, failures, stops) and sample progress events every `progress_sample_every` (default 25)

### LLM Roles

Three distinct model roles:

| Role | Default model | Purpose |
|------|--------------|---------|
| `translator` | HY-MT1.5-7B | Pass 1 translation, glossary candidate translation |
| `analyst` | Qwen3.5-9B-GLM5.1 | Pass 2 correction, Pass 3 polish, summaries, idioms, entity extraction |
| `embedding` | BAAI/bge-m3 | Fuzzy alias/epithet matching via embedding similarity |

Models are configured in `resemantica.toml` under `[models]`. The system uses llama.cpp router mode — any model available through the OpenAI-compatible endpoint can be used.

### Storage Architecture

Three storage layers:

1. **SQLite** (`resemantica.db`) — Glossary, summaries, idioms, checkpoints, packet metadata
2. **LadybugDB** (`graph.ladybug`) — Entities, aliases, appearances, relationships, world model
3. **Filesystem** — Chapter packets, paragraph bundles, validation reports, final EPUB

### Design Principles

- **Source-text authority** — The original Chinese text is never modified; all translations are stored as parallel artifacts.
- **Glossary-based naming** — All proper noun translations are determined by the locked glossary. No ad-hoc name translation during inference.
- **Deterministic preprocessing** — All memory building runs before any LLM prompting. No interleaving.
- **Chapter-safe filtering** — Entity graph context is filtered per-chapter to prevent spoilers.
- **Resumable execution** — Every stage writes durable checkpoints. Interruptions resume from the last checkpoint.
