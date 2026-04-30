# Task 16: EPUB Reconstruction (Phase 2)

## Goal

Integrate the logic for injecting translated text into original XHTML structures into the core library, enabling full-novel EPUB reconstruction from the CLI and orchestration layer.

## Scope

In:

- Migrating the XHTML injection logic from `scripts/pilot/run.py` to `src/resemantica/epub/rebuild.py`.
- Ensuring the `epub-rebuild` command correctly handles the full set of translated artifacts.
- Implementing validation to ensure placeholders are correctly restored during reconstruction.
- Exposing the reconstruction step as a formal orchestration stage.

Out:

- Re-implementing the core EPUB packaging logic (already exists in `src/resemantica/epub/rebuild.py`).
- Modifying the placeholder extraction logic in Phase 0.

## Owned Files Or Modules

- `src/resemantica/epub/rebuild.py`
- `src/resemantica/epub/validators.py`
- `src/resemantica/orchestration/runner.py` (to register the stage)

## Interfaces To Satisfy

- `resemantica rebuild-epub --run-id <id>` CLI command.
- `rebuild_chapter_xhtml()` function in `rebuild.py`.
- `ValidationReport` schema for reconstruction status.

## Tests Or Smoke Checks

- Run `resemantica rebuild-epub` on a completed translation run and verify the resulting EPUB opens in a reader.
- Run `epubcheck` on the generated EPUB.
- Verify that placeholders are correctly replaced with their translated equivalents in the final XHTML.

## Done Criteria

- Phase 2 (Reconstruction) is a fully integrated part of the library and orchestration layer.
- The `rebuild-epub` CLI command produces a valid translated EPUB.
- Placeholder restoration is validated and reported.
