# Task 36: CLI Short-Form Aliases

- **Milestone:** M12 (follow-up)
- **Depends on:** task-12

## Goal

Add 2-4 letter abbreviations for long CLI commands at both top-level and subcommand level while preserving full names as backward-compatible aliases.

## Scope

In:

- Top-level: `ext`, `tra`, `pre`, `pac`, `reb` as aliases for `extract`, `translate`, `preprocess`, `packets`, `rebuild`
- Preprocess subcommands: `gls-discover`, `gls-translate`, `gls-review`, `gls-promote` for glossary-*; `sum` for `summaries`; `idi-review`, `idi-promote` for idiom-*
- Run subcommands: `prod` for `production`; `cln-plan`, `cln-apply` for cleanup-*
- Aliases must normalize to primary names so dispatch logic is unchanged
- Test that each alias dispatches identically to its long form
- Add single-letter short flags for commonly used options following dnf convention
- Short flags are additive — long flags remain unchanged
- Rewrite all help text (`_PROGRAM_DESCRIPTION`, `_PROGRAM_EPILOG`, per-command `description=`) to dnf man-page format: concise, milestone/artifact-free, single-paragraph per command
- Add shorter alternative long flag names: `--batched`, `--review`, `--stage`
- Polish flag help text for consistency and conciseness

Out:

- Renaming any dispatching logic or internal identifiers
- Renaming any long flag names
- Updating documentation other than this task and its LLD

## Owned Files Or Modules

- `src/resemantica/cli.py`
- `tests/cli/test_cli_dispatch.py`
- `docs/20-lld/lld-36-cli-aliases.md`

## Interfaces To Satisfy

```
rsem ext --release r1 --input book.epub               # alias → extract
rsem ext -r r1 -i book.epub                           # short flags
rsem tra --release r1 --run r1 --chapter 3            # alias → translate
rsem tra -r r1 -R r1 -C 3                             # short flags
rsem pre gls-discover --release r1                    # alias → glossary-discover
rsem pre gls-discover -r r1 -p 0.5                    # short flags
rsem run cln-plan -r r1 -S translation                # short flags
rsem extract --release r1 --input book.epub           # original still works
rsem pre glossary-discover --release r1               # original still works
```

## Tests Or Smoke Checks

- `test_top_level_commands_exist` asserts exact set of top-level command names (including aliases as keys in choices dict)
- New per-alias test methods: 5 top-level + 11 subcommand alias tests
- New short-flag test methods verifying each short flag parses correctly
- Manual: `rsem --help` lists aliases alongside primary names

## Done Criteria

- All aliases (`ext|tra|pre|pac|reb` + `gls-*|sum|idi-*|prod|cln-*`) work identically to the long forms
- All short flags (`-r|-R|-c|-C|-s|-e|-i|-f|-p|-F|-b|-n|-t|-S`) work identically to their long forms
- All help text rewritten to dnf man-page format — no milestone/artifact references, concise per-command descriptions
- All existing tests pass unchanged
- Alias and short-flag tests added and passing
