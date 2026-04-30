# LLD 20c: Chapter Manifest And Scan Cache

## Summary

Add a release-local extracted chapter manifest and shared enumeration helper to replace repeated full-directory scans in hot paths.

## Problem Statement

Many pipelines repeatedly scan and sort `extracted/chapters/chapter-*.json`. That is acceptable for small releases but adds avoidable overhead and duplicated parsing for 1000+ chapters.

## Technical Design

Add a shared module, for example `src/resemantica/chapters/manifest.py`:

```python
@dataclass(slots=True)
class ChapterRef:
    chapter_number: int
    chapter_path: Path
    placeholder_path: Path
    source_document_path: str | None
    chapter_source_hash: str | None

def write_chapter_manifest(paths: DerivedPaths) -> Path: ...

def list_extracted_chapters(
    paths: DerivedPaths,
    *,
    chapter_start: int | None = None,
    chapter_end: int | None = None,
) -> list[ChapterRef]: ...
```

Manifest path:

```text
artifacts/releases/{release_id}/extracted/chapter-manifest.json
```

Manifest rows are sorted by `chapter_number` and include only data that can be derived from extracted chapter JSON files.

## Data Flow

1. `extract_epub()` writes normal chapter artifacts.
2. `extract_epub()` calls `write_chapter_manifest(paths)`.
3. Pipelines call `list_extracted_chapters(paths, ...)`.
4. If manifest is missing or malformed, the helper scans chapter files, rewrites the manifest, and returns refs.

## Call Sites To Convert

Use the helper in:

- preprocessing pipelines and extractors
- packet builder target selection
- orchestration chapter range resolution
- reconstruction loop

Callers that need full chapter payloads still read the chapter JSON file after receiving `ChapterRef`.

## Tests

- Manifest written after extraction.
- Missing manifest fallback scans and rewrites.
- Numeric sort handles `chapter-10.json` after `chapter-2.json`.
- Range filtering returns expected refs.
- Existing stage tests pass without behavior changes.

## Out Of Scope

- Removing extracted chapter JSON files.
- Storing the full chapter payload in the manifest.
- Background cache invalidation.
