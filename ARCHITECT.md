# Resemantica Architecture

Version: 1.0
Sources: derived from `SPEC.md`; `DECISIONS.md` is the active source of truth for resolved implementation decisions.
Status: implementation-facing architecture baseline

## Purpose

This document translates `SPEC.md` into an engineering blueprint for building Resemantica as a local-first, resumable EPUB translation system. It keeps the architecture concrete, narrow, and staged so the implementation can grow in validated slices without collapsing the pipeline into a single opaque workflow.

## System Intent

Resemantica converts long-form Chinese web novel EPUBs into readable English EPUBs while preserving:

- source-grounded meaning
- chapter structure and XHTML integrity
- canonical terminology
- continuity across chapters
- auditability, resumability, and operator visibility

The system is intentionally a structured pipeline with precomputed memory assets. Runtime translation should stay narrow, chapter-safe, and packet-driven.

## Architectural Drivers

- Local-first execution on Windows 11 consumer hardware
- Sequential execution as the required baseline
- Deterministic preprocessing before translation-time prompting
- Strict separation between authority state and working state
- Artifact-rich workflows for debugging, inspection, and reruns
- Centralized orchestration shared by CLI, TUI, and tracking
- Safe cleanup/reset as a first-class operational capability

## Non-Goals

- Cloud-native service design
- One-shot full-book prompting
- Generic RAG chatbot behavior
- Full semantic world simulation
- Graph-first architecture that replaces glossary or summary authority
- Style-first rewriting that outranks source fidelity

## Core Invariants

- Source Chinese text is the ultimate truth.
- Locked glossary is naming truth.
- Validated Chinese summaries are continuity truth.
- English summaries are derived inspection artifacts, not authority.
- Working state may inform review, but never silently becomes canon.
- Runtime translation consumes packet-derived paragraph bundles instead of heavy live graph retrieval.
- Deterministic matches outrank fuzzy retrieval.
- Model outputs do not write directly into locked authority stores without validation.
- Placeholder preservation and XHTML restoration are first-class constraints.

## System Overview

```text
EPUB Input
  -> EPUB ingest and structured extraction
  -> Preprocessing workflows
     -> glossary authority
     -> summary authority
     -> idiom policy store
     -> graph-backed narrative state
     -> chapter packet builder
  -> Translation workflows
     -> paragraph bundle derivation
     -> Pass 1 draft
     -> Pass 2 fidelity correction
     -> optional Pass 3 readability polish
     -> validation and checkpoints
  -> EPUB reconstruction
  -> Final reports, artifacts, and translated EPUB

Shared across all phases:
  orchestration -> event stream -> CLI / TUI / MLflow
```

## Logical Architecture

### 1. EPUB Layer

Responsibilities:

- unpack EPUBs
- identify chapter documents
- parse XHTML safely
- extract normalized Chinese text
- preserve reversible placeholder and block mappings
- rebuild valid EPUB outputs
- emit extraction and validation artifacts

Key rule:

Only deterministic code should own XHTML parsing, placeholder mapping, restoration, and final packaging.

### 2. Glossary Layer

Responsibilities:

- candidate discovery from source chapters
- candidate English translation
- deterministic normalization and conflict checks
- promotion into locked glossary
- exact term lookup at translation time

Authority boundary:

SQLite is the glossary authority store. Graph data may reference glossary entities, but it does not replace glossary truth.

### 3. Summary Layer

Responsibilities:

- produce structured Chinese summaries
- validate Chinese continuity artifacts
- derive English summaries from validated Chinese plus locked glossary
- maintain chapter, previous-3, story-so-far, and arc continuity layers

Authority boundary:

Chinese summaries are authoritative. English summaries remain derived inspection assets.

### 4. Idiom Layer

Responsibilities:

- detect idioms and set phrases
- capture meaning and preferred rendering policy
- store reusable idiom records for packet assembly and paragraph matching

Authority boundary:

Idioms live as versioned structured assets outside the graph as their primary authority store.

### 5. Graph Layer

Responsibilities:

- store entities, aliases, appearances, and relationships in LadybugDB
- support alias resolution and relationship continuity
- enforce reveal-safe, chapter-safe filtering
- contribute compact narrative context to chapter packets

Scope boundary:

The graph is a translation-support world model, not a universal lore engine.

### 6. Packet Layer

Responsibilities:

- build one reproducible chapter packet per chapter
- assemble paragraph bundles from packet content plus deterministic retrieval rules
- carry version hashes needed for invalidation and reproducibility

Design rule:

Packets are runtime-ready memory containers. Paragraph bundles are the only context the translation passes should need in normal operation.

### 7. Translation Layer

Responsibilities:

- run the three-pass chapter workflow
- preserve structure placeholders
- inject only filtered local context
- classify paragraph risk
- validate structural and semantic outcomes
- checkpoint frequently for resume safety

Pass split:

- Pass 1 creates a conservative source-faithful draft with glossary constraints.
- Pass 2 repairs fidelity issues against the source.
- Pass 3 improves readability without changing facts, named terms, or event order.

### 8. Orchestration Layer

Responsibilities:

- own workflow state and stage transitions
- coordinate retries, resegmentation, and resume behavior
- emit structured events
- register artifacts and run metadata
- expose production and reset workflows
- act as the shared execution core for CLI and TUI

Design rule:

Operational workflows belong here, not inside scattered scripts or duplicated UI logic.

### 9. Tracking and Operator Experience

Responsibilities:

- record metrics, parameters, and artifacts in MLflow
- provide progress and warnings without requiring MLflow UI access
- power CLI verbose output and the Textual TUI from the same event stream

## Primary Data Flow

### Phase 0: Preprocessing

Flow:

1. EPUB ingest extracts stable chapter and block artifacts.
2. Glossary workflow builds candidates, translations, validations, and locked entries.
3. Summary workflow builds validated Chinese summaries and derived English summaries.
4. Idiom workflow builds reusable idiom policy records.
5. Graph workflow builds chapter-safe entity and relationship state after glossary and summary foundations exist.
6. Packet builder produces one reproducible chapter packet per chapter.

Outputs:

- locked glossary
- validated Chinese summaries
- derived English summaries
- idiom policies
- graph-backed narrative state
- embedding index for fuzzy support
- chapter packets
- paragraph bundle derivation rules

### Phase 1: Translation

Flow:

1. Load chapter packet.
2. Derive a paragraph bundle for the current block.
3. Run Pass 1 with narrow context and structure constraints.
4. Restore and validate structural output.
5. Run Pass 2 for semantic correction.
6. Run a fidelity gate.
7. Optionally run Pass 3 for readability.
8. Run chapter checks and commit checkpoints.

Outputs:

- raw and corrected paragraph/chapter artifacts
- validation reports
- retries and warning traces
- resumable checkpoint state

### Phase 2: EPUB Reconstruction

Flow:

1. Restore translated XHTML into original structure positions.
2. Validate XHTML and block mapping integrity.
3. Rebuild the EPUB package.
4. Emit output reports and final translated EPUB.

### Phase 3: Operations and Control

Flow:

1. Select source input and run or release context.
2. Determine whether preprocessing artifacts are valid or stale.
3. Run translation for a chapter, range, or full production job.
4. Expose progress, warnings, and artifacts through CLI, TUI, and MLflow.
5. Support scoped cleanup and safe restart workflows.

## State Model

### Authority State

- locked glossary
- validated Chinese chapter summaries
- validated Chinese story-so-far summaries
- arc summaries
- confirmed idiom policies
- confirmed graph relationship state
- validated packet builds
- approved config and schema versions

### Working State

- glossary candidates
- provisional English term candidates
- unresolved alias clusters
- provisional graph relationships
- draft summaries
- fuzzy retrieval hits
- reranked candidates
- paragraph risk scores
- retry traces
- temporary packet candidates

### Architectural Rule

Every promotion from working state to authority state must pass deterministic validation. The architecture should make silent promotion difficult by design.

## Retrieval Arbitration

Translation-time retrieval follows this precedence:

1. locked glossary exact match
2. explicit alias match
3. deterministic idiom match
4. chapter-safe graph match
5. validated chapter-local packet memory
6. embedding-based fuzzy retrieval
7. reranked fallback candidates

Conflict policy:

Lower-priority retrieval may enrich context, but it must not override higher-priority authority.

## Storage Architecture

### SQLite

Stores:

- glossary candidates and locked glossary
- summaries and idioms
- checkpoints and translation cache
- packet metadata and run metadata
- cleanup bookkeeping

Why:

SQLite is the authoritative structured store for local, inspectable, transactional project state.

### LadybugDB

Stores:

- entities
- aliases
- appearances
- relationships
- chapter and arc graph links
- lightweight world-model structure

Why:

LadybugDB provides graph-native relationship storage and chapter-safe subgraph support for packet assembly.

### JSON Artifacts

Stores:

- chapter packets
- paragraph bundles
- validation reports
- event traces
- cleanup plans and reports

Why:

These are portable, inspectable runtime and operational artifacts.

### Filesystem Artifacts

Stores:

- intermediate XHTML outputs
- logs
- reports
- final EPUB outputs
- regression and golden-set assets

## Module Layout

Target package layout:

```text
src/resemantica/
  cli.py
  settings.py
  logging_config.py
  config/
  db/
  epub/
  glossary/
  summaries/
  idioms/
  graph/
  packets/
  llm/
  translation/
  orchestration/
  tracking/
  tui/
  utils/
```

Module responsibility should stay narrow. Avoid combining preprocessing authority builders, translation passes, UI logic, and orchestration behavior inside the same module.

## Orchestration Blueprint

The orchestration layer should expose four workflow families:

- `preprocess`: builds reusable authority and packet artifacts
- `translate`: runs chapter translation with retries, checkpoints, and validation
- `run-production`: executes the full operator-facing path from input selection through final EPUB output
- `reset`: previews and executes scoped cleanup safely

Shared orchestration services should include:

- workflow state machine
- checkpoint manager
- event bus
- artifact registry
- retry and resegmentation policy
- cleanup planner
- run and release metadata tracking

## Event and UI Model

The event stream is the shared visibility contract for the system. Meaningful actions should emit structured events such as:

- stage started and completed
- chapter started and completed
- paragraph retry
- packet assembled
- validation failed
- artifact written
- warning emitted
- cleanup candidate detected
- run finalized

Presentation layers should consume this shared stream:

- CLI for direct commands and `--verbose` progress
- Textual TUI for dashboards, inspection, and control surfaces
- MLflow for run comparison, artifacts, metrics, and dashboards

The TUI is a presentation layer over orchestration services. It must not implement an alternate execution model.

## Validation and Failure Strategy

Validation is layered:

- structural validation for placeholders, restoration, block mapping, and XHTML integrity
- semantic validation for hallucinations, omissions, term consistency, ambiguity preservation, and event order
- memory-integrity validation for glossary conflicts, chapter-unsafe context, stale packets, and invalid authority promotion

Failure handling should remain bounded and resumable:

- retry once with stricter settings
- resegment unstable paragraphs when needed
- mark persistent failures for review and continue where safe
- persist checkpoints at chapter, paragraph, and pass granularity

## Security and Safety Posture

For this architecture, "safety" is mostly about data integrity and controlled mutation:

- deterministic code owns source extraction and restoration
- authority stores are protected behind validation boundaries
- chapter-safe filtering prevents future-knowledge leaks
- cleanup is explicit, scoped, previewable, and release-aware
- destructive operations default to preserving inputs, config, prompts, and manual overrides

## Recommended Build Order

Implementation should follow the validated slices already implied by the spec:

1. EPUB round-trip MVP
2. single-chapter translation MVP with Pass 1 and Pass 2
3. canonical glossary system
4. summary memory
5. idiom workflow
6. graph MVP foundation with LadybugDB as the graph store
7. lightweight world model
8. chapter packets with graph integration
9. full three-pass translation with stronger risk handling
10. centralized orchestration and production workflow
11. reset and cleanup workflow
12. unified Textual TUI
13. observability, evaluation, and dashboards
14. batch pilot and final rebuild

This order preserves the main architectural constraint: expensive memory construction happens offline before runtime translation becomes richer.

## Implementation Guidance for Agents

- Build the smallest validated vertical slice first.
- Keep authority builders separate from runtime consumers.
- Treat packets as reproducible products, not ad hoc dictionaries.
- Keep pass responsibilities narrow and non-overlapping.
- Preserve resumability whenever adding a new stage.
- Emit artifacts and events as part of the feature, not as later polish.
- Do not bypass exact glossary and alias rules with fuzzy retrieval.
- Do not duplicate orchestration behavior inside the CLI or TUI.

## Definition of Architectural Success

The architecture is successful when the system can:

1. unpack and validate EPUB input safely
2. build stable authority memory and packet artifacts offline
3. translate chapters with narrow, chapter-safe paragraph context
4. validate structure, fidelity, and terminology consistently
5. checkpoint and resume without rerunning completed work
6. expose production workflow, visibility, and cleanup through one orchestration core
7. rebuild a valid translated EPUB with enough artifacts to debug failures later
