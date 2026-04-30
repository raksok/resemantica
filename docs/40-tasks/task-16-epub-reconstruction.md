# Task 16: EPUB Reconstruction (Phase 2)

## Milestone And Depends On

Milestone: M16

Depends on: M15

## Goal

Make EPUB reconstruction consume translated run artifacts, inject restored translated text into the original XHTML structure, validate the result, and rebuild a translated EPUB through orchestration.

## Scope

In:

- Add `rebuild_chapter_xhtml()` to `src/resemantica/epub/rebuild.py`.
- Add a run-aware `rebuild_translated_epub()` or equivalent library function that loads translated artifacts for a release/run.
- Inject final translated text into the original XHTML block positions without trusting model output as XHTML.
- Prefer pass3 `final_output` when present; otherwise fall back to pass2 `restored_text_en`.
- Reassemble split segments by `parent_block_id` and `segment_order` before injection.
- Validate placeholder restoration, block mapping coverage, XHTML parseability, and packaging integrity.
- Emit a reconstruction `ValidationReport` JSON artifact.
- Wire `rebuild-epub --run-id <id>` and the `epub-rebuild` orchestration stage to the new reconstruction path.

Out:

- Changing translation pass logic.
- Modifying the placeholder extraction logic in Phase 0.
- Adding EPUB reader UI features.

## Owned Files Or Modules

- `src/resemantica/epub/rebuild.py`
- `src/resemantica/epub/validators.py`
- `src/resemantica/orchestration/runner.py` (to register the stage)
- `src/resemantica/cli.py`
- `tests/epub/`
- `tests/orchestration/`

## Interfaces To Satisfy

- `resemantica rebuild-epub --release <id> --run-id <id>` CLI command.
- `rebuild_chapter_xhtml()` function in `rebuild.py`.
- `rebuild_translated_epub()` function or equivalent public reconstruction entrypoint.
- `ValidationReport` schema for reconstruction status.
- `OrchestrationRunner.run_stage("epub-rebuild", run_id=...)`.

## Tests Or Smoke Checks

- Unit test `rebuild_chapter_xhtml()` replaces original block text with translated text while preserving original XHTML tags and attributes.
- Unit test missing translated blocks fail validation unless explicitly skipped with reason.
- Unit test pass3 output is preferred over pass2 output.
- Unit test segment outputs are concatenated by parent block order.
- Run `resemantica rebuild-epub` on a completed translation run and verify the resulting EPUB opens in a reader.
- Run `epubcheck` on the generated EPUB.
- Verify that placeholders are correctly replaced with their translated equivalents in the final XHTML.

## Done Criteria

- Phase 2 (Reconstruction) is a fully integrated part of the library and orchestration layer.
- The `rebuild-epub` CLI command produces a valid translated EPUB.
- Placeholder restoration is validated and reported.
- Reconstruction artifacts are written under the release/run artifact tree and are linked from orchestration events.
- `docs/20-lld/lld-16-epub-reconstruction.md` is implemented and kept in sync.
