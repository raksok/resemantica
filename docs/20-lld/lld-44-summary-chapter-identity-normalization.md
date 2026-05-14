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
- The LLM content-validation prompt receives the recorded identity warnings as context, so it does not re-flag accepted filename or visible-heading disagreements as content problems.
- Fenced JSON returned by the content validator is accepted defensively, even though the prompt asks for raw JSON.

## Validation
Future-knowledge validation keeps blocking references to chapters greater than the canonical chapter, except for the visible source heading number detected from the chapter text. This allows summaries to mention an in-file heading like `第12章` while processing canonical spine chapter 4.

LLM content-validation `flags` remain validation warnings/events. LLM content-validation `warnings` are preserved in artifacts for review but are not emitted as blocking validation-warning events.

## Events And Artifacts
- Emit `preprocess-summaries.chapter_identity_warning` when warnings exist.
- `preprocess-summaries.chapter_identity_warning` includes a non-empty human-readable message summarizing the mismatch.
- Add `warnings` to `chapter-*-zh.json`.
- Add `llm_validation_warnings` to `chapter-*-zh.json` alongside `llm_validation_flags`.
- Add `warnings` to the chapter result metadata returned by `preprocess_summaries`.

## Out Of Scope
- Renumbering extracted artifacts.
- Reordering OPF spine entries.
- Automatic repair of malformed EPUB metadata.
