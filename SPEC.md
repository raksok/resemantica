# Resemantica — SPEC.md
Version: 1.0
Status: Consolidated target spec
Scope: Unified project spec replacing the older baseline + upgrade-plan split
Decision authority: `DECISIONS.md` resolves implementation-level conflicts.

---

## 1. Overview

**Resemantica** is a local-first pipeline for translating long-form Chinese web novel EPUBs into readable English EPUBs while preserving structure, semantic fidelity, continuity, and auditability.

The system must:

1. unpack and validate a source EPUB
2. preprocess the novel into stable translation memory
3. compile chapter-level context packets
4. translate chapter by chapter using controlled multi-pass generation
5. rebuild a final translated EPUB
6. support resumability, validation, inspection, cleanup, and operator-visible progress at every major stage

This system is intentionally designed as a **structured pipeline**, not a single end-to-end prompt. Expensive memory construction happens offline. Translation-time behavior must remain narrow, filtered, and source-grounded.

---

## 2. Core goals

### 2.1 Primary goals

- Translate a long Chinese EPUB novel into English
- Preserve reader-visible structure and essential metadata
- Maintain consistency across names, titles, factions, techniques, idioms, and relationships
- Keep runtime translation deterministic and auditable
- Run fully locally on consumer hardware
- Be implementable in validated stages by coding agents
- Provide a centralized production workflow rather than scattered manual invocations
- Provide an operator-facing console with visible progress and inspection
- Support clean reset / cleanup so a user can start fresh safely

### 2.2 Non-goals

- Not a cloud service
- Not a generic RAG chatbot
- Not an autonomous agent that invents its own architecture
- Not a one-shot full-novel translation script
- Not a graph-only memory system
- Not a style-first literary rewriting engine
- Not a full semantic world simulator
- Not a full lore ontology

---

## 3. Source of truth and state model

### 3.1 Source-of-truth hierarchy

- **Source Chinese text** = ultimate ground truth
- **Locked glossary** = naming truth
- **Validated Chinese summaries** = continuity truth
- **English summaries** = derived inspection layer
- **Idiom policy store** = approved idiom rendering policy
- **LadybugDB graph** = structured entity / relationship / chapter-safe narrative state for packet assembly
- **Chapter packet JSON** = runtime chapter memory snapshot
- **Paragraph bundle JSON** = runtime prompt context

### 3.2 Authority state

Authority state includes:

- locked glossary
- validated Chinese chapter summaries
- validated Chinese story-so-far summaries
- validated arc summaries
- confirmed idiom policies
- confirmed graph relationship states
- validated packet builds
- approved config / schema versions

### 3.3 Working state

Working state includes:

- glossary candidates
- provisional translated glossary candidates
- unresolved alias clusters
- provisional graph relationships
- draft summaries
- fuzzy retrieval hits
- reranked context candidates
- paragraph risk scores
- retry traces
- temporary packet assembly candidates

### 3.4 Rule

Working state may guide validation or review but must not be silently treated as truth.

---

## 4. Core design rules

1. **Source text is the ground truth.**
2. **Glossary authority and summary authority are separate.**
3. **Chinese continuity memory is authoritative; English continuity memory is derived.**
4. **Precompute memory offline; do not rebuild heavy context at paragraph runtime.**
5. **Pass responsibilities must stay narrow.**
6. **Translation-time prompts must receive filtered local context, not broad full-chapter context.**
7. **All major steps must emit inspectable artifacts.**
8. **The system must be resumable at chapter, paragraph, and pass granularity.**
9. **Model output must never write directly into locked canonical memory without validation.**
10. **Structure preservation is a first-class requirement, not post-processing glue.**
11. **Chapter-safe filtering applies to all runtime memory, not only graph edges.**
12. **Deterministic rules outrank fuzzy retrieval and reranking.**
13. **Runtime translation should consume packet-derived context instead of heavy live graph queries.**
14. **Operational workflows belong to a centralized orchestration layer.**
15. **The operator must be able to see what the system is doing without opening MLflow manually.**
16. **Cleanup/reset is a first-class workflow owned by orchestration.**
17. **The TUI is an operator console on top of the orchestration/event system, not a separate execution model.**

---

## 5. Hardware and software assumptions

### 5.1 Target environment

- Windows 11
- AMD GPU
- local inference via `llama.cpp`
- default backend: Vulkan
- sequential execution is the required baseline

### 5.2 Model roles

- **`translator_name`** = translation model, used for glossary candidate translation and Pass 1 chapter translation
- **`analyst_name`** = preprocessing / analysis / editing model for discovery, extraction, summaries, idioms, relationship mining, Pass 2, and Pass 3
- **`embedding_name`** = embedding model for fuzzy alias and epithet support only

### 5.3 Core stack

- `llama.cpp` for local inference (router mode with OpenAI-compatible API)
- SQLite for structured storage, checkpoints, cache, glossary, summaries, and packet metadata
- LadybugDB for graph-backed entity and relationship memory
- MLflow for observability, artifacts, metrics, evaluation, and run comparison
- ebooklib + BeautifulSoup + lxml for EPUB/XHTML handling
- Textual for the unified operator TUI
- loguru for logs

---

## 6. System phases

### Phase 0 — Preprocessing
Build reusable memory assets and one reproducible chapter packet per chapter.

### Phase 1 — Translation
Translate each chapter with a controlled multi-pass workflow.

### Phase 2 — EPUB reconstruction
Restore translated XHTML into a valid EPUB and validate output.

### Phase 3 — Operations and control
Run the system through a centralized orchestration layer with event streaming, progress visibility, resumability, repair/rerun controls, cleanup/reset workflows, and a unified TUI.

---

## 7. Updated preprocessing architecture

Phase 0 runs once over the source EPUB and builds reusable memory assets plus one reproducible chapter packet per chapter.

### 7.1 Phase 0 outputs

By the end of preprocessing, the system should have:

- locked glossary
- validated Chinese summaries
- derived English summaries
- idiom dictionary
- entity and relationship memory in LadybugDB
- embedding index for fuzzy support
- one chapter packet per chapter
- paragraph bundle derivation rules

### 7.2 Design rule

Expensive continuity and terminology work happens offline. Runtime translation should consume filtered packet-derived local context rather than rebuild memory on the fly.

---

## 8. EPUB ingest and structured extraction

Use deterministic code only.

### Responsibilities

- unpack EPUB
- identify chapter documents
- parse XHTML safely
- extract normalized Chinese text
- preserve placeholder-safe restoration mapping
- preserve stable block ordering and block IDs
- emit inspection artifacts for extracted content and structure

### Acceptance criteria

- input EPUB can be unpacked without crashing
- malformed XHTML generates a validation report
- extracted text can be mapped back to original XHTML blocks
- placeholder restoration is reversible for supported block types

---

## 9. Canonical glossary workflow

Canonical glossary construction runs as its own preprocessing sub-pipeline and remains separate from summaries, idioms, graph memory, and packet assembly.

### 9.1 Stage A — discovery with `analyst_name`

Use `analyst_name` to:

- detect candidate terms from source chapters
- classify likely category
- collect evidence snippets
- track `first_seen_chapter`
- track `last_seen_chapter`
- update `appearance_count`

This writes only to the **candidate registry**, not the locked glossary.

### 9.2 Stage B — candidate translation with `translator_name`

Use `translator_name` to produce candidate English renderings for discovered terms.

This stage creates **candidate English forms**, not final canon.

### 9.3 Prompt templates

**A. Translate one glossary word**

```text
Translate the following segment into English, without additional explanation.

{source_text}
```

**B. Translate with context**

```text
{context}
Referring to the information above, please translate it into English. without additional explanation :
{source_text}
```

**C. Translate with specific term**

```text
Refer to the translation below:
{source_term} should be translated as {target_term}.
Referring to the information above, please translate it into English. without additional explanation :
{source_text}
```

**D. Combine glossary with context**

```text
{context}
Refer to the translation below:
{source_term} should be translated as {target_term}.

Referring to the information above, please translate it into English. without additional explanation :

{source_text}
```

### 9.4 Prompt routing rules

- single term, clear meaning → A
- single term, ambiguous meaning → B
- larger source with one forced approved mapping → C
- larger source with forced mapping plus evidence → D

For initial glossary candidate creation, A and B are the default choices.

### 9.5 Stage C — deterministic validation and promotion

After candidate translation:

- run normalization and duplicate checks
- apply naming policy
- compare against existing canon
- record conflicts explicitly
- promote only validated entries into the locked glossary

### 9.6 Storage rule

- glossary candidates = SQLite
- locked glossary = SQLite
- graph DB is not the primary glossary authority

### 9.7 Mandatory category enum

- `character`
- `alias`
- `title_honorific`
- `faction`
- `location`
- `technique`
- `item_artifact`
- `realm_concept`
- `creature_race`
- `generic_role`
- `event`
- `idiom`

---

## 10. Summary workflow

Summary generation remains separate from glossary construction.

### 10.1 Summary authority rule

- Chinese summaries are authoritative continuity memory
- English summaries are derived convenience artifacts
- English summaries must be derived only from validated Chinese summaries plus locked glossary

### 10.2 Safe summary sequence

`source chapter -> structured Chinese summary -> validated Chinese summary -> derived English summary`

### 10.3 Per-chapter outputs

- `chapter_summary_zh_structured`
- `chapter_summary_zh_short`
- `chapter_summary_en_short`

### 10.4 Multi-chapter continuity layers

- chapter summary
- previous 3 chapters bundle
- `story_so_far_zh`
- `story_so_far_en`
- arc summary

### 10.5 Continuity update rule

- `story_so_far_zh(n)` derives from `story_so_far_zh(n-1)` plus current validated chapter summary
- English continuity derives from Chinese continuity plus locked glossary

### 10.6 Validation layers

- structure validation
- terminology validation
- content fidelity validation
- continuity validation

### 10.7 Useful flags

- `unsupported_claim`
- `major_omission`
- `wrong_referent`
- `glossary_conflict`
- `premature_reveal`
- `ambiguity_overwritten`
- `continuity_conflict`
- `schema_invalid`

---

## 11. Idiom workflow

Use `analyst_name` to:

- detect idioms and set phrases
- capture meaning
- propose preferred rendering
- suggest policy

Store idioms as versioned reusable structured assets.

### Rule

Idioms remain outside the graph as primary authority memory. They may be referenced during packet assembly, but the graph is not the main idiom store.

---

## 12. Graph MVP and lightweight world model

The graph MVP is a **relationship graph for translation support**.

It exists to improve:

- alias resolution
- identity continuity
- relationship continuity
- reveal-safe context assembly
- packet assembly quality

LadybugDB is the graph backend for this layer.

### 12.1 When the graph is used

LadybugDB is not used at the beginning of preprocessing and is not the primary runtime lookup store.

It enters during Phase 0 after:

1. structured extraction
2. initial glossary work
3. summary / idiom foundations

It is then used for:

4. entity extraction support
5. alias linking
6. relationship mining
7. graph validation
8. chapter-safe subgraph filtering
9. packet assembly support

### 12.2 In-scope node types

- Character
- Faction
- Location
- Item
- Technique
- Chapter
- Arc

### 12.3 In-scope edge types

- `ALIAS_OF`
- `APPEARS_IN`
- `MEMBER_OF`
- `DISCIPLE_OF`
- `MASTER_OF`
- `ALLY_OF`
- `ENEMY_OF`
- `LOCATED_IN`
- `OWNS`
- `USES_TECHNIQUE`
- `PART_OF_ARC`
- `NEXT_CHAPTER`

### 12.4 Lightweight world-model features

Only features that directly improve translation support are in scope:

**Hierarchy**
- faction hierarchy
- teacher/disciple lineage
- branch membership
- rank/title hierarchy

**Containment**
- location inside region / realm / city / building
- faction based in location
- item stored in location if explicit

**Role state**
- sect leader / elder / disciple / master / heir / guest / guard status
- time-scoped role changes
- title / honorific changes over chapters

**Reveal-safe lore context**
- identity reveal chains
- secret identity masking
- public vs reader-safe alias state
- lore facts only when safely revealed by chapter

### 12.5 Out of scope

- full lore ontology
- universal world simulation
- semantic concept graph for everything
- freeform inferred cosmology
- agentic world understanding

---

## 13. Alias and relationship model

### 13.1 Alias handling

The graph should support both:

- simple alias arrays on entity nodes
- explicit `ALIAS_OF` edges where auditability or masked identity matters

### 13.2 Alias fields

- `alias_text`
- `alias_language`
- `first_seen_chapter`
- `last_seen_chapter`
- `revealed_chapter`
- `confidence`
- `is_masked_identity`
- `schema_version`

### 13.3 Relationship fields

Required:

- `relationship_id`
- `type`
- `source_entity_id`
- `target_entity_id`
- `source_chapter`
- `start_chapter`
- `end_chapter` nullable
- `revealed_chapter`
- `confidence`
- `status`
- `schema_version`

Optional working-state fields:

- `provisional`
- `suspected`
- `disputed`
- `unconfirmed`
- `reader_unrevealed`
- `identity_masked`
- `state_reason`
- `evidence_strength`
- `notes`

### 13.4 Design rule

Raw model output may propose relationship edges, but deterministic checks and promotion rules decide what becomes confirmed graph state.

---

## 14. Chapter-safe filtering and retrieval arbitration

### 14.1 Chapter-safe filtering rule

A relationship may be included in chapter `N` only if:

- `start_chapter <= N`
- `end_chapter` is null or `end_chapter >= N`
- `revealed_chapter <= N`

This chapter-safe logic also applies to:

- aliases introduced later
- title changes
- faction-role changes
- identity reveals
- reveal-gated lore context
- summaries
- packet contents
- paragraph bundles

### 14.2 Retrieval precedence

1. locked glossary exact match
2. explicit alias match
3. deterministic idiom match
4. chapter-safe graph match
5. validated chapter-local packet memory
6. embedding-based fuzzy retrieval
7. reranked fallback candidates

### 14.3 Conflict rule

If a lower-priority retrieval source conflicts with a higher-priority authority source, the higher-priority source wins.

### 14.4 Fuzzy retrieval and reranking

The system may support:

- embedding-based fuzzy epithet retrieval
- indirect reference resolution
- advanced reranking over eligible candidates

But:

- deterministic glossary and exact alias matches remain first-line retrieval
- fuzzy retrieval is fallback / augmentation only
- reranking improves selection among eligible candidates; it does not replace deterministic safety rules

---

## 15. Chapter packets and paragraph bundles

### 15.1 Chapter packet purpose

A chapter packet is the precomputed runtime-ready memory container for a single chapter.

### 15.2 Minimum chapter packet contents

- chapter metadata
- chapter glossary subset
- previous 3 chapter summaries
- story-so-far summary
- active arc summary
- chapter-local idioms
- chapter-local entity and relationship context
- warnings
- packet schema version
- asset version metadata

### 15.3 Reproducibility fields

At minimum:

- `chapter_source_hash`
- `glossary_version_hash`
- `summary_version_hash`
- `graph_snapshot_hash`
- `idiom_policy_hash`
- `packet_builder_version`
- `built_at`

### 15.4 Graph contribution to packets

LadybugDB contributes:

- active entity list
- alias resolution candidates
- chapter-safe relationship snippets
- hierarchy / containment / role-state context where relevant
- reveal-safe identity notes
- reveal-safe lore context where justified

### 15.5 Packet design rule

Do not dump the whole subgraph into the packet. Include only graph content likely to improve local translation quality.

### 15.6 Paragraph bundle purpose

Provide only the local context needed for the current paragraph / block.

### 15.7 Minimum paragraph bundle contents

- matched glossary entries
- alias/title resolutions
- paragraph-matched idioms
- directly relevant local relationships
- minimal continuity notes
- retrieval evidence summary
- risk classification

### 15.8 Runtime rule

Translation should consume paragraph bundles rather than query LadybugDB heavily per paragraph.

---

## 16. Translation pipeline

The system translates each chapter using 3 controlled passes.

### 16.1 Pass 1 — source-faithful draft

Model: translation model

Responsibilities:

- translate Chinese to English
- preserve meaning, order, named entities, and structure placeholders
- obey glossary constraints
- remain conservative

Must not:

- invent motives
- add imagery
- dramatize scenes
- overwrite ambiguity without support
- consume broad narrative summaries by default

### 16.2 Pass 2 — semantic fidelity correction

Model: analyst/editor model

Responsibilities:

- compare Pass 1 draft against source
- repair hallucinations, omissions, mistranslated terms, wrong referents, or sequencing errors
- preserve ambiguity where the source is ambiguous

Possible flags:

- `hallucination_removed`
- `omission_restored`
- `term_corrected`
- `referent_uncertain`
- `ambiguous_source`

### 16.3 Pass 3 — readability polish

Model: analyst/editor model

Responsibilities:

- improve surface readability only
- operate on narrow windows, not full chapter by default

Must not:

- add new facts
- alter named terms
- change event order
- invent dialogue or imagery

### 16.4 High-risk paragraph handling

High-risk paragraphs may skip Pass 3.

### 16.5 Stronger paragraph risk classification

Risk factors may include:

- idiom density
- title/honorific density
- lore exposition
- relationship reversals or reveals
- pronoun ambiguity
- dense dialogue
- poetry or stylized language
- malformed or fragile XHTML
- unusually high entity density

Possible actions:

- skip Pass 3
- restrict context injection
- force stricter validation
- trigger resegmentation earlier
- log for regression review

---

## 17. Validation, failure handling, and memory update policy

### 17.1 Validation layers

**Structural validation**
- non-empty output
- successful placeholder restoration
- no unresolved control markers
- valid XHTML restoration
- stable block mapping

**Semantic validation**
- no known hallucination remains
- no critical omission remains
- glossary-critical terms are consistent
- ambiguity is preserved when required
- event order remains correct

**Memory-integrity validation**
- no glossary conflicts
- no future-knowledge leaks
- no invalid chapter-unsafe packet contents
- no invalid provisional-to-authority promotion
- no stale packet version misuse

### 17.2 Chapter-level checks

- all paragraphs completed
- no structural XHTML corruption
- terminology remains consistent across the chapter
- no unresolved high-severity fidelity flags

### 17.3 Failure handling

- retry once with stricter settings when a pass fails
- resegment unstable paragraphs if needed
- if still unstable, mark for review and continue
- persist checkpoint state frequently enough to resume safely

### 17.4 Resume granularity

The system must be able to resume from:

- current chapter
- current paragraph
- current pass
- latest stable output artifact

### 17.5 Failure classes

- informational
- recoverable warning
- serious warning
- hard failure

### 17.6 Memory update policy

- Pass 1 outputs never update authority memory
- Pass 2 outputs may update QA artifacts and warning state
- Pass 3 outputs never update authority memory
- validated Chinese summaries may update continuity authority state
- relationship updates require explicit evidence threshold
- candidate promotion requires deterministic checks and optional audit pass
- English outputs may be stored as inspection artifacts, but not as story truth

---

## 18. Centralized orchestration and baked-in production workflow

The project should no longer require scattered manual stage invocations as the primary operating model.

### 18.1 Orchestration responsibilities

The orchestration layer owns:

- workflow state
- stage transitions
- retries
- checkpoints
- run metadata
- event emission
- artifact registration
- repair / rerun policy
- cleanup / reset actions
- production workflow entrypoints

### 18.2 Workflow families

**Preprocessing workflow**
- EPUB unpacking
- XHTML parsing and extraction
- glossary workflow
- summary workflow
- idiom workflow
- graph workflow
- packet assembly

**Translation workflow**
- load chapter packet
- derive paragraph bundles
- Pass 1
- structural restore / validate
- Pass 2
- fidelity gate
- optional Pass 3
- chapter checks
- checkpoint commit

**Production workflow**
- select input + release/run context
- preprocess if missing/stale
- translate requested range / full run
- validate outputs
- rebuild EPUB
- publish / finalize reports

**Reset / cleanup workflow**
- analyze scope
- preview destruction plan
- perform scoped deletion / DB cleanup
- emit event log + final report

### 18.3 Design rule

Production workflow is baked into orchestration, not a loose wrapper around unrelated scripts.

### 18.4 Verbose and progress visibility

The orchestration layer must emit a shared event stream that can power:

- CLI console progress
- `--verbose` step-by-step reporting
- MLflow artifacts / metrics
- TUI live panels

The operator should be able to see what is happening without manually opening MLflow.

### 18.5 Event stream concept

Each meaningful workflow action emits structured events such as:

- stage started / completed
- chapter started / completed
- paragraph retry
- packet assembled
- validation failed
- cleanup candidate detected
- artifact written
- warning emitted
- run finalized

---

## 19. Reset and cleanup workflow

Reset / cleanup is an orchestration-owned workflow for starting fresh safely.

### 19.1 Supported reset scopes

- `run`
- `translation`
- `preprocess`
- `cache`
- `all`

### 19.2 Required behaviors

- `--dry-run` preview of what would be deleted
- scoped cleanup of filesystem artifacts
- scoped cleanup of SQLite state
- release-aware cleanup by run ID / release ID where possible
- preservation of inputs, config, prompts, and manual overrides by default
- structured event/logging integration with console and MLflow

### 19.3 Design rule

Cleanup must be explicit, inspectable, and scope-aware. It must not silently destroy authority memory the user did not choose to clear.

---

## 20. Unified operator UI with Textual

The next unified UI is a **Textual** TUI sitting on top of orchestration, event streaming, production workflow, and reset/cleanup.

### 20.1 Role of the TUI

The TUI is an operator console, not a separate architecture. It should reuse the same orchestration services, events, state, and artifacts as CLI and MLflow.

### 20.2 TUI scope

- run overview
- workflow progress
- chapter / paragraph status
- warnings and failures
- artifact navigation
- packet / validation inspection
- run history
- cleanup / reset controls
- production workflow launch and monitoring

### 20.3 Suggested screens / panels

- dashboard / home
- active run detail
- preprocessing detail
- translation detail
- chapter queue / status table
- warnings / failure inspector
- artifacts / reports browser
- reset / cleanup preview screen
- settings / run configuration screen

### 20.4 Integration rule

CLI and TUI should share the same controllers and execution services. UI is a presentation layer over the orchestration core.

---

## 21. Storage split and artifact discipline

### 21.1 SQLite

- locked glossary
- glossary candidates
- summaries
- idioms
- checkpoints
- packet metadata
- translation cache
- run metadata
- cleanup bookkeeping

### 21.2 LadybugDB

- entities
- aliases
- appearances
- relationships
- chapter/arc graph links
- lightweight world-model structure
- chapter-safe narrative structure

### 21.3 JSON

- chapter packets
- paragraph bundles
- validation reports
- event traces
- cleanup plans / reports

### 21.4 Filesystem

- outputs
- logs
- intermediate XHTML artifacts
- human-readable reports
- regression sets
- exported dashboards or summaries

### 21.5 Artifact rule

Any artifact that influences runtime translation must carry enough version metadata to reproduce or invalidate it.

---

## 22. Package / module layout

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

### 22.1 Responsibility split

- `epub/` — unpack, parse, placeholders, restore, rebuild, validate
- `glossary/` — discovery, candidate translation, normalization, matching, validation
- `summaries/` — chapter, arc, story_so_far, validation
- `idioms/` — extract, match, validate
- `graph/` — entities, aliases, relationships, chapter-safe filtering, assembly, validation
- `packets/` — chapter packet and paragraph bundle schemas/builders
- `llm/` — model clients and prompt loading
- `translation/` — pass1, pass2, pass3, validators, chapter runner, risk handling
- `orchestration/` — states, preprocess graph, translation graph, production workflow, reset workflow, event bus/controllers
- `tracking/` — MLflow helpers, metrics, artifact logging, run summaries
- `tui/` — Textual app, screens, widgets, controllers/adapters
- `db/` — SQLite schema, cache, checkpoints, repositories

---

## 23. CLI requirements

The system should expose CLI commands or subcommands for at least:

- `epub-roundtrip`
- `preprocess`
- `translate-chapter`
- `translate-range`
- `rebuild-epub`
- `run-production`
- `reset`
- `tui`

### Required CLI behavior

- accept config path
- accept chapter number or range where relevant
- support resume behavior
- support `--verbose`
- print artifact/report paths on failure
- support dry-run for destructive actions
- return non-zero exit codes on hard failures

---

## 24. Observability, evaluation, and dashboards

The system must support local observability and evaluation.

### 24.1 Required tracked metadata

- model names
- prompt versions
- packet version
- glossary version
- chapter number
- pass number
- retry counts
- warnings
- validation outcomes
- runtime metrics
- event stream records

### 24.2 Suggested metrics

- latency
- retry count
- resegmentation count
- glossary consistency rate
- unresolved placeholder count
- fidelity flag counts
- chapter completion time
- retrieval confidence distributions
- risk class frequencies
- cleanup counts and scope summaries

### 24.3 Evaluation dimensions

- fidelity
- terminology consistency
- structural integrity
- readability

### 24.4 Golden set requirement

Maintain a benchmark set of difficult paragraphs / chapters containing:

- idioms
- honorific-heavy dialogue
- identity concealment
- relationship reversals
- lore exposition
- pronoun ambiguity
- XHTML-heavy formatting cases

### 24.5 Dashboard / inspection views

These may be presented in MLflow, exported reports, or the TUI:

- chapter completion status
- warning distribution
- fidelity flag trends
- glossary conflict counts
- retry / resegmentation patterns
- high-risk paragraph frequency
- retrieval confidence distributions
- evaluation scores across experiments

---

## 25. Resource-budget policy

The system must define runtime budget rules for local hardware operation.

### Minimum policies

- max context window per pass
- max paragraph size before forced segmentation
- when to invoke fallback translation model
- when Pass 3 is automatically disabled
- which optional features are disabled first under memory pressure
- maximum bundle size before context trimming

### Suggested degrade-first order

1. disable broad continuity injection
2. reduce fuzzy retrieval candidate count
3. reduce reranking candidate depth
4. skip Pass 3
5. use fallback translation model if explicitly enabled

### Rule

Reduced-budget runs must remain structurally safe and chapter-safe.

---

## 26. Milestones

### Milestone 1 — EPUB round-trip MVP
- read / unpack / validate / rebuild smoke test
- XHTML validation report
- baseline CLI entry

### Milestone 2 — Single-chapter translation MVP
- placeholder-safe extraction
- Pass 1 + Pass 2
- raw/corrected outputs
- basic validation

### Milestone 3 — Canonical glossary system
- candidate registry
- locked glossary tables
- deterministic matching
- glossary validation

### Milestone 4 — Summary memory
- validated Chinese chapter summaries
- derived English summaries
- previous-3 and story-so-far support

### Milestone 5 — Idiom workflow
- idiom detection and extraction
- idiom normalization and duplicate detection
- idiom policy store
- exact-match retrieval for packet assembly

### Milestone 6 — Graph MVP foundation
- LadybugDB client
- entity nodes
- alias support
- relationship edges
- graph validation
- chapter-safe filtering

### Milestone 7 — Lightweight world model
- hierarchy edges
- containment edges
- role-state changes
- reveal-safe lore context

### Milestone 8 — Chapter packets with graph integration
- chapter packet schema
- packet builder with graph context
- packet versioning
- paragraph bundle builder
- chapter-safe relationship snippets and packet size control

### Milestone 9 — Full three-pass workflow with stronger paragraph risk classification
- Pass 3
- stronger paragraph risk classifier
- high-risk paragraph skip/downgrade rules
- richer chapter-level checks and artifacts

### Milestone 10 — Centralized orchestration and production workflow
- explicit state model
- run controllers
- resume support
- retry / resegmentation flow
- baked-in production workflow
- shared event stream
- verbose console reporting

### Milestone 11 — Reset / cleanup workflow
- reset scopes
- dry-run preview
- filesystem + SQLite cleanup
- release-aware cleanup
- preservation rules

### Milestone 12 — Unified Textual TUI
- dashboard
- active-run panels
- warnings / artifacts inspection
- cleanup integration
- production workflow launch and monitoring

### Milestone 13 — Observability, evaluation, dashboards
- tracked run metadata
- comparison-friendly logs
- regression / golden set support
- quality trend dashboards

### Milestone 14 — Batch pilot and final rebuild
- 10–50 chapter pilot
- final EPUB rebuild from translated outputs
- validation report

---

## 27. Agent execution policy

Coding agents working on this repo must follow these rules:

1. Do not collapse multiple major stages into one opaque function.
2. Do not let model output directly mutate locked glossary or authoritative summaries.
3. Do not inject broad full-chapter narrative context into Pass 1 by default.
4. Do not bypass placeholder restoration and validation.
5. Do not remove artifact emission in the name of simplification.
6. Do not hardcode story-specific assumptions into generic pipeline code.
7. Prefer typed schemas and versioned artifacts over ad hoc dicts where practical.
8. Implement the smallest validated slice first, then extend.
9. Preserve resumability whenever adding new workflow stages.
10. Keep modules small and responsibility-focused.
11. Do not let summaries inject future knowledge.
12. Do not let fuzzy retrieval override exact glossary matches.
13. Do not write repaired English back into authoritative Chinese continuity memory.
14. Do not merge pass responsibilities.
15. Do not silently ignore placeholder failures.
16. Do not regenerate stored continuity artifacts at runtime unless explicitly required by design.
17. Do not treat provisional relationship state as confirmed truth.
18. Do not bypass retrieval arbitration policy.
19. Do not build UI logic that duplicates orchestration logic.
20. Do not implement destructive cleanup without preview / scope control.

---

## 28. Definition of done

The working target is achieved when the system can:

1. unpack and validate an EPUB
2. preprocess chapters into stable memory artifacts
3. build reproducible chapter packets
4. translate chapters through controlled passes (Pass 1 and Pass 2 are required; Pass 3 is strictly optional but must be supported for low-risk paragraphs)
5. validate structure, fidelity, and glossary consistency
6. checkpoint and resume safely
7. run through a centralized production workflow
8. show visible progress and warnings through CLI and TUI
9. perform scoped cleanup/reset safely
10. rebuild translated output into an EPUB
11. leave enough artifacts to debug failures without rerunning everything

---

## 29. Condensed summary

Resemantica is a local-first EPUB translation pipeline built around precomputed translation memory, chapter-safe structured memory, and constrained multi-pass translation. The locked glossary remains naming truth, validated Chinese summaries remain continuity truth, LadybugDB provides graph-backed narrative state for chapter packet assembly, and runtime translation consumes filtered paragraph bundles rather than broad live retrieval. The consolidated next-state architecture adds a graph MVP plus lightweight world model, centralized orchestration with a baked-in production workflow and shared event stream, a reset/cleanup workflow for safe fresh starts, and a Textual TUI as the unified operator console.
