# LLD 36: CLI Short-Form Aliases

## Summary

Add `argparse` `aliases` for long commands (top-level and subcommands) so operators can use 2-4 letter abbreviations without breaking existing scripts that use the full names.

## Mapping

### Top-Level Commands

| Full Name | Alias | Convention |
|-----------|-------|------------|
| `extract` | `ext` | first 3 chars |
| `translate` | `tra` | first 3 chars |
| `preprocess` | `pre` | first 3 chars |
| `packets` | `pac` | first 3 chars |
| `rebuild` | `reb` | first 3 chars |

`tui` and `run` are unchanged (already ≤3 chars).

### Preprocess Subcommands (under `preprocess` / `pre`)

| Full Name | Alias | Convention |
|-----------|-------|------------|
| `glossary-discover` | `gls-discover` | `gls` = glossary, first 3 |
| `glossary-translate` | `gls-translate` | |
| `glossary-review` | `gls-review` | |
| `glossary-promote` | `gls-promote` | |
| `summaries` | `sum` | first 3 chars |
| `idioms` | — | unchanged (6 chars) |
| `idiom-review` | `idi-review` | `idi` = idiom, first 3 |
| `idiom-promote` | `idi-promote` | |
| `graph` | — | unchanged (5 chars) |

### Run Subcommands (under `run`)

| Full Name | Alias | Convention |
|-----------|-------|------------|
| `production` | `prod` | first 4 chars (`pro` would collide with `preprocess`) |
| `resume` | — | unchanged (6 chars) |
| `cleanup-plan` | `cln-plan` | `cln` = cleanup, first 3 |
| `cleanup-apply` | `cln-apply` | |

### Packets Subcommands (under `packets` / `pac`)

`build` unchanged (5 chars).

## Design

### Mechanism

Use `argparse.ArgumentParser.add_parser()` `aliases` parameter:

```python
# Before:
subparsers.add_parser("extract", help="...")

# After:
subparsers.add_parser("extract", aliases=["ext"], help="...")
```

Applies identically to sub-subparsers:

```python
preprocess_subparsers.add_parser(
    "glossary-discover", aliases=["gls-discover"], help="..."
)
```

### Alias Normalization

Aliases must be normalized back to primary names so dispatch branches are unaffected. This is done in `_parse_and_resolve()`, which post-processes `args.command`, `args.preprocess_command`, `args.packets_command`, and `args.run_command` through `_ALIAS_MAP`.

```python
def _parse_and_resolve(argv):
    parser = _build_parser()
    args = parser.parse_args(argv)
    args.command = _resolve_command(args.command)
    for attr in ("preprocess_command", "packets_command", "run_command"):
        val = getattr(args, attr, None)
        if val:
            setattr(args, attr, _resolve_command(val))
    return args
```

### What `argparse` Does

- Registers both primary name and alias(es) as valid subcommand choices
- Stores both in the subparser's `choices` dict
- Help text shows `{name,alias}` notation
- Alias resolves to the same parser object as the primary name

### Affected Files

| File | Change |
|------|--------|
| `src/resemantica/cli.py` | Add `aliases=[...]` to 16 `add_parser()` calls (5 top-level + 11 subcommand); extend `_ALIAS_MAP` with 11 entries; extend `_parse_and_resolve` to normalize subcommand attrs |
| `tests/cli/test_cli_dispatch.py` | Add 16 alias test methods; update `test_top_level_commands_exist` expected set |

### Unchanged

- All dispatch branches (`if args.preprocess_command == "glossary-discover"`, etc.)
- All subcommand structures (dest names, sub-subparsers)
- All `--run` default values (artifact IDs, not command names)
- Cleanup scope strings
- All other documentation

## Test Plan

Each alias gets a test through `_parse_and_resolve()`:

```python
def test_glossary_discover_alias(self):
    args = _parse_and_resolve(["pre", "gls-discover", "--release", "r1"])
    assert args.command == "preprocess"
    assert args.preprocess_command == "glossary-discover"

def test_summaries_alias(self):
    args = _parse_and_resolve(["pre", "sum", "--release", "r1"])
    assert args.preprocess_command == "summaries"

def test_production_alias(self):
    args = _parse_and_resolve(["run", "prod", "--release", "r1", "--dry-run"])
    assert args.run_command == "production"

def test_cleanup_plan_alias(self):
    args = _parse_and_resolve(["run", "cln-plan", "--release", "r1"])
    assert args.run_command == "cleanup-plan"
```

## Short Flag Aliases

Following the `dnf` convention, add single-letter short options for commonly used flags. Short flags are additive — all long flags remain unchanged.

### Shared Flag Helpers

Modified once in `_build_parser()`, these apply to every command that uses them:

| Helper | Long | Short | Convention |
|---|---|---|---|
| `_add_common_release_args` | `--release` | `-r` | release |
| (same) | `--run` | `-R` | uppercase to avoid `-r` collision |
| (same) | `--config` | `-c` | universal config convention |
| `_add_chapter_scope_args` | `--chapter` | `-C` | uppercase to avoid `-c` collision |
| (same) | `--start` | `-s` | standard start |
| (same) | `--end` | `-e` | standard end |
| `_add_batched_model_order_arg` | `--batched-model-order` | `-b` | batched |

### Per-Subcommand Flags

| Subcommand | Long | Short | Convention |
|---|---|---|---|
| `extract` | `--input` | `-i` | standard input |
| `translate` | `--force-pass1` | `-f` | force |
| `glossary-discover` | `--pruning-threshold` | `-p` | pruning |
| `glossary-promote` | `--review-file` | `-F` | uppercase File |
| `idiom-promote` | `--review-file` | `-F` | same, consistent |
| `run production` | `--dry-run` | `-n` | dry-ru-n |
| `run resume` | `--from-stage` | `-t` | s-t-age (middle letter) |
| `run cleanup-plan` | `--scope` | `-S` | uppercase Scope |
| `run cleanup-apply` | `--scope` | `-S` | same |
| (same) | `--force` | `-f` | force |

### Design

Flags are added via `add_argument("-r", "--release", ...)` in `argparse`. The short flag follows the same definition as the long flag — same type, required/optional status, default, help text. No normalization needed since the `dest` is the same.

### Affected Files (Incremental)

| File | Change |
|------|--------|
| `src/resemantica/cli.py` | Add short flag strings to 14 `add_argument()` calls across 4 shared helpers + 9 individual flag definitions |
| `tests/cli/test_cli_dispatch.py` | Add test methods verifying each short flag parses to the same value |

### Unchanged

- All long flag names — every `--release`, `--input`, etc. still works
- No dispatch logic changes — flags use the same `dest` attribute
- No `_ALIAS_MAP` changes — flag aliases are native argparse

## Help Text Rewrite

Rewrite all argparse `description=` strings and the program-level `_PROGRAM_DESCRIPTION` / `_PROGRAM_EPILOG` to follow the dnf man-page format: concise, purpose-focused, no milestone labels or artifact output paths.

### Program-Level Help (`rsem --help`)

```
NAME
  rsem — local-first EPUB translation pipeline for Chinese web novels

SYNOPSIS
  rsem [options] <command> [<args>...]

DESCRIPTION
  Unrolls Chinese webnovel EPUBs through a deterministic pipeline:
  glossary discovery, summary generation, idiom detection,
  entity-relationship graph building, translation passes, and
  EPUB reconstruction.

  Pipeline stages (execution order):
    extract     Unpack and validate EPUB structure
    preprocess  Glossary, summaries, idioms, entity graph
    packets     Build chapter packets with enriched context
    translate   Pass1 (translator), Pass2 (analyst), Pass3 (polish)
    rebuild     Reconstruct translated EPUB from pass artifacts

  Configuration: resemantica.toml or --config <path>.
  See docs/ for architecture, task briefs, and operation guides.
```

### Per-Command Style

Each `description=` is a single paragraph explaining what the command does. No milestone numbers, no artifact paths, no prerequisite lists.

| Command | Style |
|---|---|
| `extract` | "Entry point for a new release. Unpacks a source EPUB into structured chapters, placeholder maps, and a validation report. Produces a lossless reconstructed EPUB to confirm round-trip fidelity." |
| `translate` | "Two-pass translation of one or more chapters. Pass 1 (translator model) produces a draft English translation preserving all placeholders. Pass 2 (analyst model) performs a structured fidelity check, correcting omissions and terminology violations." |
| `glossary-discover` | "Scans extracted chapters for Chinese terms not in the locked glossary. Applies deterministic filters and BGE-M3 embedding critic. Writes candidates.json with frequency counts and context snippets." |
| etc. | All 21 commands follow the same pattern — one paragraph, no verbosity. |

### Affected Files

| File | Change |
|------|--------|
| `src/resemantica/cli.py` | Replace `_PROGRAM_DESCRIPTION`, `_PROGRAM_EPILOG`, and 21 per-command `description=` strings |

### Unchanged

- All `help=` one-liners (shown in `rsem --help` command list)
- All argument definitions and `help=` on individual flags
- All tests — cosmetic change only

## Flag Name Expansion (Third Kaizen Pass)

Add shorter alternative long-form names for three flags. Old names remain functional.

| Flag | Added Name | `dest` | Rationale |
|---|---|---|---|
| `--batched-model-order` | `--batched` | `batched_model_order` | "batched" is enough in context |
| `--review-file` | `--review` | `review_file` | "file" implied by context |
| `--from-stage` | `--stage` | `from_stage` | "from" is filler |

## Flag Help Text Polish (Third Kaizen Pass)

Standardize flag help text for consistency and conciseness.

| Flag | Before | After |
|---|---|---|
| `--release` | "Release identifier. Creates/references artifacts/releases/\<id\>/." | "Release identifier. Creates artifacts/releases/\<id\>/." |
| `--run` | "Run identifier for checkpoint tracking and artifact scoping (default: X)." | "Checkpoint tracking and artifact scoping identifier (default: X)." |
| `--config` | "Optional path to resemantica.toml (default: ./resemantica.toml)." | "Path to resemantica.toml (default: ./resemantica.toml)." |
| `--start` | "First chapter number in a range (inclusive). Mutually exclusive with --chapter." | "First chapter in range (inclusive). Mutually exclusive with --chapter." |
| `--end` | "Last chapter number in a range (inclusive). Used with --start." | "Last chapter in range (inclusive). Used with --start." |

## Backward Compatibility

| Scenario | Behavior |
|---|---|
| `rsem extract --release r1 --input book.epub` | Works exactly as before |
| `rsem ext --release r1 --input book.epub` | Works identically, normalized to `"extract"` |
| `rsem ext -r r1 -i book.epub` | Works identically |
| `rsem pre glossary-discover --release r1` | Works exactly as before |
| `rsem pre gls-discover --release r1` | Works identically, normalized to `"glossary-discover"` |
| Scripts passing long names via subprocess | Unchanged |
| `rsem --help` | Shows short flags alongside long forms |
