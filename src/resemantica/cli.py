from __future__ import annotations

import argparse
import os
import signal
import sys
from pathlib import Path
from typing import Any

from loguru import logger

from resemantica.cli_progress import CliProgressSubscriber
from resemantica.epub.extractor import extract_epub
from resemantica.glossary.pipeline import (
    promote_glossary_candidates,
    translate_glossary_candidates,
)
from resemantica.logging_config import configure_logging
from resemantica.orchestration import OrchestrationRunner
from resemantica.orchestration.stop import StopRequested, StopToken
from resemantica.settings import AppConfig, derive_paths, load_config


def _add_verbose_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="-v for INFO, -vv for CHAPTER, -vvv for DEBUG, -vvvv for TRACE.",
    )


def _add_common_release_args(parser: argparse.ArgumentParser, *, default_run: str) -> None:
    parser.add_argument(
        "--release", required=True,
        help="Release identifier. Creates/references artifacts/releases/<id>/.",
    )
    parser.add_argument(
        "--run",
        required=False,
        default=default_run,
        help=f"Run identifier for checkpoint tracking and artifact scoping (default: {default_run}).",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        metavar="PATH",
        help="Optional path to resemantica.toml (default: ./resemantica.toml).",
    )
    _add_verbose_arg(parser)


def _configure_cli_logging(
    *,
    args: argparse.Namespace,
    config: AppConfig,
    release_id: str,
    run_id: str | None,
) -> None:
    paths = derive_paths(config, release_id=release_id)
    configure_logging(
        verbosity=int(getattr(args, "verbose", 0) or 0),
        artifacts_dir=paths.artifact_root,
        run_id=run_id,
    )


def _configure_tui_logging(*, config: AppConfig, release_id: str | None, run_id: str | None) -> None:
    logger.remove()
    if release_id is None:
        return
    paths = derive_paths(config, release_id=release_id)
    if not paths.artifact_root.exists():
        return
    logs_dir = paths.artifact_root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    logger.add(logs_dir / f"{run_id or 'tui'}.jsonl", level="DEBUG", serialize=True)


class _InterruptedStop:
    pass


_INTERRUPTED_STOP = _InterruptedStop()


_FORCE_STOP_HANDLER: Any = None  # keep ctypes callback alive to prevent GC


def _install_interrupt_handlers(stop_token: StopToken) -> None:
    """Install OS-level interrupt handlers that fire even during blocking I/O.

    On Windows uses SetConsoleCtrlHandler (dedicated handler thread, fires
    immediately). On Unix uses Python signal.signal (interrupts system calls).
    """
    global _FORCE_STOP_HANDLER

    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32

        @ctypes.CFUNCTYPE(wintypes.BOOL, wintypes.DWORD)
        def _ctrl_handler(ctrl_type: int) -> bool:
            if ctrl_type != 0:  # CTRL_C_EVENT
                return False
            if not stop_token.requested:
                stop_token.request_stop()
                os.write(2, b"Stopping after current task...\n")
                return True
            stop_token.force = True
            os.write(2, b"Force stopping...\n")
            os._exit(130)
            return True

        _FORCE_STOP_HANDLER = _ctrl_handler
        kernel32.SetConsoleCtrlHandler(_ctrl_handler, True)
    else:
        signal.signal(signal.SIGINT, lambda _sig, _fr: _unix_interrupt(_sig, _fr, stop_token))


def _uninstall_interrupt_handlers(stop_token: StopToken) -> None:
    """Restore default interrupt handling."""
    global _FORCE_STOP_HANDLER
    if sys.platform == "win32":
        import ctypes

        if _FORCE_STOP_HANDLER is not None:
            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleCtrlHandler(_FORCE_STOP_HANDLER, False)
            _FORCE_STOP_HANDLER = None
    else:
        signal.signal(signal.SIGINT, signal.SIG_DFL)


def _unix_interrupt(_signum: int, _frame: object, stop_token: StopToken) -> None:
    if not stop_token.requested:
        stop_token.request_stop()
        print("Stopping after current task...", file=sys.stderr)
        return
    stop_token.force = True
    print("Force stopping...", file=sys.stderr)
    os._exit(130)


def _with_cli_progress(fn, *, stop_token: StopToken | None = None, verbosity: int = 0):
    if stop_token is None:
        with CliProgressSubscriber(verbosity=verbosity):
            return fn()

    _install_interrupt_handlers(stop_token)
    try:
        with CliProgressSubscriber(verbosity=verbosity):
            return fn()
    except StopRequested as exc:
        print(f"status=stopped\nmessage={exc.message}")
        return _INTERRUPTED_STOP
    finally:
        _uninstall_interrupt_handlers(stop_token)


def _status_text(result: Any) -> str:
    if getattr(result, "stopped", False):
        return "stopped"
    return "success" if getattr(result, "success", False) else "failed"


def _exit_code(result: Any) -> int:
    if result is _INTERRUPTED_STOP or getattr(result, "stopped", False):
        return 130
    return 0 if getattr(result, "success", False) else 1


def _add_chapter_range_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--start",
        required=False,
        type=int,
        default=None,
        help="First chapter number to include (inclusive). If omitted, starts from the earliest extracted chapter.",
    )
    parser.add_argument(
        "--end",
        required=False,
        type=int,
        default=None,
        help="Last chapter number to include (inclusive). If omitted, goes to the latest extracted chapter.",
    )


def _add_batched_model_order_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--batched-model-order",
        action="store_true",
        help="Run all chapters pass1-first, then pass2, then pass3. Best with separate model endpoints.",
    )


_PROGRAM_DESCRIPTION = """\
Resemantica — local-first EPUB translation pipeline for Chinese web novels.

Pipeline stages (in execution order):
  M1  epub-roundtrip     Unpack, extract, and validate EPUB structure
  M3  preprocess         Glossary discovery, translation, and promotion
  M4  preprocess         Chapter summaries (Chinese + English)
  M5  preprocess         Idiom policies (detection + validation)
  M6  preprocess         Graph MVP state (entity, alias, relationship graph)
  M8  packets build      Build chapter packets with graph-enriched context
  M2  translate-range    Run pass1 (translator), pass2 (analyst), pass3 (polish)
  M16 rebuild-epub       Reconstruct translated EPUB from pass artifacts

Configuration: resemantica.toml in project root, or --config <path>.
See docs/ for architecture, task briefs, and operation guides."""

_PROGRAM_EPILOG = """\
Exit codes:
  0    Success
  1    Stage or command failure
  2    Invalid arguments or unknown command
  130  Interrupted (Ctrl+C) — clean stop"""


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rsem",
        description=_PROGRAM_DESCRIPTION,
        epilog=_PROGRAM_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    roundtrip = subparsers.add_parser(
        "epub-roundtrip",
        help="Unpack, extract, validate, and rebuild an EPUB without translation changes.",
        description="""\
Milestone M1 — the entry point for a new release.

Unpacks the source EPUB into structured artifacts: extracted chapters
(chapter-{n}.json per chapter with block-level records), placeholder
maps (⟦TYPE_N⟧ markers for inline formatting elements), a validation
report, and a lossless reconstruction EPUB to confirm round-trip fidelity.

Outputs:
  artifacts/releases/<release>/extracted/chapters/
  artifacts/releases/<release>/extracted/placeholders/
  artifacts/releases/<release>/extracted/reports/
  artifacts/releases/<release>/rebuild/reconstructed.epub""",
    )
    roundtrip.add_argument(
        "--input", required=True, type=Path,
        help="Path to the source EPUB file.",
    )
    roundtrip.add_argument(
        "--release", required=True,
        help="Release identifier. Creates artifacts/releases/<id>/.",
    )
    roundtrip.add_argument(
        "--config",
        type=Path,
        default=None,
        metavar="PATH",
        help="Optional path to resemantica.toml (default: ./resemantica.toml).",
    )
    _add_verbose_arg(roundtrip)

    translate = subparsers.add_parser(
        "translate-chapter",
        help="Translate one extracted chapter using pass1 and pass2.",
        description="""\
Milestone M2 — two-pass translation for a single chapter.

Pass 1 (translator model): produces a draft English translation, preserving
all placeholders (⟦TYPE_N⟧ markers). On structural failure, the source block
is split into sentences and retried segment-by-segment.

Pass 2 (analyst model): JSON-structured fidelity check. Corrects omissions,
mistranslations, and terminology violations. Produces the final per-block output.

Requires: epub-roundtrip (extracted chapters + placeholders).
For full context enrichment, preprocessing stages (glossary, summaries, idioms,
graph) and packets must be completed first; otherwise context sections are empty.

Outputs:
  artifacts/releases/<release>/runs/<run>/translation/chapter-<n>/pass1.json
  artifacts/releases/<release>/runs/<run>/translation/chapter-<n>/pass2.json
  artifacts/releases/<release>/runs/<run>/validation/chapter-<n>/
  Checkpoint rows in resemantica.db for resume support.""",
    )
    translate.add_argument(
        "--release", required=True,
        help="Release identifier.",
    )
    translate.add_argument(
        "--chapter", required=True, type=int,
        help="Chapter number to translate.",
    )
    translate.add_argument(
        "--run", required=True,
        help="Run identifier for checkpoint tracking and artifact scoping.",
    )
    translate.add_argument(
        "--force-pass1",
        action="store_true",
        help="Ignore cached pass1 checkpoint and re-run from scratch.",
    )
    translate.add_argument(
        "--config",
        type=Path,
        default=None,
        metavar="PATH",
        help="Optional path to resemantica.toml (default: ./resemantica.toml).",
    )
    _add_verbose_arg(translate)

    preprocess = subparsers.add_parser(
        "preprocess",
        help="Run preprocessing stage tasks.",
        description="""\
Preprocessing stages that must run before translation to build the authority
datasets (glossary, summaries, idioms, graph). Run individually or as part
of 'run production'.

Ordering (see each subcommand's description for dependencies):
  glossary-discover  →  glossary-translate  →  glossary-promote
  summaries
  idioms
  graph

All subcommands accept --release, --run, --config, and --verbose.""",
    )
    preprocess_subparsers = preprocess.add_subparsers(
        dest="preprocess_command",
        required=True,
    )

    glossary_discover = preprocess_subparsers.add_parser(
        "glossary-discover",
        help="Discover glossary candidates from extracted chapters.",
        description="""\
Milestone M3 step 1. Scans extracted chapter text for Chinese terms not yet
in the locked glossary. Writes candidate entries with frequency counts and
context snippets to candidates.json.

Applies deterministic filters (date patterns, stop-list) and BGE-M3
embedding critic to prune non-glossary terms. Use --pruning-threshold 0
for evaluation-only mode (scores stored, no pruning).

Requires: epub-roundtrip (extracted chapters).

Outputs:
  artifacts/releases/<release>/glossary/candidates.json""",
    )
    _add_common_release_args(glossary_discover, default_run="glossary-discover")
    glossary_discover.add_argument(
        "--pruning-threshold",
        required=False,
        type=float,
        default=None,
        help="BGE-M3 critic pruning threshold (0-1, default: from config). Set 0 for eval-only.",
    )

    glossary_translate = preprocess_subparsers.add_parser(
        "glossary-translate",
        help="Translate discovered glossary candidates to provisional English terms.",
        description="""\
Milestone M3 step 2. Each untranslated candidate in candidates.json is sent
through the translator LLM to produce a provisional English rendering. Adds
translation metadata to candidates.json.

Requires: glossary-discover.

Outputs: updated artifacts/releases/<release>/glossary/candidates.json""",
    )
    _add_common_release_args(glossary_translate, default_run="glossary-translate")

    glossary_review = preprocess_subparsers.add_parser(
        "glossary-review",
        help="Generate a human-editable review file for translated candidates.",
        description="""\
Milestone M3 review step. Reads all translated glossary candidates and writes
a JSON review file to artifacts/releases/<release>/glossary/review.json.

The user edits the file to:
  - Override translations
  - Mark entries for deletion
  - Add new entries

Then run glossary-promote --review-file <path> to apply changes.

Requires: glossary-translate.

Outputs:
  artifacts/releases/<release>/glossary/review.json""",
    )
    _add_common_release_args(glossary_review, default_run="glossary-review")

    glossary_promote = preprocess_subparsers.add_parser(
        "glossary-promote",
        help="Validate and promote glossary candidates into locked glossary.",
        description="""\
Milestone M3 step 3. Validates translated candidates (no empty terms, no
duplicates, no conflicts), promotes them to the locked glossary, and writes
any unresolvable conflicts to conflicts.json for manual review.

With --review-file, reads a previously generated review file, applies
user overrides (translation edits, deletions, additions), then runs
standard validation and promotion.

Requires: glossary-translate (or glossary-review if --review-file is used).

Outputs:
  Locked rows added to resemantica.db (glossary tables)
  artifacts/releases/<release>/glossary/conflicts.json""",
    )
    _add_common_release_args(glossary_promote, default_run="glossary-promote")
    glossary_promote.add_argument(
        "--review-file",
        required=False,
        type=Path,
        default=None,
        metavar="PATH",
        help="Path to a review.json file from glossary-review. Applies user edits before promotion.",
    )

    summaries = preprocess_subparsers.add_parser(
        "summaries",
        help="Generate validated Chinese summaries and derived English summaries.",
        description="""\
Milestone M4. Generates three summary types per chapter:
  - story_so_far_zh: cumulative plot summary up to the current chapter
  - chapter_summary_zh_short: one-paragraph synopsis of the chapter
  - arc_summary_zh: active narrative arc context (when applicable)
Summaries are stored in resemantica.db and serve as continuity context during
translation.

Requires: epub-roundtrip. Strongly recommended: locked glossary (M3).

Outputs: rows added to resemantica.db (summaries tables).""",
    )
    _add_common_release_args(summaries, default_run="summaries")
    _add_chapter_range_args(summaries)

    idioms = preprocess_subparsers.add_parser(
        "idioms",
        help="Detect, validate, and promote idiom policies from extracted chapters.",
        description="""\
Milestone M5. Scans extracted chapters for idiomatic expressions (chengyu,
set phrases, proverbs). Validates detected idioms against glossary entries
to avoid term conflicts, then writes idiom policies with preferred English
renderings to resemantica.db.

Requires: epub-roundtrip. Strongly recommended: locked glossary (M3).

Outputs: rows added to resemantica.db (idiom tables).""",
    )
    _add_common_release_args(idioms, default_run="idioms")

    idiom_review = preprocess_subparsers.add_parser(
        "idiom-review",
        help="Generate a human-editable review file for translated idiom candidates.",
        description="""\
Milestone M5 review step. Reads all translated idiom candidates and writes
a JSON review file to artifacts/releases/<release>/idioms/review.json.

The user edits the file to:
  - Override idiom renderings
  - Mark entries for deletion
  - Add new entries

Then run idiom-promote --review-file <path> to apply changes.

Requires: preprocess idioms (at least through translation phase).

Outputs:
  artifacts/releases/<release>/idioms/review.json""",
    )
    _add_common_release_args(idiom_review, default_run="idiom-review")

    idiom_promote = preprocess_subparsers.add_parser(
        "idiom-promote",
        help="Validate and promote idiom candidates into idiom policies.",
        description="""\
Milestone M5 promote step. Validates translated idiom candidates and promotes
them into the authoritative idiom policy store.

With --review-file, reads a previously generated review file, applies
user overrides (rendering edits, deletions, additions), then runs
standard validation and promotion.

Requires: preprocess idioms (at least through translation phase).

Outputs:
  Locked rows added to resemantica.db (idiom tables)
  artifacts/releases/<release>/idioms/conflicts.json""",
    )
    _add_common_release_args(idiom_promote, default_run="idiom-promote")
    idiom_promote.add_argument(
        "--review-file",
        required=False,
        type=Path,
        default=None,
        metavar="PATH",
        help="Path to a review.json file from idiom-review. Applies user edits before promotion.",
    )

    graph = preprocess_subparsers.add_parser(
        "graph",
        help="Extract, validate, and promote Graph MVP state from preprocessing assets.",
        description="""\
Milestones M6–M7. Builds a lightweight entity-relationship graph from
glossary entries, summaries, and chapter text. Extracts entities, aliases,
appearances, and relationships; applies chapter-safe filters to prevent
future-spoiler leaks.

The graph database (LadybugDB) is queried during packet building to enrich
translation context with entity relationships, alias resolutions, and
reveal-safe lore.

Requires: locked glossary (M3), summaries (M4), idioms (M5).

Outputs:
  artifacts/graph.ladybug  (LadybugDB database file)
  artifacts/releases/<release>/graph/snapshot.json""",
    )
    _add_common_release_args(graph, default_run="graph")

    packets = subparsers.add_parser(
        "packets",
        help="Build immutable chapter packets and paragraph bundles.",
        description="""\
Build or rebuild immutable chapter artifacts from validated upstream state.""",
    )
    packets_subparsers = packets.add_subparsers(
        dest="packets_command",
        required=True,
    )
    packets_build = packets_subparsers.add_parser(
        "build",
        help="Build chapter packets from validated upstream authority state.",
        description="""\
Milestone M8. For each chapter, assembles a ChapterPacket containing:
  - Glossary subset (entries that appear in the chapter)
  - Previous 3 chapter summaries + story-so-far + active arc
  - Local idiom matches
  - Graph-enriched context (entities, relationships, alias resolutions,
    reveal-safe identity notes)
Then derives narrow ParagraphBundle per block — the exact context the
translation passes consume for that block.

Staleness detection: if any upstream hash (chapter source, glossary,
summaries, graph snapshot, idiom policy) has changed since the last build,
the packet is rebuilt automatically.

Requires: locked glossary (M3), summaries (M4), idioms (M5), graph (M6–M7).

Outputs per chapter:
  artifacts/releases/<release>/packets/chapter-<n>-<packet_id>.json
  artifacts/releases/<release>/packets/chapter-<n>-<packet_id>-bundles.json
  Metadata rows in resemantica.db (packet_metadata table)""",
    )
    _add_common_release_args(packets_build, default_run="packets-build")
    packets_build.add_argument(
        "--chapter",
        required=False,
        type=int,
        default=None,
        help="Single chapter number to build. If omitted, all extracted chapters are built.",
    )

    rebuild = subparsers.add_parser(
        "rebuild-epub",
        help="Rebuild EPUB from unpacked release content.",
        description="""\
Milestone M16. Reads the final translated pass artifacts (pass2 or pass3
output per block), restores placeholders to their original XHTML elements,
and reconstructs a complete EPUB file ready for reading.

Requires: completed translate-range or translate-chapter for all chapters
in the release.

Outputs:
  artifacts/releases/<release>/rebuild/reconstructed.epub""",
    )
    rebuild.add_argument(
        "--release", required=True,
        help="Release identifier. Creates artifacts/releases/<id>/.",
    )
    rebuild.add_argument(
        "--run-id",
        "--run",
        dest="run_id",
        required=False,
        default="rebuild-epub",
        help="Run identifier for artifact lookup (default: rebuild-epub).",
    )
    rebuild.add_argument(
        "--config",
        type=Path,
        default=None,
        metavar="PATH",
        help="Optional path to resemantica.toml (default: ./resemantica.toml).",
    )
    _add_verbose_arg(rebuild)

    translate_range = subparsers.add_parser(
        "translate-range",
        help="Translate a range of chapters.",
        description="""\
Milestone M2 batch mode. Translates every chapter from --start to --end
inclusive. Each chapter runs pass1 → pass2 → pass3 sequentially.

With --batched-model-order, all chapters run pass1 first, then all pass2,
then all pass3 — this can be more efficient when the translator and analyst
models are served from separate endpoints.

Requires: epub-roundtrip, preprocessing stages, and packets build (for
bundle context enrichment).

Outputs (per chapter):
  artifacts/releases/<release>/runs/<run>/translation/chapter-<n>/{pass1,pass2,pass3}.json
  artifacts/releases/<release>/runs/<run>/validation/chapter-<n>/""",
    )
    translate_range.add_argument(
        "--release", required=True,
        help="Release identifier.",
    )
    translate_range.add_argument(
        "--run", required=True,
        help="Run identifier for checkpoint tracking and artifact scoping.",
    )
    translate_range.add_argument(
        "--start", required=True, type=int,
        help="First chapter number to translate (inclusive).",
    )
    translate_range.add_argument(
        "--end", required=True, type=int,
        help="Last chapter number to translate (inclusive).",
    )
    translate_range.add_argument(
        "--config",
        type=Path,
        default=None,
        metavar="PATH",
        help="Optional path to resemantica.toml (default: ./resemantica.toml).",
    )
    _add_batched_model_order_arg(translate_range)
    _add_verbose_arg(translate_range)

    run_production_top = subparsers.add_parser(
        "run-production",
        help="Run or inspect the full production workflow.",
        description="""\
Convenience alias for 'run production'. Executes the full pipeline in stage
order: preprocess → packets-build → translate-range → epub-rebuild.

With --dry-run, prints the ordered stage list and exits without executing.

Exit codes:
  0    All stages completed
  1    A stage failed (details in logs)
  130  Stopped by user (Ctrl+C)""",
    )
    _add_common_release_args(run_production_top, default_run="production")
    run_production_top.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the deterministic stage plan without executing any stages.",
    )
    _add_chapter_range_args(run_production_top)
    _add_batched_model_order_arg(run_production_top)

    tui_cmd = subparsers.add_parser(
        "tui",
        help="Launch the Textual TUI.",
        description="""\
Interactive terminal UI for monitoring pipeline runs, inspecting artifacts,
and triggering individual stages. Supports keyboard navigation and session
persistence.

Optional arguments constrain which release/run/chapter range the TUI shows
by default; all can be changed interactively.""",
    )
    tui_cmd.add_argument(
        "--release",
        required=False,
        default=None,
        help="Release identifier to pre-load in the TUI.",
    )
    tui_cmd.add_argument(
        "--run",
        required=False,
        default=None,
        help="Run identifier to pre-load in the TUI.",
    )
    tui_cmd.add_argument(
        "--config",
        type=Path,
        default=None,
        metavar="PATH",
        help="Optional path to resemantica.toml (default: ./resemantica.toml).",
    )
    _add_chapter_range_args(tui_cmd)

    run = subparsers.add_parser(
        "run",
        help="Orchestration run commands.",
        description="""\
Central workflow control: run the full production pipeline, resume from a
checkpoint, or plan/apply cleanup of intermediate artifacts.

Subcommands:
  production     Execute all pipeline stages in order
  resume         Continue a previous run from its last checkpoint
  cleanup-plan   Dry-run to list deletable artifacts for a scope
  cleanup-apply  Actually delete artifacts for a scope""",
    )
    run_subparsers = run.add_subparsers(
        dest="run_command",
        required=True,
    )

    run_production = run_subparsers.add_parser(
        "production",
        help="Run full production workflow from preprocess through EPUB rebuild.",
        description="""\
Executes all pipeline stages in canonical order:

  1. preprocess-glossary    — discover, translate, promote
  2. preprocess-summaries   — generate chapter summaries
  3. preprocess-idioms      — detect and validate idioms
  4. preprocess-graph       — build entity-relationship graph
  5. packets-build          — build chapter packets with context
  6. translate-range        — run pass1/pass2/pass3 on all chapters
  7. epub-rebuild           — reconstruct translated EPUB

With --dry-run, prints the ordered stage list and exits.
With --start/--end, limits the chapter range for applicable stages.
With --batched-model-order, runs all pass1 first, then all pass2,
then all pass3.

Exit codes:
  0    All stages completed
  1    A stage failed (details in logs)
  130  Stopped by user (Ctrl+C)""",
    )
    _add_common_release_args(run_production, default_run="production")
    run_production.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the deterministic stage plan without executing any stages.",
    )
    _add_chapter_range_args(run_production)
    _add_batched_model_order_arg(run_production)

    run_resume = run_subparsers.add_parser(
        "resume",
        help="Resume a previous run from its last checkpoint.",
        description="""\
Loads the last saved checkpoint for a given release + run and continues
execution from that point. Useful after an interrupted production run.

With --from-stage, override the resume point to a specific stage name.
Useful after manual fixes to skip or re-run a particular stage.

Stage order: preprocess-glossary → preprocess-summaries → preprocess-idioms
→ preprocess-graph → packets-build → translate-range → epub-rebuild""",
    )
    _add_common_release_args(run_resume, default_run="resume")
    run_resume.add_argument(
        "--from-stage",
        required=False,
        type=str,
        default=None,
        metavar="STAGE",
        help="Stage name to resume from. Default: auto-detect from checkpoint.",
    )

    run_cleanup_plan = run_subparsers.add_parser(
        "cleanup-plan",
        help="Plan cleanup by enumerating deletable artifacts.",
        description="""\
Dry-run inspection of what would be deleted for a given scope. No files are
removed. Scopes:

  run           Artifacts for the current run (default)
  translation   All translation artifacts across runs
  preprocess    All preprocessing artifacts (glossary, summaries, etc.)
  cache         All cached data and intermediate files
  all           Everything except the reconstructed EPUB""",
    )
    _add_common_release_args(run_cleanup_plan, default_run="cleanup-plan")
    run_cleanup_plan.add_argument(
        "--scope",
        required=False,
        type=str,
        default="run",
        choices=["run", "translation", "preprocess", "cache", "all"],
        help="Cleanup scope (default: run).",
    )

    run_cleanup_apply = run_subparsers.add_parser(
        "cleanup-apply",
        help="Apply a previously planned cleanup.",
        description="""\
Deletes artifacts matching the given scope. Use cleanup-plan first to
inspect what will be removed.

Scopes:
  run           Artifacts for the current run (default)
  translation   All translation artifacts across runs
  preprocess    All preprocessing artifacts (glossary, summaries, etc.)
  cache         All cached data and intermediate files
  all           Everything except the reconstructed EPUB

With --force, bypasses the scope-mismatch safety check (use with caution).""",
    )
    _add_common_release_args(run_cleanup_apply, default_run="cleanup-apply")
    run_cleanup_apply.add_argument(
        "--scope",
        required=False,
        type=str,
        default="run",
        choices=["run", "translation", "preprocess", "cache", "all"],
        help="Cleanup scope (default: run).",
    )
    run_cleanup_apply.add_argument(
        "--force",
        action="store_true",
        help="Skip scope-mismatch safety check (use with caution).",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    result: Any

    if args.command == "epub-roundtrip":
        config = load_config(args.config)
        _configure_cli_logging(args=args, config=config, release_id=args.release, run_id="epub-roundtrip")
        roundtrip_result = _with_cli_progress(
            lambda: extract_epub(
                input_path=args.input,
                release_id=args.release,
                config=config,
            ),
            verbosity=int(getattr(args, "verbose", 0) or 0),
        )
        print(f"status={roundtrip_result.status}")
        print(f"release_root={roundtrip_result.release_root}")
        print(f"rebuilt_epub={roundtrip_result.rebuilt_epub_path}")
        print(f"validation_report={roundtrip_result.validation_report_path}")
        return 0 if roundtrip_result.status == "success" else 1

    if args.command == "translate-chapter":
        config = load_config(args.config)
        _configure_cli_logging(args=args, config=config, release_id=args.release, run_id=args.run)
        stop_token = StopToken()
        result = _with_cli_progress(
            lambda: OrchestrationRunner(args.release, args.run, config=config).run_stage(
                "translate-chapter",
                chapter_number=args.chapter,
                force=bool(getattr(args, "force_pass1", False)),
                stop_token=stop_token,
            ),
            stop_token=stop_token,
            verbosity=int(getattr(args, "verbose", 0) or 0),
        )
        if result is _INTERRUPTED_STOP:
            return 130
        print(f"status={_status_text(result)}")
        print(f"message={result.message}")
        return _exit_code(result)

    if args.command == "preprocess":
        config = load_config(args.config)
        _configure_cli_logging(args=args, config=config, release_id=args.release, run_id=args.run)
        stop_token = StopToken()
        if args.preprocess_command == "glossary-discover":
            from resemantica.glossary.pipeline import discover_glossary_candidates
            result = _with_cli_progress(
                lambda: discover_glossary_candidates(
                    release_id=args.release,
                    run_id=args.run,
                    config=config,
                    pruning_threshold=getattr(args, "pruning_threshold", None),
                    stop_token=stop_token,
                ),
                stop_token=stop_token,
                verbosity=int(getattr(args, "verbose", 0) or 0),
            )
            if result is _INTERRUPTED_STOP:
                return 130
            print(f"status={result['status']}")
            print(f"candidates_written={result['candidates_written']}")
            print(f"filtered_count={result.get('filtered_count', 0)}")
            print(f"pruned_count={result.get('pruned_count', 0)}")
            return 0

        if args.preprocess_command == "glossary-translate":
            result = _with_cli_progress(
                lambda: translate_glossary_candidates(
                    release_id=args.release,
                    run_id=args.run,
                    config=config,
                    stop_token=stop_token,
                ),
                stop_token=stop_token,
                verbosity=int(getattr(args, "verbose", 0) or 0),
            )
            if result is _INTERRUPTED_STOP:
                return 130
            print(f"status={result['status']}")
            print(f"translated_count={result['translated_count']}")
            print(f"candidates_artifact={result['candidates_artifact']}")
            return 0

        if args.preprocess_command == "glossary-review":
            from resemantica.glossary.pipeline import review_glossary_candidates
            result = _with_cli_progress(
                lambda: review_glossary_candidates(
                    release_id=args.release,
                    run_id=args.run,
                    config=config,
                ),
                verbosity=int(getattr(args, "verbose", 0) or 0),
            )
            if result is _INTERRUPTED_STOP:
                return 130
            print(f"status={result['status']}")
            print(f"entries_written={result['entries_written']}")
            print(f"review_path={result['review_path']}")
            return 0

        if args.preprocess_command == "glossary-promote":
            result = _with_cli_progress(
                lambda: promote_glossary_candidates(
                    release_id=args.release,
                    run_id=args.run,
                    config=config,
                    review_file_path=getattr(args, "review_file", None),
                    stop_token=stop_token,
                ),
                stop_token=stop_token,
                verbosity=int(getattr(args, "verbose", 0) or 0),
            )
            if result is _INTERRUPTED_STOP:
                return 130
            print(f"status={result['status']}")
            print(f"candidate_count={result['candidate_count']}")
            print(f"promoted_count={result['promoted_count']}")
            print(f"conflict_count={result['conflict_count']}")
            print(f"candidates_artifact={result['candidates_artifact']}")
            print(f"conflicts_artifact={result['conflicts_artifact']}")
            return 0

        if args.preprocess_command == "summaries":
            stage_result = _with_cli_progress(
                lambda: OrchestrationRunner(args.release, args.run, config=config).run_stage(
                    "preprocess-summaries",
                    chapter_start=args.start,
                    chapter_end=args.end,
                    stop_token=stop_token,
                ),
                stop_token=stop_token,
                verbosity=int(getattr(args, "verbose", 0) or 0),
            )
            if stage_result is _INTERRUPTED_STOP:
                return 130
            print(f"status={_status_text(stage_result)}")
            print(f"message={stage_result.message}")
            return _exit_code(stage_result)

        if args.preprocess_command == "idioms":
            stage_result = _with_cli_progress(
                lambda: OrchestrationRunner(args.release, args.run, config=config).run_stage(
                    "preprocess-idioms",
                    stop_token=stop_token,
                ),
                stop_token=stop_token,
                verbosity=int(getattr(args, "verbose", 0) or 0),
            )
            if stage_result is _INTERRUPTED_STOP:
                return 130
            print(f"status={_status_text(stage_result)}")
            print(f"message={stage_result.message}")
            return _exit_code(stage_result)

        if args.preprocess_command == "idiom-review":
            from resemantica.idioms.pipeline import review_idiom_candidates
            result = _with_cli_progress(
                lambda: review_idiom_candidates(
                    release_id=args.release,
                    run_id=args.run,
                    config=config,
                ),
                verbosity=int(getattr(args, "verbose", 0) or 0),
            )
            if result is _INTERRUPTED_STOP:
                return 130
            print(f"status={result['status']}")
            print(f"entries_written={result['entries_written']}")
            print(f"review_path={result['review_path']}")
            return 0

        if args.preprocess_command == "idiom-promote":
            from resemantica.idioms.pipeline import promote_idiom_candidates
            result = _with_cli_progress(
                lambda: promote_idiom_candidates(
                    release_id=args.release,
                    run_id=args.run,
                    config=config,
                    review_file_path=getattr(args, "review_file", None),
                    stop_token=stop_token,
                ),
                stop_token=stop_token,
                verbosity=int(getattr(args, "verbose", 0) or 0),
            )
            if result is _INTERRUPTED_STOP:
                return 130
            print(f"status={result['status']}")
            print(f"promoted_count={result['promoted_count']}")
            print(f"conflict_count={result['conflict_count']}")
            print(f"candidates_artifact={result['candidates_artifact']}")
            print(f"policies_artifact={result['policies_artifact']}")
            print(f"conflicts_artifact={result['conflicts_artifact']}")
            return 0

        if args.preprocess_command == "graph":
            stage_result = _with_cli_progress(
                lambda: OrchestrationRunner(args.release, args.run, config=config).run_stage(
                    "preprocess-graph",
                    stop_token=stop_token,
                ),
                stop_token=stop_token,
                verbosity=int(getattr(args, "verbose", 0) or 0),
            )
            if stage_result is _INTERRUPTED_STOP:
                return 130
            print(f"status={_status_text(stage_result)}")
            print(f"message={stage_result.message}")
            return _exit_code(stage_result)

        parser.print_help()
        return 2

    if args.command == "packets":
        config = load_config(args.config)
        _configure_cli_logging(args=args, config=config, release_id=args.release, run_id=args.run)
        stop_token = StopToken()
        if args.packets_command == "build":
            stage_result = _with_cli_progress(
                lambda: OrchestrationRunner(args.release, args.run, config=config).run_stage(
                    "packets-build",
                    chapter_number=args.chapter,
                    stop_token=stop_token,
                ),
                stop_token=stop_token,
                verbosity=int(getattr(args, "verbose", 0) or 0),
            )
            if stage_result is _INTERRUPTED_STOP:
                return 130
            print(f"status={_status_text(stage_result)}")
            print(f"message={stage_result.message}")
            return _exit_code(stage_result)
        parser.print_help()
        return 2

    if args.command == "run":
        config = load_config(args.config)
        _configure_cli_logging(args=args, config=config, release_id=args.release, run_id=args.run)
        from resemantica.orchestration import (
            apply_cleanup,
            plan_cleanup,
            resume_run,
        )

        if args.run_command == "production":
            if getattr(args, "dry_run", False):
                result = OrchestrationRunner(args.release, args.run, config=config).run_production(
                    dry_run=True,
                    chapter_start=args.start,
                    chapter_end=args.end,
                    batched_model_order=bool(getattr(args, "batched_model_order", False)),
                )
                for stage in result.metadata.get("stages", []):
                    print(stage["stage_name"])
                return 0
            stop_token = StopToken()
            result = _with_cli_progress(
                lambda: OrchestrationRunner(
                    args.release,
                    args.run,
                    config=config,
                    stop_token=stop_token,
                ).run_production(
                    dry_run=False,
                    chapter_start=args.start,
                    chapter_end=args.end,
                    batched_model_order=bool(getattr(args, "batched_model_order", False)),
                ),
                stop_token=stop_token,
                verbosity=int(getattr(args, "verbose", 0) or 0),
            )
            if result is _INTERRUPTED_STOP:
                return 130
            print(result.message)
            return _exit_code(result)

        if args.run_command == "resume":
            resume_result = resume_run(
                args.release, args.run, from_stage=args.from_stage
            )
            if not resume_result.success:
                print(f"Resume failed: {resume_result.message}")
                return 1
            print("Resume completed successfully")
            return 0

        if args.run_command == "cleanup-plan":
            plan = plan_cleanup(
                args.release, args.run, scope=args.scope, dry_run=True
            )
            print(f"\nCleanup Plan (scope: {plan['scope']})")
            print(f"Release: {plan['release_id']}, Run: {plan['run_id']}")
            print(f"Estimated space to free: {plan['estimated_space_bytes']} bytes")
            print(f"\nDeletable artifacts ({len(plan['deletable_artifacts'])}):")
            for artifact in plan['deletable_artifacts']:
                print(f"  - {artifact}")
            print(f"\nPreserved artifacts ({len(plan['preserved_artifacts'])}):")
            for artifact in plan['preserved_artifacts']:
                print(f"  - {artifact}")
            print(f"\nDry-run: {plan['dry_run']} (no files will be deleted)")
            return 0

        if args.run_command == "cleanup-apply":
            cleanup_result = apply_cleanup(
                args.release, args.run, scope=args.scope, force=args.force
            )
            print(f"\nCleanup Report (scope: {cleanup_result['scope']})")
            print(f"Release: {cleanup_result['release_id']}, Run: {cleanup_result['run_id']}")
            print(f"\nDeleted files ({len(cleanup_result['deleted_files'])}):")
            for f in cleanup_result['deleted_files']:
                print(f"  - {f}")
            print(f"\nDeleted directories ({len(cleanup_result['deleted_dirs'])}):")
            for d in cleanup_result['deleted_dirs']:
                print(f"  - {d}")
            print(f"\nSQLite rows deleted: {cleanup_result['sqlite_rows_deleted']}")
            if cleanup_result['errors']:
                print(f"\nErrors ({len(cleanup_result['errors'])}):")
                for e in cleanup_result['errors']:
                    print(f"  - {e}")
            return 0

    if args.command == "run-production":
        config = load_config(args.config)
        _configure_cli_logging(args=args, config=config, release_id=args.release, run_id=args.run)
        if getattr(args, "dry_run", False):
            result = OrchestrationRunner(args.release, args.run, config=config).run_production(
                dry_run=True,
                chapter_start=args.start,
                chapter_end=args.end,
                batched_model_order=bool(getattr(args, "batched_model_order", False)),
            )
            for stage in result.metadata.get("stages", []):
                print(stage["stage_name"])
            return 0
        stop_token = StopToken()
        result = _with_cli_progress(
            lambda: OrchestrationRunner(
                args.release,
                args.run,
                config=config,
                stop_token=stop_token,
            ).run_production(
                dry_run=False,
                chapter_start=args.start,
                chapter_end=args.end,
                batched_model_order=bool(getattr(args, "batched_model_order", False)),
            ),
            stop_token=stop_token,
            verbosity=int(getattr(args, "verbose", 0) or 0),
        )
        if result is _INTERRUPTED_STOP:
            return 130
        print(result.message)
        return _exit_code(result)

    if args.command == "rebuild-epub":
        config = load_config(args.config)
        _configure_cli_logging(args=args, config=config, release_id=args.release, run_id=args.run_id)
        stop_token = StopToken()
        result = _with_cli_progress(
            lambda: OrchestrationRunner(args.release, args.run_id, config=config).run_stage(
                "epub-rebuild",
                stop_token=stop_token,
            ),
            stop_token=stop_token,
            verbosity=int(getattr(args, "verbose", 0) or 0),
        )
        if result is _INTERRUPTED_STOP:
            return 130
        print(f"status={_status_text(result)}")
        print(f"message={result.message}")
        return _exit_code(result)

    if args.command == "translate-range":
        config = load_config(args.config)
        _configure_cli_logging(args=args, config=config, release_id=args.release, run_id=args.run)
        stop_token = StopToken()
        result = _with_cli_progress(
            lambda: OrchestrationRunner(args.release, args.run, config=config).run_stage(
                "translate-range",
                chapter_start=args.start,
                chapter_end=args.end,
                batched_model_order=bool(getattr(args, "batched_model_order", False)),
                stop_token=stop_token,
            ),
            stop_token=stop_token,
            verbosity=int(getattr(args, "verbose", 0) or 0),
        )
        if result is _INTERRUPTED_STOP:
            return 130
        print(f"status={_status_text(result)}")
        print(f"message={result.message}")
        return _exit_code(result)

    if args.command == "tui":
        from resemantica.tui import ResemanticaApp
        config = load_config(args.config)
        _configure_tui_logging(config=config, release_id=args.release, run_id=args.run)
        app = ResemanticaApp(
            release_id=args.release,
            run_id=args.run,
            config_path=args.config,
            chapter_start=args.start,
            chapter_end=args.end,
        )
        app.run()
        return 0

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
