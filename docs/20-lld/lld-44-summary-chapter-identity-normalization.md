# LLD 44: Summary Chapter Identity Normalization

## Summary
EPUB filenames and visible chapter headings are not authoritative. Extraction already assigns chapter numbers from OPF spine order, and downstream packet, translation, and rebuild artifacts depend on that identity. Summary preprocessing will therefore normalize LLM-returned chapter numbers to the extracted chapter number and preserve any disagreement as warnings.

## Behavior
- `chapter_payload["chapter_number"]` remains canonical.
- The structured summary prompt explicitly tells the model to echo the canonical pipeline chapter number even if filename/title text disagrees.
- After parsing the structured summary, the generator compares:
  - canonical extracted chapter number
  - LLM-returned `chapter_number`
  - numeric hints from `source_document_path`
  - numeric hints from the first source-text heading
- If the LLM-returned number differs, the generator rewrites it to canonical before validation and records a warning.
- If source filename or heading hints differ, they are recorded as warnings only.

## Validation
Future-knowledge validation keeps blocking references to chapters greater than the canonical chapter, except for the visible source heading number detected from the chapter text. This allows summaries to mention an in-file heading like `第12章` while processing canonical spine chapter 4.

## Events And Artifacts
- Emit `preprocess-summaries.chapter_identity_warning` when warnings exist.
- Add `warnings` to `chapter-*-zh.json`.
- Add `warnings` to the chapter result metadata returned by `preprocess_summaries`.

## Out Of Scope
- Renumbering extracted artifacts.
- Reordering OPF spine entries.
- Automatic repair of malformed EPUB metadata.
