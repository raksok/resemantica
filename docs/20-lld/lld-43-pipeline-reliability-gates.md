# LLD 43: Pipeline Reliability Gates

## Summary
Production orchestration now performs deterministic preflight checks before every production stage. The checks do not run extraction and do not alter `STAGE_ORDER`; they verify that expected extracted, summary, graph, packet, translation, and rebuild inputs already exist before allowing the next stage to start.

## Gate Scope
- `preprocess-summaries`: extracted chapter manifest and selected chapter files.
- `preprocess-glossary`: extraction plus unresolved preprocess translation vote checks; skips chapters marked `is_story_chapter = 0` in `summary_drafts` (if summaries exist).
- `preprocess-idioms` and `preprocess-graph`: extraction, summary story metadata, required story summaries, and unresolved vote checks.
- `packets-build`: summary inputs, graph snapshot inputs, and unresolved vote checks.
- `translate-range`: packet metadata and packet/bundle artifacts for selected story chapters.
- `epub-rebuild`: translated pass artifacts and placeholder maps for selected story chapters.

## Non-Story Chapters
Downstream gates use `summary_drafts.is_story_chapter = 0` as the authoritative non-story marker. Non-story chapters may omit packets and translation pass artifacts; rebuild leaves their original XHTML untouched.

## Failure Behavior
Gate failures are normal orchestration failures:
- `StageResult(success=False, message="Gate failed: ...")`
- run state marked failed for that stage
- a persisted `{stage}.gate_failed` event with the full gate report in payload

This gives operators a short feedback loop: fix upstream artifacts, complete review/promotion, or narrow chapter scope, then re-run.

## Dry Run
`run production --dry-run` returns the usual ordered production plan. Each stage also includes a `gate` object with `success`, `failures`, `warnings`, and metadata such as selected chapter numbers.

## Out Of Scope
- Automatic extraction from production.
- Bypass flags.
- Rewriting the packet builder or translation pipeline scheduling.
- LLM-based diagnostics for gate failures.
