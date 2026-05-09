# Task 42: Multi-Model Preprocess Translation

## Milestone
M42

## Depends On
M3, M5, M40, M41

## Goal
Reduce glossary and idiom pollution risk by translating preprocess candidates with a configurable set of translator models, resolving only clear consensus automatically, and routing disagreement through the existing review workflows.

## Scope
- Add configurable preprocess translator model names with backward-compatible single-model behavior.
- Store per-model translation votes for glossary candidates and idiom candidates.
- Resolve glossary and idiom translations by deterministic consensus before promotion.
- Include unresolved model alternatives in glossary and idiom review JSON.
- Keep downstream locked glossary, idiom policy, packets, summaries, and translation pass interfaces unchanged.

## Owned Files Or Modules
- `src/resemantica/settings.py`
- `src/resemantica/db/sqlite.py`
- `src/resemantica/db/glossary_repo.py`
- `src/resemantica/db/idiom_repo.py`
- `src/resemantica/glossary/pipeline.py`
- `src/resemantica/idioms/pipeline.py`
- `tests/glossary/`
- `tests/idioms/`
- `tests/test_settings_models.py`
- `docs/20-lld/lld-42-multi-model-preprocess-translation.md`

## Interfaces To Satisfy
- Config accepts optional `models.preprocess_translator_names = ["model-a", "model-b", "model-c"]`.
- If `preprocess_translator_names` is omitted or empty, preprocess translation uses `[models.translator_name]`.
- `preprocess glossary-translate` and `preprocess idioms` remain the public CLI entrypoints.
- Existing canonical fields remain the only downstream source of truth:
  - glossary: `candidate_translation_en`
  - idioms: `preferred_rendering_en`, `meaning_en`
- Review JSON includes `alternatives` for unresolved candidates without requiring users to edit a new artifact type.

## Tests Or Smoke Checks
- Config parsing defaults to `[translator_name]` when no multi-model list is configured.
- Glossary exact consensus resolves to `translated`.
- Glossary majority consensus resolves to `translated`.
- Glossary disagreement remains unpromotable and appears in review alternatives.
- Idiom rendering and meaning votes are stored per model.
- Idiom disagreement blocks promotion until review override.
- Model calls are batched by model first, then candidate.
- Existing single-model glossary and idiom pipeline tests continue to pass.

## Done Criteria
- Focused glossary, idiom, and settings tests pass.
- Ruff passes for changed source and tests.
- Docs describe the resolver, storage, and operational behavior.
- No hard-coded translator model names are introduced.
