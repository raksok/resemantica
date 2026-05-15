# Task 47: Translation Context Kaizen

## Milestone
M47

## Depends On
M8 (Chapter Packets), M9 (Pass 3 + Risk Handling), M46 (CSV Review + Glossary-Aware Translation Cache)

## Goal

Standardize paragraph bundle context across translation passes so richer context improves fidelity without causing chapters or successful blocks to be skipped when packet context is missing.

## Scope

In:

- Bundle context formatters for Pass 1, Pass 2, and Pass 3
- Enriched idiom context with meanings and usage notes
- Pass 2 alias, idiom, relationship, continuity, and retrieval evidence context
- Pass 3 preservation constraints and glossary target-term integrity validation
- Bundle-informed risk fixes for pronouns, titles, and reveal-gated relationships
- Pass 3 `force=True` cache bypass
- Best-effort packet metadata lookup for translation checkpoint hashes
- Tests and docs

Out:

- Packet schema changes
- New glossary or idiom discovery logic
- Changes to Pass 2 JSON response schema
- Changes to Pass 3 plain-text response contract

## Owned Files Or Modules

- `src/resemantica/translation/bundle_context.py`
- `src/resemantica/translation/pass2.py`
- `src/resemantica/translation/pass3.py`
- `src/resemantica/translation/pipeline.py`
- `src/resemantica/orchestration/runner.py`
- `src/resemantica/llm/prompts/translate_pass1.txt`
- `src/resemantica/llm/prompts/translate_pass2.txt`
- `src/resemantica/llm/prompts/translate_pass3.txt`
- `tests/translation/test_bundle_context.py`
- `tests/translation/test_pass2_glossary_context.py`
- `tests/translation/test_pass3_and_risk.py`
- `tests/orchestration/test_batched_translation.py`
- `docs/20-lld/lld-47-translation-context-kaizen.md`
- `docs/40-tasks/task-47-translation-context-kaizen.md`

## Interfaces To Satisfy

- Pass 1 accepts empty context and still translates every extracted record.
- Pass 2 prompt context includes terminology, aliases, idioms, relationships, continuity, and retrieval evidence when a bundle is present.
- Pass 3 prompt context includes preservation constraints and validates glossary target terms.
- `translate_chapter_pass3(..., force=True)` bypasses a successful Pass 3 checkpoint.
- Missing packet metadata or bundle files only produce warnings/events and empty context.

## Tests Or Smoke Checks

- `tests/translation/test_bundle_context.py`
- `tests/translation/test_pass2_glossary_context.py`
- `tests/translation/test_pass3_and_risk.py`
- `tests/translation/test_translate_chapter.py`
- `tests/orchestration/test_batched_translation.py`

## Done Criteria

- [ ] Pass 1, Pass 2, and Pass 3 use standardized bundle formatters
- [ ] Empty or missing bundle context never skips a chapter
- [ ] Bundle-informed risk computes pronouns from Pass 2 output
- [ ] Title/honorific glossary entries contribute title risk
- [ ] Ordinary local relationships do not trigger reveal risk
- [ ] Pass 3 force bypasses cache reuse
- [ ] Prompt versions are bumped
- [ ] Ruff, mypy, and targeted pytest pass
