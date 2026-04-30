# LLD 16: EPUB Reconstruction

## Summary

Task 16 implements Phase 2 reconstruction as a core library workflow. Reconstruction must load translated run artifacts, restore translated text into the original XHTML document structure, validate the result, and package a final translated EPUB. Repackaging unchanged `work/unpacked` content is not sufficient.

## Public Interfaces

CLI:

- `uv run python -m resemantica.cli rebuild-epub --release <id> --run-id <id>`

Python:

- `rebuild_chapter_xhtml(source_xhtml, chapter_records, translated_blocks, placeholder_map) -> ChapterRebuildResult`
- `rebuild_translated_epub(release_id, run_id, config=None, output_path=None) -> RebuildResult`
- `validate_reconstruction(...) -> ValidationReport`
- `OrchestrationRunner.run_stage("epub-rebuild", run_id=...)`

## Artifact Inputs

Required:

- unpacked source EPUB under `artifacts/releases/{release_id}/work/unpacked`
- extracted chapter JSON under `artifacts/releases/{release_id}/extracted/chapters`
- placeholder map JSON under `artifacts/releases/{release_id}/extracted/placeholders`
- translated run artifacts under `artifacts/releases/{release_id}/runs/{run_id}/translation`

Translation selection order:

1. Use pass3 `final_output` when a valid pass3 artifact exists.
2. Otherwise use pass2 `restored_text_en`.
3. Pass1 output is not valid final reconstruction input.

## Artifact Outputs

Write reconstruction outputs under:

```text
artifacts/releases/{release_id}/runs/{run_id}/reconstruction/
  chapters/
    chapter-{chapter_number}.xhtml
  validation-report.json
  manifest.json
```

The final EPUB should be written to a stable release/run path, for example:

```text
artifacts/releases/{release_id}/runs/{run_id}/reconstruction/reconstructed.epub
```

## Chapter Rebuild Flow

1. Load extracted chapter records and sort by `block_order`, then `segment_order`.
2. Load the original XHTML document referenced by `source_document_path`.
3. Load the final translated block map for the chapter.
4. Reassemble split segments by `parent_block_id` and `segment_order`.
5. For each source block, inject translated text into the matching original text-bearing element.
6. Preserve original XHTML tags, attributes, namespaces, document order, and non-text assets.
7. Serialize the rebuilt XHTML.
8. Validate the rebuilt XHTML before packaging.

The model output must never be parsed as trusted XHTML. The original source document and placeholder map remain the structure authority.

## Validation Report Schema

The reconstruction validation report must include:

- `report_id`
- `report_scope`
- `release_id`
- `run_id`
- `chapter_number` nullable
- `validation_type = "reconstruction"`
- `status`
- `severity`
- `flags`
- `artifact_refs`
- `generated_at`
- `schema_version`

Chapter-level flags should include:

- `missing_translation`
- `unmapped_block`
- `placeholder_restoration_failed`
- `xhtml_parse_failed`
- `packaging_failed`

## Packaging Flow

1. Copy the unpacked EPUB tree into a reconstruction work directory.
2. Replace only chapter XHTML files that have rebuilt chapter output.
3. Preserve `mimetype` as the first stored ZIP entry.
4. Deflate all other entries.
5. Write final EPUB.
6. Emit `artifact_written` and `validation_failed` events through orchestration.

## Failure Policy

- Missing translated blocks fail reconstruction unless explicitly marked skipped with reason.
- Placeholder restoration failures are hard failures.
- XHTML parse failures are hard failures.
- Packaging failures are hard failures.
- Non-critical `epubcheck` warnings may be recorded as warnings if the EPUB is otherwise readable.

## Tests

- `rebuild_chapter_xhtml()` preserves original tags and attributes while replacing text.
- pass3 output is preferred over pass2 output.
- pass2 is used when pass3 is disabled or missing.
- segment output is concatenated in source order.
- missing translation produces a failed validation report.
- final EPUB contains rebuilt XHTML, not unchanged source XHTML.

## Migration Notes

Current drift to fix:

- `rebuild_epub()` only repackages `unpacked_dir`.
- `rebuild_chapter_xhtml()` does not exist.
- `rebuild-epub` is not run-aware.
- No reconstruction validation report exists.
