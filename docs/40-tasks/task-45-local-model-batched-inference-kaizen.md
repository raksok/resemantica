# Task 45: Local Model-Batched Inference Kaizen

## Milestone
M45

## Depends On
M20D, M42, M44

## Goal
Reduce model swapping for local inference servers that can keep only one model loaded at a time.

## Scope
- Make model-batched translation range execution the default through configuration.
- Preserve `--batched-model-order` as a force-enable CLI override.
- Ensure missing CLI batched flags fall back to config instead of forcing `False`.
- Split summary preprocessing into analyst-model Chinese work first, then translator-model English derivation.
- Keep glossary and idiom translation loops unchanged because they already run model-first.
- Keep production `STAGE_ORDER` unchanged.

## Owned Files Or Modules
- `resemantica.toml`
- `src/resemantica/settings.py`
- `src/resemantica/cli.py`
- `src/resemantica/orchestration/runner.py`
- `src/resemantica/summaries/pipeline.py`
- `tests/orchestration/test_batched_translation.py`
- `tests/cli/test_cli_dispatch.py`
- `tests/summaries/test_summary_pipeline.py`
- `docs/20-lld/lld-45-local-model-batched-inference-kaizen.md`

## Interfaces To Satisfy
- `translation.batched_model_order` defaults to `true`.
- CLI absence of `--batched-model-order` passes `None`; explicit flag passes `True`.
- Runner uses config when batched option is `None`.
- Summary artifacts keep `chapter-*-zh.json` and `chapter-*-en.json` with the same returned `chapter_artifacts` shape after completion.

## Tests Or Smoke Checks
- Batched translation range runs all pass1 calls, then all pass2 calls, then all pass3 calls when enabled by config default.
- CLI parser tests prove missing batched flag is `None` and explicit `-b` is `True`.
- Summary pipeline test proves English derivation starts only after all Chinese summary generation and validation calls complete.
- Run focused orchestration, CLI dispatch, and summary tests, then Ruff and mypy on touched files.

## Done Criteria
- Production and translate-range default to local-friendly model-batched translation unless config disables it.
- Summary preprocessing no longer switches analyst to translator and back for every chapter.
- Existing production stage order and artifact contracts remain stable.
