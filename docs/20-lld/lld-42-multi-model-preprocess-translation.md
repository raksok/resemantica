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

## Pipeline Behavior
Glossary translation:
1. Load pending candidates using the existing translation query.
2. For each model in effective preprocess translator order, translate every pending candidate.
3. Save or replace that model's vote for the candidate.
4. Resolve each candidate from its votes.
5. Write the canonical translation only for resolved candidates.
6. Leave unresolved candidates for review.

Idiom translation:
1. Load pending idiom candidates after detection.
2. For each model, translate every candidate's rendering and meaning.
3. Save votes with `vote_kind = 'rendering'` and `vote_kind = 'meaning'`.
4. Resolve rendering and meaning independently.
5. Write canonical idiom fields only when rendering resolves. Meaning may resolve independently, but unresolved meaning should not block promotion if rendering is resolved.

Review workflow:
- `glossary-review` includes an `alternatives` array for each translated or unresolved candidate.
- `idiom-review` includes an `alternatives` array for each translated or unresolved candidate.
- Human review override remains the final authority and writes the existing canonical fields.

## Testing
- Settings tests cover configured lists, omitted lists, and empty lists.
- Repository tests cover idempotent vote upserts and vote listing order.
- Glossary pipeline tests cover single-model compatibility, exact consensus, majority consensus, unresolved disagreement, review alternatives, and model-batched call order.
- Idiom pipeline tests cover rendering vote resolution, meaning vote resolution, unresolved rendering blocking promotion, and review alternatives.

## Out Of Scope
- Per-stage translator lists.
- LLM picker model.
- Metric-driven automatic selection.
- Full COMET/XCOMET/CometKiwi integration.
- Changes to downstream packet or translation pass contracts.
