# Runtime Lifecycle

## End-To-End Flow

```text
source EPUB
  -> extraction
  -> preprocessing products
  -> chapter packet build
  -> chapter translation
  -> EPUB reconstruction
  -> final reports and output EPUB
```

## Phase Contracts

### Phase 0: Extraction And Preprocessing

Inputs:

- source EPUB
- operator config

Outputs:

- extracted chapter/block metadata
- locked glossary
- validated Chinese summaries
- derived English summaries
- idiom policies
- graph state
- chapter packets

### Phase 1: Translation

Inputs:

- source chapter text
- chapter packet
- release and run metadata

Outputs:

- pass artifacts
- validation reports
- checkpoints
- translated chapter content

### Phase 2: Reconstruction

Inputs:

- translated chapter/block outputs
- original structure mappings

Outputs:

- rebuilt EPUB
- reconstruction validation report

### Phase 3: Operations

Inputs:

- command or TUI operator action

Outputs:

- structured events
- MLflow runs and artifacts
- cleanup plans and reports

## Resume Model

- Each stage must checkpoint on stable boundaries.
- Chapter translation checkpoints are keyed by `release_id`, `run_id`, `chapter_number`, and `pass_name`.
- Rebuild and cleanup workflows must be rerunnable without corrupting authority state.
- A failed stage may be rerun in isolation if its upstream hashes remain valid.

## Failure Model

- Validation failures produce inspectable reports instead of silent fallback.
- Structure failures are hard stops for translation/reconstruction.
- Upstream hash changes invalidate downstream packet and translation artifacts.
- Cleanup operations must emit a plan before destructive deletion logic is executed by orchestration.
