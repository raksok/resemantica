# Task 49: Resume Granularity Standardization

## Milestone

M49

## Depends On

M10, M48

## Goal

Standardize rerun behavior so the same `release_id` and `run_id` resumes completed durable work by default. Explicit `--force` rebuilds the requested scope. `--allow-rewind` remains only a stage-order safety override.

## Scope

- Wire default internal resume for production and individual preprocessing, packet, and translation commands.
- Add `--force` to summaries, glossary discovery/translation/promotion, idioms, graph, packet build, production, resume, and translation.
- Keep translation `--force-pass1` as a backward-compatible alias for `--force`.
- Persist graph extraction drafts per chapter and reuse them during graph resume.
- Keep packet staleness metadata as packet resume truth, with `force_rebuild` bypassing cache hits.

## Owned Files Or Modules

- `src/resemantica/cli.py`
- `src/resemantica/orchestration/`
- `src/resemantica/summaries/`
- `src/resemantica/glossary/`
- `src/resemantica/idioms/`
- `src/resemantica/graph/`
- `src/resemantica/packets/`
- `src/resemantica/translation/`
- `src/resemantica/db/sqlite.py`
- `src/resemantica/db/graph_repo.py`
- `tests/cli/`, `tests/orchestration/`, `tests/graph/`, `tests/packets/`

## Interfaces To Satisfy

- Default reruns skip completed durable units.
- `--force` ignores internal checkpoints and cache hits for the requested command scope.
- `--allow-rewind` only permits legal transition override; it does not imply force.
- Graph drafts are keyed by release, run, chapter, chapter source hash, and prompt version.
- Checkpoints advance only after durable writes complete.

## Durable Resume Units

- Idiom translation resumes at two levels: the existing phase checkpoint skips the whole translate phase after `translated` or `promoted`, and interrupted in-phase translation resumes from persisted `idiom_translation_votes` rows keyed by release, run, model, candidate, and vote kind.
- A complete idiom model vote is both `rendering` and `meaning` rows for the same candidate. Reruns generate only missing vote kinds unless `--force` is used.

## Tests Or Smoke Checks

- CLI parsing proves `--force` and `--allow-rewind` are separate.
- Production force starts from the first stage and forwards `force=True`.
- Graph resume reuses persisted draft rows without LLM calls.
- Packet force rebuild bypasses an `up_to_date` metadata hit.
- Existing graph interval tests remain green after draft merge.

## Done Criteria

- All affected stage commands default to resume behavior.
- Forced reruns rebuild only the requested scope.
- Documentation records durable resume units for summaries, glossary, idioms, graph, packets, and translation.
- Targeted and full validation pass.
