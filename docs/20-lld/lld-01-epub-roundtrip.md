# LLD 01: EPUB Round-Trip

## Summary

Build the deterministic EPUB foundation: unpack an EPUB, discover chapter documents, extract stable block data, emit validation artifacts, and rebuild a structurally valid EPUB without translation changes.

Success means the system can safely parse and round-trip a supported EPUB while preserving chapter/block identity and reversible placeholders.

## Public Interfaces

CLI:

- `uv run python -m resemantica.cli epub-roundtrip --input <path> --release <release_id>`

Python modules:

- `epub.extractor.extract_epub()`
- `epub.parser.parse_chapters()`
- `epub.placeholders.build_placeholder_map()`
- `epub.rebuild.rebuild_epub()`
- `epub.validators.validate_extraction()`

Artifacts:

- extracted chapter JSON
- XHTML validation report
- placeholder map JSON files (one per chapter)
- rebuilt EPUB

## Data Flow

1. Resolve input paths and release workspace.
2. Unpack EPUB to a release-scoped working directory.
3. Discover OPF manifest, spine, and candidate chapter XHTML files.
4. Parse chapter XHTML deterministically.
5. Split content into stable ordered blocks and assign `block_id`.
6. Build placeholder-safe restoration mapping for supported inline and block structures.
7. Emit extraction metadata and validation reports.
8. Rebuild the EPUB from extracted structure without translated text changes.

## Data Contracts

Extraction record fields:

- `chapter_id`
- `chapter_number`
- `source_document_path`
- `block_id`
- `block_order`
- `source_text_zh`
- `placeholder_map_ref`
- `chapter_source_hash`
- `schema_version`

Validation report minimum fields:

- `release_id`
- `stage_name`
- `status`
- `errors`
- `warnings`
- `document_path`

Block rules:

- A block is a leaf-level XHTML text element such as `<p>`, `<h1>`-`<h6>`, text-containing `<div>`, `<li>`, `<td>`, and equivalent leaf content containers.
- Non-text elements such as images, rules, and tables become placeholder-bearing blocks when they must round-trip in order.
- Blocks over approximately 1500 characters are split at sentence boundaries.
- `block_id` format is `ch{NNN}_blk{NNN}`, for example `ch003_blk007`.
- **Segment IDs:** When a block is split, each resulting segment receives a segment ID: `ch{NNN}_blk{NNN}_seg{NN}` (e.g., `ch001_blk010_seg01`, `ch001_blk010_seg02`). Segments are ordered and their concatenation must equal the original block text. Unsplit blocks retain `ch{NNN}_blk{NNN}` with no `_seg` suffix.
- Every segment carries a `parent_block_id` field referencing the original block. During reconstruction (Phase 2), segments are concatenated in order under their parent block to produce the final translated block output.

Placeholder rules:

- Placeholder syntax is `⟦TYPE_N⟧`, where `N` is sequential within the block.
- Supported type codes are `B`, `I`, `U`, `S`, `SPAN`, `IMG`, `HR`, `DIV`, `RUBY`, `A`, `TABLE`, and `BR`.
- The placeholder map stores the original element, attributes, nesting position, and restoration order needed to rebuild the source structure.
- The placeholder map is the restoration authority; translated text must never be parsed as trusted XHTML.

Nested tag handling:

- When tags are nested (e.g., `<b><i>text</i></b>`), each inner tag gets its own `⟦TYPE_N⟧` placeholder.
- The placeholder map entry records: `parent_placeholder` (null for top-level), `depth`, and `closing_order` (array of placeholders in reverse opening order — innermost closes first).
- Restoration uses `closing_order` on the outermost parent to reconstruct correct tag nesting deterministically.
- Deep nesting (depth > 3): flatten to the outermost tag placeholder only; inner tags are recorded in the map for inspection but not sent to the model as separate placeholders.

Example placeholder map entry for nesting:

```json
{
  "placeholder": "⟦I_1⟧",
  "element": "i",
  "attributes": {},
  "parent_placeholder": "⟦B_1⟧",
  "depth": 2,
  "closing_order": null
}
```

The outermost parent entry:

```json
{
  "placeholder": "⟦B_1⟧",
  "element": "b",
  "attributes": {},
  "parent_placeholder": null,
  "depth": 1,
  "closing_order": ["⟦I_1⟧", "⟦B_1⟧"]
}
```

Placeholder map storage:

- Physical location: `artifacts/releases/{release_id}/extracted/placeholders/chapter-{chapter_number}.json`
- The `placeholder_map_ref` field on extraction records stores this path.
- Placeholder maps are `immutable_artifact` per `chapter_source_hash`.
- The map is keyed by `block_id`; reconstruction (Phase 2) loads this file by path — no BLOB storage, no SQLite inline storage.

Placeholder map file schema:

```json
{
  "chapter_number": 3,
  "chapter_source_hash": "abc123",
  "schema_version": 1,
  "blocks": {
    "ch003_blk001": [
      {
        "placeholder": "⟦B_1⟧",
        "element": "b",
        "attributes": {"class": "bold"},
        "original_xhtml": "<b class=\"bold\">",
        "parent_placeholder": null,
        "depth": 1,
        "closing_order": ["⟦B_1⟧"]
      },
      {
        "placeholder": "⟦I_1⟧",
        "element": "i",
        "attributes": {},
        "original_xhtml": "<i>",
        "parent_placeholder": "⟦B_1⟧",
        "depth": 2,
        "closing_order": null
      }
    ]
  }
}
```

Each entry in a block's array contains:

- `placeholder` — the `⟦TYPE_N⟧` string as it appears in the extracted text
- `element` — the HTML tag name
- `attributes` — dict of original HTML attributes
- `original_xhtml` — the original opening tag string for restoration
- `parent_placeholder` — null for top-level, or the placeholder of the enclosing parent
- `depth` — nesting depth (1 = top-level)
- `closing_order` — array of placeholders in reverse opening order (innermost first); null for leaf entries that are not the outermost parent of a nesting group

## Validation Ownership

- XHTML parsing and placeholder reversibility are validated inside `epub.validators`.
- Rebuild integrity is checked before emitting success.
- Malformed documents produce reports and a failed stage result.

## Resume And Rerun

- Extraction artifacts are immutable per `chapter_source_hash`.
- A rerun with the same source hash may reuse extracted chapter artifacts.
- Any change to source EPUB path or hash invalidates prior extraction artifacts for that release.

## Tests

- fixture EPUB round-trip success
- malformed XHTML produces readable failure report
- stable `block_id` and `block_order` across rerun
- placeholder restoration reversibility for supported block types
- nested tag placeholder map produces correct `closing_order` and `parent_placeholder`
- nested tag restoration reconstructs correct closing order (innermost first)
- deep nesting (depth > 3) flattens to outermost placeholder only
- 1500-character split behavior at sentence boundaries
- segment ID format (`_seg{NN}` suffix) and ordering
- `parent_block_id` reconstruction from segments
- `block_id` format and reset behavior per chapter

## Out Of Scope

- translation
- glossary discovery
- summary generation
- graph extraction
