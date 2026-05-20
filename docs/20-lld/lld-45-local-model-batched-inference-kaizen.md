# LLD 45: Local Model-Batched Inference Kaizen

## Summary
Local inference servers often unload the active model when a request targets another model. Repeated translator to analyst switching therefore dominates long runs. This slice makes the existing translation batched path the default and removes summary preprocessing's per-chapter analyst to translator switch.

## Translation Defaults
`translation.batched_model_order` defaults to `true`. The runner already accepts `batched_model_order: bool | None`; `None` means "use config." CLI dispatch must preserve that by passing:

- `None` when no batched flag is present.
- `True` when `--batched`, `-b`, or `--batched-model-order` is present.

The batched range order remains:

```text
pass1 translator for all selected chapters
pass2 analyst for all selected chapters
pass3 analyst for all selected chapters
```

## Summary Preprocessing
`preprocess_summaries()` runs in three internal phases:

1. Chinese chapter-local phase: analyst-model structured summary generation, Chinese validation, and validated `chapter_summary_zh_structured` / `chapter_summary_zh_short` rows.
2. Ordered story assembly phase: full `story_so_far_zh`, compact `story_so_far_zh_compact`, and `chapter-*-zh.json`.
3. English phase: translator-model derivation of `chapter_summary_en_short` and `story_so_far_en`, derived rows, and `chapter-*-en.json`.

The function keeps the same public entrypoint and returned `chapter_artifacts` shape. Skipped chapters remain skipped during the Chinese phase and do not enqueue story or English work. The two LLM-heavy phases (Chinese generation/validation and English derivation) can use `summaries.chapter_concurrency`; ordered story assembly remains sequential so continuity rows are deterministic.

## Events And Artifacts
- Chinese artifacts are written during ordered story assembly after full and compact continuity rows are saved.
- English artifacts are written during the translator phase.
- Ordered story assembly and English story derivation emit `preprocess-summaries.summary_generation_started` and `preprocess-summaries.summary_generation_completed` for `story_so_far_zh`, `story_so_far_zh_compact`, and `story_so_far_en` before the chapter completion event.
- `preprocess-summaries.chapter_completed` is emitted after the English artifact is written for each processed chapter.
- Final completion counters keep the same processed/skipped semantics.

## Out Of Scope
- A global cross-stage model scheduler.
- Reordering production `STAGE_ORDER`.
- Changing glossary or idiom multi-model translation loops.
- Changing summary prompts, validation rules, or artifact schema versions.
