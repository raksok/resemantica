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
        "-r", "--release", required=True,
        help="Release identifier. Creates artifacts/releases/<id>/.",
    )
    parser.add_argument(
        "-R", "--run",
        required=False,
        default=default_run,
        help=f"Checkpoint tracking and artifact scoping identifier (default: {default_run}).",
    )
    parser.add_argument(
        "-c", "--config",
        type=Path,
        default=None,
        metavar="PATH",
        help="Path to resemantica.toml (default: ./resemantica.toml).",
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


def _add_chapter_scope_args(parser: argparse.ArgumentParser, required: bool = False) -> None:
    group = parser.add_mutually_exclusive_group(required=required)
    group.add_argument(
        "-C", "--chapter",
        type=int,
        help="Single chapter number to process. Mutually exclusive with --start.",
    )
    group.add_argument(
        "-s", "--start",
        type=int,
        help="First chapter in range (inclusive). Mutually exclusive with --chapter.",
    )
    parser.add_argument(
        "-e", "--end",
        type=int,
        help="Last chapter in range (inclusive). Used with --start.",
    )


def _add_batched_model_order_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-b", "--batched", "--batched-model-order",
        dest="batched_model_order",
        action="store_true",
        help="Run all chapters pass1-first, then pass2, then pass3.",
    )


_PROGRAM_DESCRIPTION = """\
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

    extract = subparsers.add_parser(
        "extract", aliases=["ext"],
        help="Unpack, extract, validate, and rebuild an EPUB without translation changes.",
        description="""\
Entry point for a new release. Unpacks a source EPUB into structured
chapters, placeholder maps, and a validation report. Produces a lossless
reconstructed EPUB to confirm round-trip fidelity.""",
    )
    extract.add_argument(
        "-i", "--input", required=True, type=Path,
        help="Path to the source EPUB file.",
    )
    extract.add_argument(
        "-r", "--release", required=True,
        help="Release identifier. Creates artifacts/releases/<id>/.",
    )
    extract.add_argument(
        "-c", "--config",
        type=Path,
        default=None,
        metavar="PATH",
        help="Path to resemantica.toml (default: ./resemantica.toml).",
    )
    _add_verbose_arg(extract)

    translate = subparsers.add_parser(
        "translate", aliases=["tra"],
        help="Translate one or multiple extracted chapters.",
        description="""\
Two-pass translation of one or more chapters. Pass 1 (translator model)
produces a draft English translation preserving all placeholders. Pass 2
(analyst model) performs a structured fidelity check, correcting omissions
and terminology violations.""",
    )
    translate.add_argument(
        "-r", "--release", required=True,
        help="Release identifier. Creates artifacts/releases/<id>/.",
    )
    translate.add_argument(
        "-R", "--run", required=True,
        help="Checkpoint tracking and artifact scoping identifier.",
    )
    _add_chapter_scope_args(translate, required=True)
    translate.add_argument(
        "-f", "--force-pass1",
        action="store_true",
        help="Ignore cached pass1 checkpoint and re-run from scratch.",
    )
    translate.add_argument(
        "-c", "--config",
        type=Path,
        default=None,
        metavar="PATH",
        help="Path to resemantica.toml (default: ./resemantica.toml).",
    )
    _add_batched_model_order_arg(translate)
    _add_verbose_arg(translate)

    preprocess = subparsers.add_parser(
        "preprocess", aliases=["pre"],
        help="Run preprocessing stage tasks.",
        description="""\
Preprocessing stages: glossary discovery, translation, and promotion;
chapter summaries; idiom detection and policy generation; entity-relationship
graph building. Run individual subcommands or as part of 'run production'.""",
    )
    preprocess_subparsers = preprocess.add_subparsers(
        dest="preprocess_command",
        required=True,
    )

    glossary_discover = preprocess_subparsers.add_parser(
        "glossary-discover", aliases=["gls-discover"],
        help="Discover glossary candidates from extracted chapters.",
        description="""\
Scans extracted chapters for Chinese terms not in the locked glossary.
Applies deterministic filters and BGE-M3 embedding critic. Writes
candidates.json with frequency counts and context snippets.""",
    )
    _add_common_release_args(glossary_discover, default_run="glossary-discover")
    _add_chapter_scope_args(glossary_discover)
    glossary_discover.add_argument(
        "-p", "--pruning-threshold",
        required=False,
        type=float,
        default=None,
        help="BGE-M3 critic pruning threshold (0-1, default: from config). Set 0 for eval-only.",
    )

    glossary_translate = preprocess_subparsers.add_parser(
        "glossary-translate", aliases=["gls-translate"],
        help="Translate discovered glossary candidates to provisional English terms.",
        description="""\
Sends untranslated glossary candidates through the translator LLM to
produce provisional English renderings. Updates candidates.json.""",
    )
    _add_common_release_args(glossary_translate, default_run="glossary-translate")
    _add_chapter_scope_args(glossary_translate)

    glossary_review = preprocess_subparsers.add_parser(
        "glossary-review", aliases=["gls-review"],
        help="Generate a human-editable review file for translated candidates.",
        description="""\
Generates a human-editable JSON review file of translated glossary
candidates. Edit the file to override translations, mark deletions, or
add entries, then run glossary-promote to apply changes.""",
    )
    _add_common_release_args(glossary_review, default_run="glossary-review")
    _add_chapter_scope_args(glossary_review)

    glossary_promote = preprocess_subparsers.add_parser(
        "glossary-promote", aliases=["gls-promote"],
        help="Validate and promote glossary candidates into locked glossary.",
        description="""\
Validates translated glossary candidates and promotes them into the
locked glossary. With --review-file, applies user edits from a previous
glossary-review run before promotion.""",
    )
    _add_common_release_args(glossary_promote, default_run="glossary-promote")
    _add_chapter_scope_args(glossary_promote)
    glossary_promote.add_argument(
        "-F", "--review", "--review-file",
        dest="review_file",
        required=False,
        type=Path,
        default=None,
        metavar="PATH",
        help="Path to a review.json file from glossary-review. Applies user edits before promotion.",
    )

    summaries = preprocess_subparsers.add_parser(
        "summaries", aliases=["sum"],
        help="Generate validated Chinese summaries and derived English summaries.",
        description="""\
Generates three summary types per chapter: story_so_far_zh (cumulative
plot), chapter_summary_zh_short (one-paragraph synopsis), and
arc_summary_zh (active narrative arc context). Stored in resemantica.db.""",
    )
    _add_common_release_args(summaries, default_run="summaries")
    _add_chapter_scope_args(summaries)

    idioms = preprocess_subparsers.add_parser(
        "idioms",
        help="Detect, validate, and promote idiom policies from extracted chapters.",
        description="""\
Scans chapters for idiomatic expressions (chengyu, set phrases, proverbs).
Validates against the glossary to avoid conflicts, then writes idiom
policies with preferred English renderings to resemantica.db.""",
    )
    _add_common_release_args(idioms, default_run="idioms")
    _add_chapter_scope_args(idioms)

    idiom_review = preprocess_subparsers.add_parser(
        "idiom-review", aliases=["idi-review"],
        help="Generate a human-editable review file for translated idiom candidates.",
        description="""\
Generates a human-editable JSON review file of translated idiom candidates.
Edit the file to override renderings, mark deletions, or add entries,
then run idiom-promote to apply changes.""",
    )
    _add_common_release_args(idiom_review, default_run="idiom-review")
    _add_chapter_scope_args(idiom_review)

    idiom_promote = preprocess_subparsers.add_parser(
        "idiom-promote", aliases=["idi-promote"],
        help="Validate and promote idiom candidates into idiom policies.",
        description="""\
Validates translated idiom candidates and promotes them into the
authoritative idiom policy store. With --review-file, applies user edits
from a previous idiom-review run before promotion.""",
    )
    _add_common_release_args(idiom_promote, default_run="idiom-promote")
    _add_chapter_scope_args(idiom_promote)
    idiom_promote.add_argument(
        "-F", "--review", "--review-file",
        dest="review_file",
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
Builds an entity-relationship graph from glossary entries, summaries, and
chapter text. Extracts entities, aliases, appearances, and relationships
with chapter-safe spoiler filters. Outputs graph.ladybug and snapshot.json.""",
    )
    _add_common_release_args(graph, default_run="graph")
    _add_chapter_scope_args(graph)

    packets = subparsers.add_parser(
        "packets", aliases=["pac"],
        help="Build immutable chapter packets and paragraph bundles.",
        description="""\
Build or rebuild immutable chapter artifacts from validated upstream
state.""",
    )
    packets_subparsers = packets.add_subparsers(
        dest="packets_command",
        required=True,
    )
    packets_build = packets_subparsers.add_parser(
        "build",
        help="Build chapter packets from validated upstream authority state.",
        description="""\
Assembles ChapterPacket per chapter (glossary subset, summaries, idiom
matches, graph context) and derives ParagraphBundle per block. Staleness
detection rebuilds automatically when upstream hashes change.""",
    )
    _add_common_release_args(packets_build, default_run="packets-build")
    _add_chapter_scope_args(packets_build)

    rebuild = subparsers.add_parser(
        "rebuild", aliases=["reb"],
        help="Rebuild EPUB from unpacked release content.",
        description="""\
Reads final translated pass artifacts (pass2 or pass3), restores
placeholders to original XHTML elements, and reconstructs a complete
EPUB.""",
    )
    _add_common_release_args(rebuild, default_run="rebuild")

    # The standalone translate-range and run-production commands have been removed.

    tui_cmd = subparsers.add_parser(
        "tui",
        help="Launch the Textual TUI.",
        description="""\
Interactive terminal UI for monitoring pipeline runs, inspecting artifacts,
and triggering individual stages. Supports keyboard navigation and session
persistence.""",
    )
    tui_cmd.add_argument(
        "-r", "--release",
        required=False,
        default=None,
        help="Release to pre-load in the TUI.",
    )
    tui_cmd.add_argument(
        "-R", "--run",
        required=False,
        default=None,
        help="Run to pre-load in the TUI.",
    )
    tui_cmd.add_argument(
        "-c", "--config",
        type=Path,
        default=None,
        metavar="PATH",
        help="Path to resemantica.toml (default: ./resemantica.toml).",
    )
    _add_chapter_scope_args(tui_cmd)

    run = subparsers.add_parser(
        "run",
        help="Orchestration run commands.",
        description="""\
Central workflow control: full production pipeline, checkpoint resume,
and cleanup of intermediate artifacts.""",
    )
    run_subparsers = run.add_subparsers(
        dest="run_command",
        required=True,
    )

    run_production = run_subparsers.add_parser(
        "production", aliases=["prod"],
        help="Run full production workflow from preprocess through EPUB rebuild.",
        description="""\
Executes all pipeline stages in canonical order: preprocess-glossary,
preprocess-summaries, preprocess-idioms, preprocess-graph, packets-build,
translate-range, epub-rebuild. With --dry-run, prints the ordered stage
list without executing.""",
    )
    _add_common_release_args(run_production, default_run="production")
    run_production.add_argument(
        "-n", "--dry-run",
        action="store_true",
        help="Print the deterministic stage plan without executing any stages.",
    )
    _add_chapter_scope_args(run_production)
    _add_batched_model_order_arg(run_production)

    run_resume = run_subparsers.add_parser(
        "resume",
        help="Resume a previous run from its last checkpoint.",
        description="""\
Loads the last saved checkpoint for a release and run, and continues
execution from that point. With --from-stage, overrides the resume
point to a specific stage.""",
    )
    _add_common_release_args(run_resume, default_run="resume")
    run_resume.add_argument(
        "-t", "--stage", "--from-stage",
        dest="from_stage",
        required=False,
        type=str,
        default=None,
        metavar="STAGE",
        help="Stage name to resume from. Default: auto-detect from checkpoint.",
    )

    run_cleanup_plan = run_subparsers.add_parser(
        "cleanup-plan", aliases=["cln-plan"],
        help="Plan cleanup by enumerating deletable artifacts.",
        description="""\
Dry-run inspection of deletable artifacts for a given scope. No files
removed. Scopes: run, translation, preprocess, cache, all.""",
    )
    _add_common_release_args(run_cleanup_plan, default_run="cleanup-plan")
    run_cleanup_plan.add_argument(
        "-S", "--scope",
        required=False,
        type=str,
        default="run",
        choices=["run", "translation", "preprocess", "cache", "all"],
        help="Cleanup scope (default: run).",
    )

    run_cleanup_apply = run_subparsers.add_parser(
        "cleanup-apply", aliases=["cln-apply"],
        help="Apply a previously planned cleanup.",
        description="""\
Deletes artifacts matching the given scope. Use cleanup-plan first to
preview. Scopes: run, translation, preprocess, cache, all.""",
    )
    _add_common_release_args(run_cleanup_apply, default_run="cleanup-apply")
    run_cleanup_apply.add_argument(
        "-S", "--scope",
        required=False,
        type=str,
        default="run",
        choices=["run", "translation", "preprocess", "cache", "all"],
        help="Cleanup scope (default: run).",
    )
    run_cleanup_apply.add_argument(
        "-f", "--force",
        action="store_true",
        help="Skip scope-mismatch safety check (use with caution).",
    )

    return parser


_ALIAS_MAP: dict[str, str] = {
    "ext": "extract",
    "tra": "translate",
    "pre": "preprocess",
    "pac": "packets",
    "reb": "rebuild",
    "gls-discover": "glossary-discover",
    "gls-translate": "glossary-translate",
    "gls-review": "glossary-review",
    "gls-promote": "glossary-promote",
    "sum": "summaries",
    "idi-review": "idiom-review",
    "idi-promote": "idiom-promote",
    "prod": "production",
    "cln-plan": "cleanup-plan",
    "cln-apply": "cleanup-apply",
}


def _resolve_command(command: str) -> str:
    return _ALIAS_MAP.get(command, command)


def _parse_and_resolve(argv: list[str] | None = None) -> argparse.Namespace:
    parser = _build_parser()
    args = parser.parse_args(argv)
    args.command = _resolve_command(args.command)
    for attr in ("preprocess_command", "packets_command", "run_command"):
        val = getattr(args, attr, None)
        if val:
            setattr(args, attr, _resolve_command(val))
    return args


def main(argv: list[str] | None = None) -> int:
    args = _parse_and_resolve(argv)
    result: Any

    if getattr(args, "chapter", None) is not None:
        args.start = args.chapter
        args.end = args.chapter

    if args.command == "extract":
        config = load_config(args.config)
        _configure_cli_logging(args=args, config=config, release_id=args.release, run_id="extract")
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

    if args.command == "translate":
        config = load_config(args.config)
        _configure_cli_logging(args=args, config=config, release_id=args.release, run_id=args.run)
        stop_token = StopToken()

        # Determine if running a single chapter or a range
        if getattr(args, "chapter", None) is not None:
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
        else:
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

    if args.command == "rebuild":
        config = load_config(args.config)
        _configure_cli_logging(args=args, config=config, release_id=args.release, run_id=args.run)
        stop_token = StopToken()
        result = _with_cli_progress(
            lambda: OrchestrationRunner(args.release, args.run, config=config).run_stage(
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
