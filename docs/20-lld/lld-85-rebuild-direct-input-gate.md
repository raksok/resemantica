# LLD 85: Rebuild Direct-Input Gate

## Summary

EPUB reconstruction gates on the durable inputs it consumes: extracted chapters, explicit non-story classification, placeholder maps, and complete final Pass 2/3 block coverage. Historical glossary votes, summary artifacts, graph snapshots, and packet artifacts remain gates for the stages that consume them, but do not block reconstruction after final translations exist.

## Rebuild Scope

After validating the extracted manifest and selected chapter files:

1. Read `summary_drafts.is_story_chapter = 0` only to identify explicitly non-story chapters.
2. Treat every unclassified chapter as translation-required.
3. Skip an explicitly non-story chapter only when it has no Pass 2/3 artifact.
4. Audit any translated non-story chapter alongside all translation-required chapters.
5. Require each audited chapter's placeholder map and exact, non-empty final block coverage.

The orchestration gate and the independent rebuild preflight apply the same chapter policy. The preflight remains the final defense before the reconstruction work tree or EPUB is mutated.

## Compatibility

No command, configuration, database, event, or artifact schema changes. Retrying a failed `epub-rebuild` stage remains a legal same-stage transition. Existing generated review files and unresolved preprocessing rows are not deleted or altered.

## Decision Log

- Chosen: gate reconstruction on direct durable inputs.
- Rejected: require pristine historical pipeline state, because those artifacts are not read during reconstruction and final Pass 2/3 output is already authoritative.
- Rejected: downgrade stale upstream state to rebuild warnings, because it would add noisy diagnostics unrelated to the requested operation.

## Tests

- Complete final translations pass despite unresolved glossary votes, missing summary artifacts, and absent graph or packet state.
- Missing extracted inputs, placeholder maps, or final block mappings still fail.
- Explicit non-story chapters without translations remain skippable; translated non-story chapters remain audited.
- Unclassified chapters require final translation artifacts.
