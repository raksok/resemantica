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
5. Restore placeholders and validate structure.
6. On structural failure of block `B`:
   a. Split the **original source block** `B` into segments `S1, S2, ...` at sentence boundaries. Assign segment IDs (`ch{NNN}_blk{NNN}_seg{NN}`).
   b. **Pass 1 retries each segment independently** — the source for each retry is the segment text alone, not the original full block.
   c. Segments are processed sequentially. **Pass 2 for segment `S_n` receives: (1) the original full source block `B` as context, (2) the translations of all prior segments `[T_1, ..., T_{n-1}]` to maintain cross-segment coherence (preventing tense, tone, and naming drift), and (3) the current segment draft `S_n` as the correction target.**
   d. On Pass 2 segment success: restore placeholders, validate, and emit artifacts per segment.
   e. Reconstruction phase concatenates all validated segment outputs in order to produce the final block output for `B`.
   f. If any segment fails after retry, the entire block `B` is marked failed.
7. Halt if the retry still fails structural validation.
8. Run Pass 2 through the shared LLM client against source and Pass 1 output.
9. Emit corrected output, prompt metadata, model metadata, and fidelity flags.
10. Persist chapter-level checkpoint state.

## Command Behavior

- `translate-chapter` targets exactly one chapter.
- If a valid Pass 1 checkpoint exists, resume from Pass 2 unless `--force-pass1` is supplied.
- If structure validation fails, resegment the failed block at sentence boundaries, retry each segment in Pass 1, then run Pass 2 sequentially with full original block context and prior segment translations against each segment draft before marking the chapter failed.
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
