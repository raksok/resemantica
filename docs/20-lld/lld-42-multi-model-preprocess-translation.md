# LLD 42: Multi-Model Preprocess Translation

## Summary
Glossary and idiom translations become consensus-resolved preprocess artifacts. Instead of trusting one translator model, each pending candidate is translated by every configured preprocess translator. The pipeline stores each model output as a vote, writes the existing canonical translation fields only when deterministic consensus is clear, and routes disagreements through the current review files.

This design keeps downstream consumers unchanged while reducing the chance that one bad translator output pollutes locked glossary entries, idiom policies, summaries, packets, and later translation passes.

## Configuration
`models.preprocess_translator_names` is optional.

```toml
[models]
translator_name = "HY-MT1.5-7B"
preprocess_translator_names = [
  "HY-MT1.5-7B",
  "TranslateGemma-model-name",
  "third-model-name"
]
```

Rules:
- If omitted or empty, effective preprocess translators are `[models.translator_name]`.
- Names are runtime model IDs only; code must not hard-code HY-MT, TranslateGemma, Qwen, or Mistral.
- The same list is used for glossary translation and idiom translation unless a later task introduces per-stage override lists.
- Glossary translation vote calls do not set a glossary-specific completion cap.

## Storage
Add vote tables that preserve model alternatives without changing canonical candidate fields.

Glossary vote fields:
- `candidate_id`
- `release_id`
- `translation_run_id`
- `model_name`
- `prompt_version`
- `raw_output`
- `cleaned_output`
- `normalized_output`
- `resolution_status`

Glossary vote lookup is indexed for resume with `(release_id, translation_run_id, model_name, candidate_id)`. The repository exposes scoped helpers to list candidate IDs that already have votes for a model, count votes by model, and reconstruct the resume candidate ID set from saved votes during `vote_resume` loading.

Idiom vote fields:
- `candidate_id`
- `release_id`
- `translation_run_id`
- `model_name`
- `prompt_version`
- `vote_kind` (`rendering` or `meaning`)
- `raw_output`
- `cleaned_output`
- `normalized_output`
- `resolution_status`

Idiom vote lookup is indexed for resume with `(release_id, translation_run_id, model_name, candidate_id, vote_kind)`. The repository exposes scoped helpers to list candidate IDs that already have votes for a model and vote kind, count candidates with complete model vote pairs, reconstruct the resume candidate ID set from saved votes, and hydrate candidates by candidate ID batches.

The existing canonical fields remain authoritative after resolution:
- `glossary_candidates.candidate_translation_en`
- `idiom_candidates.preferred_rendering_en`
- `idiom_candidates.meaning_en`

## Resolver
The resolver is deterministic and conservative.

- Single-model mode resolves exactly as today.
- If all configured translator outputs normalize to the same value, resolve as `consensus`.
- If at least two of three configured outputs normalize to the same value, resolve as `majority`.
- If no normalized value has majority, leave the candidate unresolved.
- Unresolved glossary candidates keep `candidate_translation_en = NULL` or empty and do not enter promotion.
- Unresolved idiom candidates keep `candidate_status = 'discovered'` and do not enter promotion.
- Vote rows record `resolution_status` so review and diagnostics can explain why a candidate did or did not resolve.

Tie-breaking:
- Use the first configured model's cleaned output as display text when its normalized output is the winning normalized value.
- If the first configured model is not in the winning group, use the earliest configured model in the winning group.
- Do not use a generalist picker model in v1.
- Do not use COMET, XCOMET, or CometKiwi scores to override disagreement in v1.

Glossary resolution also has a no-LLM replay path. `preprocess
glossary-resolve` loads saved glossary vote IDs for the selected release/run,
hydrates candidates by primary key, and re-applies the deterministic resolver to
candidate canonical fields. This is the operator path for improved voter logic
or style-rule changes when the expensive model vote rows are still valid.

## Pipeline Behavior
Glossary translation:
1. Load pending candidates using the existing translation query.
2. For each model in effective preprocess translator order, translate pending candidates without an existing vote for the same release, run, and model unless `force=True`.
3. Generate each glossary vote without a glossary-specific `max_tokens` cap.
4. Save or replace that model's vote for the candidate.
5. Resolve each candidate from its votes.
6. Write the canonical translation only for resolved candidates.
7. Leave unresolved candidates for review.

Vote-level resume is keyed by `(release_id, translation_run_id, model_name)`. On rerun, each configured model receives only candidates that do not already have a vote for that release, run, and model. Completed votes from earlier model batches remain valid durable state and are not discarded by later failures.

Resolve-only uses the same `(release_id, translation_run_id)` vote scope but
skips model work entirely. It updates vote `resolution_status`, writes resolved
candidate canonical translations, clears stale translations from the same run
that are no longer resolvable, and writes `candidates.json`.

When rerunning an interrupted translation run, the loader may use `vote_resume` instead of the canonical pending scan if a prior `translate.started` event has a pending count and one configured model already has exactly that many votes. The `vote_resume` strategy reconstructs the candidate ID universe from saved votes, emits loading completion after that indexed ID work, and fetches candidate rows lazily in `candidate_id` primary-key chunks during missing-vote generation and resolution. Lazy hydration must stay ID-first; it must not devolve into release-wide `glossary_candidates` scans before per-model resume can skip completed votes.

If a local model server crashes during a model batch, for example a llama.cpp-backed Gemma process exit, the pipeline emits `preprocess-glossary.translate.failed` and stops the current run. Votes saved before the crash remain in SQLite. Operators can rerun with the same release, run, and configuration, without `--force`, and the crashed model resumes from its first missing vote. Removing the crashing model from `models.preprocess_translator_names` is an intentional configuration change that abandons that model's missing votes and resolves from the remaining configured model votes.

Glossary translation events are scoped to the real work boundaries:
- `preprocess-glossary.translate.loading_started` before opening/preparing the release DB and loading pending candidates.
- `preprocess-glossary.translate.loading_completed` after pending candidates are loaded, with elapsed load timings and `load_strategy`; for `vote_resume`, this means the candidate ID universe is loaded, not that every candidate row has been hydrated.
- `preprocess-glossary.translate.started` after pending candidates are loaded.
- `preprocess-glossary.translate.model_started` and `.model_completed` around each model's missing-vote batch, with `model_name`, `pending_count`, `candidate_count`, and `skipped_count`.
- `preprocess-glossary.translate.resolution.started` before vote resolution begins.
- `preprocess-glossary.translate.chapter_started` and `.chapter_completed` during resolution/save, not during vote generation.
- `preprocess-glossary.translate.unresolved` with severity `warning` for each candidate without a resolvable vote.
- `preprocess-glossary.translate.failed` with severity `error`, `model_name`, `candidate_id`, `phase`, and `error` for model voting or resolution failures.
- `preprocess-glossary.translate.resolution.completed`, `.snapshot.artifact_written`, and `.completed` after resolution, `candidates.json` write, and phase completion respectively.

Idiom translation:
1. Load pending idiom candidates after detection.
2. For each model, translate only missing vote kinds for each candidate unless `force=True`.
3. Save votes with `vote_kind = 'rendering'` and `vote_kind = 'meaning'`.
4. Resolve rendering and meaning independently.
5. Write canonical idiom fields only when rendering resolves. Meaning may resolve independently, but unresolved meaning should not block promotion if rendering is resolved.

Idiom vote-level resume is keyed by `(release_id, translation_run_id, model_name, candidate_id, vote_kind)`. A complete model vote for idioms means both a `rendering` and a `meaning` vote exist for a candidate. On rerun, each configured model receives only candidates missing at least one of those vote kinds, and the generator calls only the missing prompt(s). Existing rendering votes do not force meaning regeneration, and existing meaning votes do not force rendering regeneration.

When rerunning an interrupted idiom translation run, the loader may use `vote_resume` instead of the canonical pending scan if a prior `preprocess-idioms.translate.started` event has a pending count and one configured model has complete vote pairs for exactly that many candidates. `vote_resume` reconstructs the candidate ID universe from saved idiom votes, emits loading completion after that indexed ID work, and hydrates candidate rows lazily by `candidate_id` chunks during missing-vote generation and resolution. If saved vote pairs are incomplete, the loader falls back to the canonical pending scan. `force=True` bypasses existing-vote skips and regenerates both vote kinds.

Idiom translation events mirror glossary where applicable:
- `preprocess-idioms.translate.loading_started` before loading pending candidates.
- `preprocess-idioms.translate.loading_completed` with `load_strategy`, `previous_pending_count`, `resume_vote_model`, complete-pair counts by model, and load timings.
- `preprocess-idioms.translate.started` after pending candidates or resume candidate IDs are loaded.
- `preprocess-idioms.translate.model_started` and `.model_completed` around each model's missing-vote work, with `model_name`, `pending_count`, `candidate_count`, `skipped_count`, and `vote_lookup_seconds` on start.
- `preprocess-idioms.translate.resolution.started`, `.chapter_started`, `.chapter_completed`, `.unresolved`, `.resolution.completed`, and `.completed` during saved-vote resolution and phase completion.

If idiom translation crashes during a model batch, votes saved before the crash remain the resume authority as long as the translate phase checkpoint has not advanced to `translated`. `preprocess_idioms(..., resume=True)` still skips the whole translate phase once the checkpoint is `translated` or `promoted`.

Review workflow:
- `glossary-review` includes an `alternatives` array for each translated or unresolved candidate.
- `idiom-review` includes an `alternatives` array for each translated or unresolved candidate.
- Human review override remains the final authority and writes the existing canonical fields.

## Testing
- Settings tests cover configured lists, omitted lists, and empty lists.
- Repository tests cover idempotent vote upserts and vote listing order.
- Glossary pipeline tests cover single-model compatibility, exact consensus, majority consensus, unresolved disagreement, review alternatives, and model-batched call order.
- Idiom pipeline tests cover rendering vote resolution, meaning vote resolution, unresolved rendering blocking promotion, review alternatives, complete vote-pair skips on rerun, partial vote-kind resume, `vote_resume` loading, incomplete-vote fallback, and `force=True` regeneration.

## Out Of Scope
- Per-stage translator lists.
- LLM picker model.
- Metric-driven automatic selection.
- Full COMET/XCOMET/CometKiwi integration.
- Changes to downstream packet or translation pass contracts.
