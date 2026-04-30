# Task 20c: Chapter Manifest + Directory Scan Cache

## Milestone And Depends On

Milestone: M20C

Depends on: M20B

## Goal

Reduce repeated full-directory scans by creating a reusable chapter manifest and shared chapter enumeration helper for preprocessing, packet building, translation range resolution, and reconstruction.

## Scope

In:
- Add a chapter manifest generated or refreshed from extracted chapter artifacts.
- Add a shared helper for listing chapter files and chapter numbers with optional range filtering.
- Replace repeated local `glob("chapter-*.json")` enumeration in hot paths.
- Preserve behavior when no manifest exists by falling back to scanning and rebuilding it.

Out:
- Changing extracted chapter artifact format.
- Changing database schema unless a small metadata table is required by the LLD.
- Adding a background indexer.
- Removing existing JSON artifacts.

## Owned Files Or Modules

- `src/resemantica/epub/extractor.py`
- `src/resemantica/settings.py` if a path is added
- `src/resemantica/chapters/` or a similar shared module
- Preprocessing, packets, orchestration, and reconstruction callers that enumerate chapters
- `docs/20-lld/lld-20c-chapter-manifest-and-scan-cache.md`

## Interfaces To Satisfy

- Add `list_extracted_chapters(paths, *, chapter_start: int | None = None, chapter_end: int | None = None) -> list[ChapterRef]`.
- `ChapterRef` includes `chapter_number`, `chapter_path`, `placeholder_path`, `source_document_path`, and `chapter_source_hash` when available.
- Manifest path: `artifacts/releases/{release_id}/extracted/chapter-manifest.json`.
- Callers must produce identical ordering to current numeric chapter sort.

## Tests Or Smoke Checks

- Unit test manifest creation after extraction.
- Unit test helper falls back to scan if manifest is missing.
- Unit test range filtering preserves numeric ordering.
- Regression tests for preprocessing, packets, translation range, and reconstruction continue to pass.
- Run `uv run pytest tests/epub tests/orchestration tests/packets tests/summaries tests/glossary tests/idioms tests/graph`.
- Run `uv run ruff check src tests`.

## Done Criteria

- Repeated chapter enumeration uses the shared helper in hot paths.
- Manifest is deterministic and regenerated when extraction runs.
- Missing manifest does not break existing releases.
- Tests cover manifest and fallback behavior.
