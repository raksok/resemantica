# LLD 14B: Batch Pilot

## Summary

Execute a 10-50 chapter batch pilot to validate the full end-to-end system under real workload conditions, including rebuild integrity and operational readiness.

## Public Interfaces

Operator entrypoints:

- `uv run python -m resemantica.cli run production --release <release_id> --range <start:end>`
- `uv run python -m resemantica.cli tui`

Artifacts:

- pilot validation report
- final translated EPUB
- MLflow run metadata
- event stream

## Data Flow

1. Select a 10-50 chapter range and source EPUB.
2. Run full preprocessing: glossary, summaries, idioms, graph, world model, and packets.
3. Execute batch translation through the production workflow.
4. Monitor progress and handle failures using orchestration, CLI, or TUI.
5. Rebuild the final EPUB from translated outputs.
6. Generate a Pilot Summary Report including quality metrics and validation results.

## Validation Ownership

- final EPUB must pass structural and XHTML validation
- glossary consistency and fidelity are audited via the evaluation system
- failure analysis for any skipped or unstable paragraphs

## Resume And Rerun

- the pilot uses the standard resume and retry logic of the production orchestration layer

## Tests

- production workflow smoke run against a small fixture or dry-run-compatible pilot fixture
- final EPUB structural validation
- pilot report contains warning counts, retry counts, glossary consistency, and failure analysis
- targeted rerun after a simulated recoverable failure
