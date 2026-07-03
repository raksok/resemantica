# LLD 02: Single-Chapter Translation

## Summary

Implement the smallest translation slice that is worth validating: load one extracted chapter, run Pass 1 and Pass 2, preserve structure placeholders, emit pass artifacts, and checkpoint resume state.

Success means one chapter can be translated end to end with inspectable outputs and no silent structural corruption.

## Public Interfaces

CLI:

- `uv run python -m resemantica.cli translate-chapter --release <release_id> --chapter <n> --run <run_id>`

Python modules:

- `llm.client.LLMClient`
- `llm.prompts.load_prompt()`
- `translation.pass1.translate_pass1()`
- `translation.pass2.translate_pass2()`
- `translation.validators.validate_structure()`
- `translation.validators.validate_basic_fidelity()`
- `translation.checkpoints.save_checkpoint()`

Artifacts:

- pass1 raw output
- pass2 corrected output
- structure validation report
- fidelity report
- checkpoint record

## Data Flow

1. Load extracted chapter blocks for chapter `N`.
2. Resolve locked glossary lookups if available, without requiring glossary authority to exist yet.
3. Load pass prompts and record prompt versions.
4. Run Pass 1 through the shared LLM client on each block with placeholder-safe source text.
5. **Clean Pass 1 output:** strip `<think>`/`<thought>` chain-of-thought artifacts, markdown bold/italic, smart quotes, and label prefixes. If Chinese characters remain in the cleaned output, the block is treated as failed and triggers resegmentation.
6. Restore placeholders using the restoration algorithm defined in `lld-01`: map each opening placeholder `⟦TYPE_N⟧` to its `original_xhtml`, each closing placeholder `⟦/TYPE_N⟧` to `</element>`, and validate closing order against `closing_order`.
7. On structural failure of block `B`:
   a. Split the **original source block** `B` into segments `S1, S2, ...` at sentence boundaries. Assign segment IDs (`ch{NNN}_blk{NNN}_seg{NN}`).
   b. **Pass 1 retries each segment independently** — the source for each retry is the segment text alone, not the original full block.
   c. Segments are processed sequentially. **Pass 2 for segment `S_n` receives: (1) the original full source block `B` as context, (2) the translations of all prior segments `[T_1, ..., T_{n-1}]` to maintain cross-segment coherence (preventing tense, tone, and naming drift), and (3) the current segment draft `S_n` as the correction target.**
   d. On Pass 2 segment success: restore placeholders, validate, and emit artifacts per segment.
   e. Reconstruction phase concatenates all validated segment outputs in order to produce the final block output for `B`.
   f. If any segment fails after retry, the entire block `B` is marked failed.
8. Halt if the retry still fails structural validation.
9. Run Pass 2 through the shared LLM client against source and Pass 1 output. **Pass 2 receives conditional glossary context from paragraph bundles: when `bundle.matched_glossary_entries` is non-empty, a `TERMINOLOGY:` section is prepended to the prompt so the fidelity auditor can check for terminology violations.**
10. Retry Pass 2 block validation failures up to `[translation].pass2_validation_retries` additional attempts before failing the chapter. Retries cover structural, restoration, and fidelity validation failures; prompt budget failures are not retried here.
11. Emit corrected output, prompt metadata, model metadata, and fidelity flags.
12. Persist chapter-level checkpoint state.

## Command Behavior

- `translate-chapter` targets exactly one chapter.
- If valid pass checkpoints exist, reruns skip completed Pass 1, Pass 2, and Pass 3 work by default.
- `--force` ignores pass checkpoints for the requested chapter or range; `--force-pass1` remains a backward-compatible alias.
- If structure validation fails, resegment the failed block at sentence boundaries, retry each segment in Pass 1, then run Pass 2 sequentially with full original block context and prior segment translations against each segment draft before marking the chapter failed.
- Pass 2 retries validation failures at the block task boundary before marking the chapter failed.
- Outputs are written under the run-scoped translation artifact tree.

## Validation Ownership

- placeholder preservation is validated immediately after Pass 1 restoration
- non-empty block output is required for every source block
- Pass 2 may change wording but must preserve placeholders and block mapping
- prompt version and model name are required on every pass artifact

## Resume And Rerun

Checkpoint identity:

- `release_id`
- `run_id`
- `chapter_number`
- `pass_name`
- `source_hash`
- `prompt_version`

Rerun rule:

- if source hash or prompt version changes, prior pass artifacts are stale for that pass and below
- if resegmentation changes block segment identity, dependent segment artifacts are stale and must be regenerated
- range and batched translation both forward `force` consistently into Pass 1, Pass 2, and Pass 3
- `run retry-failed --stage translate-range` retries chapters with failed or incomplete translation checkpoints. It delegates to `translate-range` with the inferred chapter scope and does not force completed pass checkpoints by default.

## Tests

- placeholder-safe chapter translation happy path
- Pass 2 correction path with persisted artifact reuse
- hard stop on restoration failure
- reactive resegmentation on structural failure
- resume from successful Pass 1 without rerunning it

## Out Of Scope

- Pass 3
- chapter packets
- graph retrieval
- full production orchestration
