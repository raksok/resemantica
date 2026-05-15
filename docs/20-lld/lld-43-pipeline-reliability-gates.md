# LLD 43: Pipeline Reliability Gates

## Summary
Production orchestration now performs deterministic preflight checks before every production stage. The checks do not run extraction and do not alter `STAGE_ORDER`; they verify that expected extracted, summary, graph, packet, translation, and rebuild inputs already exist before allowing the next stage to start.

## Gate Scope
- `preprocess-summaries`: extracted chapter manifest and selected chapter files.
- `preprocess-glossary`: extraction plus unresolved preprocess translation vote checks; skips chapters marked `is_story_chapter = 0` in `summary_drafts` (if summaries exist).
- `preprocess-idioms` and `preprocess-graph`: extraction, summary story metadata, required story summaries, and unresolved vote checks.
- `packets-build`: summary inputs, graph snapshot inputs, and unresolved vote checks.
- `translate-range`: packet metadata and packet/bundle artifacts for selected story chapters.
- `epub-rebuild`: translated pass artifacts and placeholder maps for selected story chapters, plus selected non-story chapters that already have pass artifacts.

## Non-Story Chapters
Downstream gates use `summary_drafts.is_story_chapter = 0` as the authoritative non-story marker. Non-story chapters may omit packets and translation pass artifacts. Rebuild leaves their original XHTML untouched only when no translated blocks exist; if a selected non-story chapter has pass2/pass3 artifacts, the gate validates those artifacts and rebuild consumes them.

Chapters with **no `summary_drafts` row at all** (e.g., excluded by `exclude_chapter_patterns` in the summaries pipeline) are silently skipped by the gate — they are not added to the `story_chapters` list and do not trigger gate failures. Downstream stages handle missing data gracefully (e.g., packets skips with `missing_story_so_far_summary`).

## Unresolved Preprocess Votes

The gate checks for unresolved `glossary_translation_votes` and `idiom_translation_votes` before allowing `preprocess-idioms`, `preprocess-graph`, and downstream stages to run.

For glossary votes, the gate applies the same `llm_keep` filter as the translation pipeline: candidates with `llm_keep = 0` (rejected by LLM evaluation) are excluded. This prevents a permanent gate deadlock where rejected candidates have orphaned unresolved votes that no downstream stage can resolve. Candidates with `llm_keep IS NULL` (legacy, never evaluated) are still checked.

## Failure Behavior
Gate failures are normal orchestration failures:
- `StageResult(success=False, message="Gate failed: ...")`
- run state marked failed for that stage
- a persisted `{stage}.gate_failed` event with the full gate report in payload

This gives operators a short feedback loop: fix upstream artifacts, complete review/promotion, or narrow chapter scope, then re-run. Re-running `run production` for the same release/run retries the failed gate stage using the saved chapter scope instead of starting over at `preprocess-summaries`.

## Dry Run
`run production --dry-run` returns the usual ordered production plan. Each stage also includes a `gate` object with `success`, `failures`, `warnings`, and metadata such as selected chapter numbers.

## Out Of Scope
- Automatic extraction from production.
- Bypass flags.
- Rewriting the packet builder or translation pipeline scheduling.
- LLM-based diagnostics for gate failures.
