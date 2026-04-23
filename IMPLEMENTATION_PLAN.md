# Resemantica Implementation Plan

Version: 1.0
Sources: `SPEC.md`, `ARCHITECT.md`, `DATA_CONTRACT.md`, `DECISIONS.md`
Status: milestone implementation plan

## Approach

This plan turns the target milestones into buildable execution slices. Each milestone is intentionally narrow, preserves the authority boundaries from the architecture and data contract, and ends with explicit validation so the next milestone builds on stable artifacts instead of assumptions.

## Scope

- In:
  - Milestone-by-milestone implementation plan for Milestones 1 through 14
  - Ordered action items for code, schemas, workflows, and validation
  - Dependency-aware sequencing across EPUB, preprocessing, translation, orchestration, observability, and UI
- Out:
  - Exact SQL DDL
  - Prompt text design beyond milestone references
  - Staffing, calendar estimates, or project-management process

## Global Assumptions

- The project starts from an early-stage codebase and should optimize for validated vertical slices over breadth.
- Typed schemas and versioned artifacts should land before higher-level orchestration convenience.
- Sequential local execution on Windows 11 is the baseline; parallelism is not required for milestone completion.
- Each milestone should leave behind tests, inspection artifacts, or smoke checks that make regressions visible.

## Cross-Milestone Rules

- Keep authority state separate from working state from the start.
- Do not let runtime translation bypass chapter packets and paragraph bundles once those exist.
- Treat every new durable artifact as versioned and inspectable.
- Keep CLI, TUI, and orchestration logic separated by responsibility.
- Only expand scope when the previous milestone has a stable validation path.

## Milestone Dependency Chain

**Note:** Milestone order (M1–M14) governs execution priority. Task brief IDs are historical labels and do not determine execution sequence. See `docs/40-tasks/README.md` for the canonical milestone-to-task mapping.

- M1 is the base for M2 and M14.
- M2 depends on M1 extraction and restoration.
- M3 and M4 depend on M1 extraction.
- M5 (idioms) depends on M1 and M3.
- M6 (graph) depends on M1, M3, and M4.
- M7 (world model) depends on M6.
- M8 (packets with graph) depends on M3, M4, M5, and M7.
- M9 (Pass 3 + risk) depends on M2 and M8.
- M10 depends on M1 through M9 having stable callable entrypoints.
- M11 depends on M10 run metadata and artifact registration.
- M12 depends on M10 and M11.
- M13 depends on M10 and should absorb instrumentation added earlier.
- M14 depends on M10 through M13 being usable end to end.

## Milestone 1: EPUB Round-Trip MVP

### Approach

Build the deterministic EPUB foundation first: unpack, parse, inspect, rebuild. This milestone proves the system can safely touch the source EPUB and return a structurally valid output before any translation logic exists.

### Scope

- In:
  - EPUB unpacking
  - XHTML parsing and validation
  - Stable chapter and block discovery
  - Round-trip rebuild smoke path
  - Baseline CLI entrypoint
- Out:
  - Translation
  - Glossary extraction
  - Graph logic
  - TUI work

### Action Items

[ ] Create the initial package layout under `src/resemantica/` for `cli.py`, `settings.py`, `epub/`, `logging_config.py`, and shared utilities.
[ ] Add configuration loading and path resolution for source EPUB input, working directories, and output locations.
[ ] Implement deterministic EPUB unpacking and manifest discovery in `epub/`.
[ ] Implement XHTML parsing, chapter document selection, and validation reporting with stable block ordering and block IDs.
[ ] Implement placeholder-safe restoration primitives and a rebuild path that can reconstruct a valid EPUB without translation changes.
[ ] Add an `epub-roundtrip` CLI command that unpacks, validates, rebuilds, and writes inspection artifacts and reports.
[ ] Add smoke tests for unpack -> validate -> rebuild on a small fixture EPUB, including malformed XHTML reporting behavior.

### Validation

[ ] Verify a supported EPUB can be unpacked and rebuilt without crashing.
[ ] Verify malformed XHTML produces a readable validation report.
[ ] Verify block ordering and block IDs remain stable across the round-trip path.

## Milestone 2: Single-Chapter Translation MVP

### Approach

Use the EPUB foundation to prove the smallest translation slice: one chapter, structure-safe extraction, Pass 1 draft, Pass 2 correction, and basic validation. Keep the context narrow and avoid early continuity systems.

### Scope

- In:
  - Single-chapter extraction flow
  - Pass 1 and Pass 2
  - Raw and corrected outputs
  - Basic structural and semantic validation
- Out:
  - Pass 3
  - Packets
  - Graph retrieval
  - Full production orchestration

### Action Items

[ ] Add chapter-level source loaders that expose stable block text and placeholder references to the translation layer.
[ ] Create `llm/` model client abstractions for `translator_name` and `analyst_name`, including prompt version tracking.
[ ] Implement Pass 1 in `translation/pass1.py` with conservative draft generation and glossary-hook placeholders only.
[ ] Implement structural restoration and basic output validators for non-empty output, placeholder preservation, and block mapping stability.
[ ] Implement Pass 2 in `translation/pass2.py` to compare source and draft and produce corrected output plus fidelity flags.
[ ] Implement a `translate-chapter` CLI command that runs extraction, Pass 1, restoration checks, Pass 2, and artifact emission.
[ ] Persist pass artifacts, validation reports, and basic checkpoint metadata for the single-chapter flow.
[ ] Add tests that cover placeholder-safe translation, Pass 2 correction flow, and hard-failure behavior on restoration errors.

### Validation

[ ] Verify one chapter can produce raw and corrected outputs plus validation reports.
[ ] Verify placeholder failures halt the workflow instead of being ignored.
[ ] Verify Pass 2 output can be resumed or re-read without rerunning successful earlier steps.

## Milestone 3: Canonical Glossary System

### Approach

Build the first authority store after extraction: glossary candidates and locked glossary. Keep discovery, candidate translation, and promotion separate so runtime naming truth stays deterministic.

### Scope

- In:
  - Candidate registry
  - Locked glossary store
  - Discovery and candidate translation workflow
  - Deterministic normalization and validation
- Out:
  - Summary generation
  - Graph-backed alias resolution
  - Fuzzy retrieval

### Action Items

[ ] Add SQLite setup and repositories in `db/` for glossary candidates and locked glossary entries.
[ ] Encode typed glossary schemas and status enums aligned with `DATA_CONTRACT.md`.
[ ] Implement glossary discovery using extracted chapter text, evidence snippets, chapter ranges, and category assignment.
[ ] Implement candidate English translation with prompt routing metadata and translator provenance capture.
[ ] Implement deterministic normalization, duplicate detection, naming-policy checks, and explicit conflict recording.
[ ] Implement promotion logic that moves validated candidates into locked glossary without mutating candidate history.
[ ] Add CLI or preprocessing subcommands that can run discovery, candidate translation, validation, and promotion independently.
[ ] Add tests for duplicate detection, conflict handling, and exact-match retrieval precedence.

### Validation

[ ] Verify candidate discovery never writes directly to locked glossary.
[ ] Verify approved glossary entries are stored separately from provisional or rejected candidates.
[ ] Verify exact glossary matches win over all lower-priority future retrieval sources.

## Milestone 4: Summary Memory

### Approach

Build continuity memory as a separate authority layer after glossary. Chinese summaries become the continuity truth; English summaries remain derived artifacts with explicit provenance.

### Scope

- In:
  - Structured Chinese chapter summaries
  - Validated Chinese short summaries
  - Derived English short summaries
  - Previous-3 and story-so-far support
- Out:
  - Arc-aware graph integration
  - Packet assembly
  - Pass 3

### Action Items

[ ] Add summary repositories and schemas in `db/` for draft summaries, validated Chinese summaries, and derived English summaries.
[ ] Implement chapter summary generation in `summaries/` with clear separation between structured draft output and validated continuity output.
[ ] Implement terminology, schema, continuity, and future-knowledge validation for Chinese summaries.
[ ] Implement `story_so_far_zh` update logic as a deterministic derivation from the previous validated state plus the current validated chapter summary.
[ ] Implement derived English summary generation that uses validated Chinese summaries plus locked glossary and records provenance hashes.
[ ] Add materialization logic for previous-3 chapter bundles and arc summary placeholders where available.
[ ] Expose summary generation and validation through the preprocessing workflow or CLI subcommands.
[ ] Add tests for continuity conflicts, glossary conflicts, and the rule that English summaries never become authority memory.

### Validation

[ ] Verify Chinese summaries and English summaries are stored as separate datasets with separate statuses.
[ ] Verify future-knowledge leaks are caught during continuity validation.
[ ] Verify `story_so_far_zh` derivation never uses repaired English outputs as source truth.

## Milestone 5: Idiom Workflow

### Approach

Build idiom detection, normalization, and storage as a preprocessing authority layer after glossary, making idiom policies available for packet assembly.

### Scope

- In:
  - idiom detection from source chapters
  - normalization and duplicate detection
  - idiom policy store in SQLite
  - exact-match retrieval for packet assembly

- Out:
  - packet integration
  - translation-time matching beyond exact match

### Action Items

[ ] Define the `Idiom` model and SQLite schema in `idioms/repo.py` aligned with `DATA_CONTRACT.md`.
[ ] Implement `idioms.extractor.extract_idioms` using the `analyst_name` model to find idioms in chapter text.
[ ] Implement normalization and duplicate detection in `idioms.validators`.
[ ] Add the `preprocess idioms` CLI command.
[ ] Add tests for detection, storage, and retrieval.

### Validation

[ ] Idioms can be extracted from a chapter and stored in SQLite.
[ ] Duplicates are correctly identified and merged or rejected.
[ ] Idioms are available for exact-match retrieval by source text.

## Milestone 6: Graph MVP Foundation

### Approach

Add the graph only after glossary and summary foundations exist. Keep the graph narrow: alias resolution, entity continuity, relationship continuity, and chapter-safe filtering for translation support.

### Scope

- In:
  - LadybugDB client integration
  - Entity and alias storage
  - Relationship storage
  - Graph validation
  - Chapter-safe filtering
- Out:
  - Full world simulation
  - Broad live runtime querying
  - Rich lore reasoning

### Action Items

[ ] Add `graph/` models, repositories, and a LadybugDB client wrapper with explicit boundaries around provisional versus confirmed state.
[ ] Implement entity extraction support using chapter text and glossary anchors, with supported node types only.
[ ] Implement alias storage with reveal-aware fields and support for both alias arrays and explicit `ALIAS_OF` edges.
[ ] Implement relationship storage for the MVP edge set, including chapter interval fields and reveal metadata.
[ ] Implement deterministic graph validation for entity references, relationship types, chapter-safe intervals, and promotion status.
[ ] Implement chapter-safe filtering utilities that can produce eligible entity, alias, and relationship sets for chapter `N`.
[ ] Add graph snapshot or export metadata sufficient for packet reproducibility.
[ ] Add tests for alias reveal gating, relationship eligibility logic, and separation of provisional versus confirmed graph state.

### Validation

[ ] Verify provisional graph state is never treated as confirmed runtime truth without promotion.
[ ] Verify chapter-safe filtering blocks future reveals and expired relationships.
[ ] Verify the graph can be snapshotted or hashed for downstream packet versioning.

## Milestone 7: Lightweight World Model

### Approach

Extend the graph carefully with only the world-model features that materially improve translation quality. Keep every addition reveal-safe, chapter-scoped, and directly useful for packet assembly.

### Scope

- In:
  - hierarchy edges (faction, teacher-disciple lineage, rank/title)
  - containment edges (location hierarchy, faction bases)
  - role-state changes across chapters
  - reveal-safe lore context

- Out:
  - general ontology modeling
  - freeform inferred cosmology
  - agentic reasoning on world state

### Action Items

[ ] Add graph schema support for hierarchy, containment, and role-state relationship types that are explicitly in scope.
[ ] Implement extraction or promotion workflows for rank/title hierarchy, faction membership, teacher-disciple lineage, and location containment where explicitly supported.
[ ] Add time-scoped role-state handling for title or status changes across chapters.
[ ] Implement reveal-safe lore facts and masked-identity chain handling with chapter-gated visibility rules.
[ ] Extend graph validators to enforce scope limits and reject unsupported world-model expansion.
[ ] Extend packet assembly selectors to include these richer relationship types only when locally relevant.
[ ] Add tests for role-state transitions, containment visibility, and reveal-safe lore context.

### Validation

[ ] Verify new world-model features remain within the translation-support scope from the spec.
[ ] Verify reveal-safe lore context only appears at or after the allowed chapter.
[ ] Verify packet enrichment remains compact after the richer graph model lands.

## Milestone 8: Chapter Packets with Graph Integration

### Approach

Build immutable chapter packets from validated upstream memory including confirmed graph state, and derive narrow paragraph bundles for translation-time use. This milestone merges packet building and graph integration since the graph is now available from M7.

### Scope

- In:
  - chapter packet schema
  - packet builder with graph context enrichment
  - chapter-safe relationship snippets and alias resolution candidates
  - paragraph bundle derivation
  - packet versioning and stale detection
  - retrieval arbitration (glossary and idiom outrank graph)

- Out:
  - Pass 3
  - full production orchestration

### Action Items

[ ] Add typed schemas in `packets/` for chapter packets and paragraph bundles, including version and provenance fields.
[ ] Implement packet metadata persistence in SQLite and JSON packet artifact emission on disk.
[ ] Build the chapter packet assembler using locked glossary, validated summaries, idiom policies, chapter metadata, and confirmed graph context.
[ ] Implement packet-side alias resolution candidate lists and reveal-safe identity notes from graph data.
[ ] Add packet size budgeting rules so graph enrichment can be trimmed without violating chapter safety.
[ ] Implement paragraph bundle derivation logic that selects local glossary hits, continuity notes, evidence summaries, risk placeholders, and locally relevant graph context.
[ ] Implement retrieval arbitration in packet or bundle assembly so glossary and deterministic idiom matches outrank graph contributions.
[ ] Implement packet reproducibility fields such as source hash, glossary hash, summary hash, graph snapshot hash, builder version, and build timestamp.
[ ] Add stale-artifact detection so packet rebuilds can be triggered when upstream authority hashes change.
[ ] Add a CLI or preprocessing entrypoint to build or rebuild chapter packets for a chapter or range.
[ ] Add tests for packet schema validity, reproducibility metadata presence, minimal paragraph bundle content rules, graph-to-packet filtering, packet size control, and retrieval precedence conflicts.

### Validation

[ ] Verify chapter packets are immutable artifacts with enough metadata to reproduce or invalidate them.
[ ] Verify paragraph bundles contain only local context and not broad full-chapter dumps.
[ ] Verify packet rebuilds trigger when upstream authority hashes change.
[ ] Verify packets contain chapter-safe graph snippets rather than unrestricted subgraph exports.
[ ] Verify exact glossary and idiom matches still outrank graph suggestions in paragraph bundles.
[ ] Verify graph snapshot changes invalidate dependent packets.

## Milestone 9: Full Three-Pass Workflow and Stronger Risk Handling

### Approach

Complete the translation workflow by adding Pass 3, stronger paragraph risk classification, and richer chapter-level validation. This milestone should still keep passes narrow and avoid merging responsibilities.

### Scope

- In:
  - Pass 3
  - Stronger risk classifier
  - High-risk skip or downgrade rules
  - Richer chapter-level checks and artifacts
- Out:
  - Production orchestration controllers
  - TUI screens
  - Cleanup workflow

### Action Items

[ ] Implement Pass 3 in `translation/pass3.py` with strict constraints that improve readability without changing facts, named terms, or event order.
[ ] Implement a paragraph risk classifier that uses idiom density, title density, relationship reveal risk, pronoun ambiguity, XHTML fragility, and entity density.
[ ] Add policy logic to skip Pass 3, restrict context, or force stricter validation for high-risk paragraphs.
[ ] Extend translation validators to capture chapter-level terminology consistency, unresolved high-severity fidelity flags, and structural completeness.
[ ] Add retry-once and resegmentation rules that are consistent with checkpointing and artifact persistence.
[ ] Extend translation artifact schemas and reports to include risk class, retry counts, and pass decisions.
[ ] Add tests for Pass 3 guardrails, high-risk skip behavior, and chapter-level validation failure handling.

### Validation

[ ] Verify Pass 3 never writes authority memory and never changes protected terminology or event order.
[ ] Verify high-risk paragraphs can skip Pass 3 while the chapter still completes safely.
[ ] Verify chapter-level validation catches unresolved structural or fidelity failures before success is reported.

## Milestone 10: Centralized Orchestration and Production Workflow

### Approach

Unify the working slices under one orchestration core. This is the milestone where scattered commands become one coherent execution model with state, checkpoints, events, and production entrypoints.

### Scope

- In:
  - State model
  - Run controllers
  - Resume support
  - Retry and resegmentation flow
  - Shared event stream
  - Production workflow entrypoint
- Out:
  - Reset deletion logic beyond planning hooks
  - TUI presentation layer
  - Advanced dashboards

### Action Items

[ ] Create `orchestration/` state, controller, and workflow modules for preprocess, translate, and production runs.
[ ] Implement run metadata creation, checkpoint coordination, and stage transition control backed by SQLite.
[ ] Implement a shared event bus with structured events aligned to the data contract.
[ ] Wrap preprocess, packet build, translation, validation, and EPUB rebuild into callable orchestration services rather than direct CLI-only code paths.
[ ] Implement resume behavior at chapter, paragraph, and pass granularity using checkpoint state and latest stable artifact references.
[ ] Implement `run-production` and `translate-range` CLI commands that go through orchestration services and emit artifact locations on failure.
[ ] Add integration tests for end-to-end stage sequencing, resume behavior, and event emission.

### Validation

[ ] Verify production runs execute through orchestration rather than ad hoc script chaining.
[ ] Verify resume can restart from the latest stable artifact without corrupting authority or packet state.
[ ] Verify structured events exist for every major workflow transition.

## Milestone 11: Reset and Cleanup Workflow

### Approach

Add safe destruction only after orchestration knows what exists. Cleanup must preview first, respect scope, and avoid silently deleting authority state the operator did not choose to clear.

### Scope

- In:
  - Reset scopes
  - Dry-run preview
  - Filesystem cleanup
  - SQLite cleanup
  - Release-aware cleanup
- Out:
  - UI polish
  - Automated archival policies

### Action Items

[ ] Implement cleanup planning models and storage for cleanup plans and cleanup reports.
[ ] Implement scope resolution for `run`, `translation`, `preprocess`, `cache`, and `all`.
[ ] Implement dry-run analysis that enumerates deletable filesystem artifacts, SQLite rows, and preserved assets.
[ ] Implement scoped deletion actions that preserve inputs, config, prompts, and manual overrides by default.
[ ] Integrate cleanup execution into orchestration so it emits structured events and final reports.
[ ] Add a `reset` CLI command with `--dry-run`, run-scoped targeting, and non-zero exit behavior on hard failures.
[ ] Add tests for scope isolation, preservation rules, and release-aware cleanup behavior.

### Validation

[ ] Verify dry-run previews exactly what would be deleted before any destructive action occurs.
[ ] Verify cleanup can target run-level or translation-only state without wiping authority data by accident.
[ ] Verify cleanup reports and events are written for both preview and execution paths.

## Milestone 12: Unified Textual TUI

### Approach

Build the TUI last among operational cores so it can sit cleanly on top of existing controllers and events. The TUI should present orchestration state, not recreate orchestration logic inside the UI.

### Scope

- In:
  - Dashboard
  - Active run views
  - Warnings and artifact inspection
  - Cleanup previews
  - Production workflow launch and monitoring
- Out:
  - Alternate execution model
  - UI-owned business logic

### Action Items

[ ] Create the `tui/` package with Textual app bootstrap, shared controllers, and screen skeletons.
[ ] Implement a dashboard view that reads run summaries, active status, and recent warnings from orchestration services.
[ ] Implement active-run views for preprocessing, translation, and chapter queue status.
[ ] Implement artifact and validation inspectors that can browse packet, report, and output metadata without bypassing repositories.
[ ] Implement cleanup preview and execution screens that reuse reset workflow controllers.
[ ] Implement production workflow launch controls that invoke orchestration services instead of direct shell calls.
[ ] Add smoke tests or controller-level tests that verify TUI actions map to orchestration services correctly.

### Validation

[ ] Verify the TUI can monitor and launch workflows using the same orchestration services as the CLI.
[ ] Verify warnings, failures, and artifact navigation reflect structured event and repository state.
[ ] Verify no UI screen contains duplicated workflow logic that diverges from orchestration.

## Milestone 13: Observability, Evaluation, and Dashboards

### Approach

Formalize the instrumentation added earlier so runs are comparable, regressions are visible, and quality trends can be inspected locally. This milestone should turn operational exhaust into useful evaluation assets.

### Scope

- In:
  - Tracked run metadata
  - Comparison-friendly logs
  - Golden-set support
  - Quality dashboards and reports
- Out:
  - Cloud analytics platform work
  - Fully automated experiment management beyond local needs

### Action Items

[ ] Extend `tracking/` with MLflow helpers for parameters, metrics, artifacts, and run summaries aligned to the data contract.
[ ] Instrument preprocess, packet build, translation, validation, cleanup, and rebuild stages to emit consistent metrics and artifact registrations.
[ ] Add evaluation dataset support for golden paragraphs or chapters covering idioms, honorific-heavy dialogue, identity concealment, relationship reversals, lore exposition, pronoun ambiguity, and XHTML-heavy cases.
[ ] Implement local evaluation runners that can score fidelity, terminology consistency, structural integrity, and readability on benchmark data.
[ ] Add exported summaries or dashboard views for chapter completion, warning trends, retry patterns, glossary conflicts, and high-risk paragraph frequency.
[ ] Add regression checks that compare selected outputs or metrics across runs.
[ ] Add tests for tracking metadata completeness and basic evaluation pipeline behavior.

### Validation

[ ] Verify run metadata includes model names, prompt versions, packet versions, warning counts, and validation outcomes.
[ ] Verify a golden-set run can be executed and compared across experiments.
[ ] Verify dashboards or reports expose quality and operational trends without requiring manual log digging.

## Milestone 14: Batch Pilot and Final Rebuild

### Approach

Use the complete system on a realistic chapter range before attempting final-book output. This milestone is about proving operational readiness, artifact quality, and rebuild integrity under real workload conditions.

### Scope

- In:
  - 10 to 50 chapter pilot
  - Full translation workflow
  - Final EPUB rebuild from translated outputs
  - Validation report and pilot review artifacts
- Out:
  - Production-scale automation beyond the local operator model
  - New major architecture features

### Action Items

[ ] Select a representative pilot range that stresses glossary consistency, continuity, reveal-safe memory, idioms, and XHTML-heavy formatting.
[ ] Run preprocessing and packet generation for the pilot set and verify stale-artifact handling before translation begins.
[ ] Execute the full translation workflow through orchestration with checkpoints, retries, risk handling, and observability enabled.
[ ] Review warnings, validation reports, and golden-set regression comparisons to identify blocking defects before final rebuild.
[ ] Rebuild the translated pilot into an EPUB and run structural validation plus manual spot checks on difficult chapters.
[ ] Fix blocking defects found in the pilot and rerun the affected scopes using resume or targeted reset rather than full restart.
[ ] Produce a final pilot report summarizing quality, failures, cleanup behavior, and readiness for broader runs.

### Validation

[ ] Verify a 10 to 50 chapter batch can complete with resumability, inspection artifacts, and stable output packaging.
[ ] Verify final EPUB rebuild works from translated outputs rather than ad hoc manual assembly.
[ ] Verify the pilot leaves enough artifacts and reports to debug issues without rerunning the full batch.

## Final Readiness Checklist

[ ] EPUB ingest, validation, and rebuild are deterministic and tested.
[ ] Authority memory layers are separate, validated, and reproducible.
[ ] Chapter packets and paragraph bundles are the standard runtime context path.
[ ] Translation passes are narrow, validated, and resumable.
[ ] Orchestration owns production workflow, events, and checkpoints.
[ ] Cleanup is explicit, scoped, and previewable.
[ ] CLI and TUI share orchestration services.
[ ] Observability and evaluation make regressions visible before large runs.
[ ] A batch pilot demonstrates end-to-end readiness on real chapters.
