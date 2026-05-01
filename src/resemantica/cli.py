from __future__ import annotations

import argparse
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
    parser.add_argument("--release", required=True, help="Release identifier.")
    parser.add_argument(
        "--run",
        required=False,
        default=default_run,
        help=f"Run identifier (default: {default_run}).",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Optional path to resemantica.toml",
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


def _with_cli_progress(fn, *, stop_token: StopToken | None = None):
    if stop_token is None:
        with CliProgressSubscriber():
            return fn()

    previous_handler = signal.getsignal(signal.SIGINT)

    def request_stop(_signum, _frame):  # type: ignore[no-untyped-def]
        if not stop_token.requested:
            stop_token.request_stop()
            print("Stopping after current chapter...", file=sys.stderr)
            return
        raise KeyboardInterrupt

    signal.signal(signal.SIGINT, request_stop)
    try:
        with CliProgressSubscriber():
            return fn()
    except StopRequested as exc:
        print(f"status=stopped\nmessage={exc.message}")
        return _INTERRUPTED_STOP
    except KeyboardInterrupt:
        stop_token.request_stop()
        return _INTERRUPTED_STOP
    finally:
        signal.signal(signal.SIGINT, previous_handler)


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
        help="Optional starting chapter number.",
    )
    parser.add_argument(
        "--end",
        required=False,
        type=int,
        default=None,
        help="Optional ending chapter number, inclusive.",
    )


def _add_batched_model_order_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--batched-model-order",
        action="store_true",
        help="Run translate-range as all pass1, then all pass2, then all pass3.",
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="resemantica")
    subparsers = parser.add_subparsers(dest="command", required=True)

    roundtrip = subparsers.add_parser(
        "epub-roundtrip",
        help="Unpack, extract, validate, and rebuild an EPUB without translation changes.",
    )
    roundtrip.add_argument("--input", required=True, type=Path, help="Input EPUB path.")
    roundtrip.add_argument("--release", required=True, help="Release identifier.")
    roundtrip.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Optional path to resemantica.toml",
    )
    _add_verbose_arg(roundtrip)

    translate = subparsers.add_parser(
        "translate-chapter",
        help="Translate one extracted chapter using pass1 and pass2.",
    )
    translate.add_argument("--release", required=True, help="Release identifier.")
    translate.add_argument("--chapter", required=True, type=int, help="Chapter number.")
    translate.add_argument("--run", required=True, help="Run identifier.")
    translate.add_argument(
        "--force-pass1",
        action="store_true",
        help="Ignore pass1 checkpoint and rerun pass1.",
    )
    translate.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Optional path to resemantica.toml",
    )
    _add_verbose_arg(translate)

    preprocess = subparsers.add_parser(
        "preprocess",
        help="Run preprocessing stage tasks.",
    )
    preprocess_subparsers = preprocess.add_subparsers(
        dest="preprocess_command",
        required=True,
    )

    glossary_discover = preprocess_subparsers.add_parser(
        "glossary-discover",
        help="Discover glossary candidates from extracted chapters.",
    )
    _add_common_release_args(glossary_discover, default_run="glossary-discover")

    glossary_translate = preprocess_subparsers.add_parser(
        "glossary-translate",
        help="Translate discovered glossary candidates to provisional English terms.",
    )
    _add_common_release_args(glossary_translate, default_run="glossary-translate")

    glossary_promote = preprocess_subparsers.add_parser(
        "glossary-promote",
        help="Validate and promote glossary candidates into locked glossary.",
    )
    _add_common_release_args(glossary_promote, default_run="glossary-promote")

    summaries = preprocess_subparsers.add_parser(
        "summaries",
        help="Generate validated Chinese summaries and derived English summaries.",
    )
    _add_common_release_args(summaries, default_run="summaries")

    idioms = preprocess_subparsers.add_parser(
        "idioms",
        help="Detect, validate, and promote idiom policies from extracted chapters.",
    )
    _add_common_release_args(idioms, default_run="idioms")

    graph = preprocess_subparsers.add_parser(
        "graph",
        help="Extract, validate, and promote Graph MVP state from preprocessing assets.",
    )
    _add_common_release_args(graph, default_run="graph")

    packets = subparsers.add_parser(
        "packets",
        help="Build immutable chapter packets and paragraph bundles.",
    )
    packets_subparsers = packets.add_subparsers(
        dest="packets_command",
        required=True,
    )
    packets_build = packets_subparsers.add_parser(
        "build",
        help="Build chapter packets from validated upstream authority state.",
    )
    _add_common_release_args(packets_build, default_run="packets-build")
    packets_build.add_argument(
        "--chapter",
        required=False,
        type=int,
        default=None,
        help="Optional chapter number. If omitted, all extracted chapters are built.",
    )

    rebuild = subparsers.add_parser(
        "rebuild-epub",
        help="Rebuild EPUB from unpacked release content.",
    )
    rebuild.add_argument("--release", required=True, help="Release identifier.")
    rebuild.add_argument(
        "--run-id",
        "--run",
        dest="run_id",
        required=False,
        default="rebuild-epub",
        help="Run identifier (default: rebuild-epub).",
    )
    rebuild.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Optional path to resemantica.toml",
    )
    _add_verbose_arg(rebuild)

    translate_range = subparsers.add_parser(
        "translate-range",
        help="Translate a range of chapters.",
    )
    translate_range.add_argument("--release", required=True, help="Release identifier.")
    translate_range.add_argument("--run", required=True, help="Run identifier.")
    translate_range.add_argument(
        "--start", required=True, type=int, help="Starting chapter number."
    )
    translate_range.add_argument(
        "--end", required=True, type=int, help="Ending chapter number (inclusive)."
    )
    translate_range.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Optional path to resemantica.toml",
    )
    _add_batched_model_order_arg(translate_range)
    _add_verbose_arg(translate_range)

    tui_cmd = subparsers.add_parser(
        "tui",
        help="Launch the Textual TUI.",
    )
    tui_cmd.add_argument(
        "--release",
        required=False,
        default=None,
        help="Release identifier to show in the TUI.",
    )

    run_production_top = subparsers.add_parser(
        "run-production",
        help="Run or inspect the full production workflow.",
    )
    _add_common_release_args(run_production_top, default_run="production")
    run_production_top.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the deterministic production plan without executing stages.",
    )
    _add_chapter_range_args(run_production_top)
    _add_batched_model_order_arg(run_production_top)
    tui_cmd.add_argument(
        "--run",
        required=False,
        default=None,
        help="Run identifier to show in the TUI.",
    )
    tui_cmd.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Optional path to resemantica.toml",
    )
    _add_chapter_range_args(tui_cmd)

    run = subparsers.add_parser(
        "run",
        help="Orchestration run commands.",
    )
    run_subparsers = run.add_subparsers(
        dest="run_command",
        required=True,
    )

    run_production = run_subparsers.add_parser(
        "production",
        help="Run full production workflow from preprocess through EPUB rebuild.",
    )
    _add_common_release_args(run_production, default_run="production")
    run_production.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the deterministic production plan without executing stages.",
    )
    _add_chapter_range_args(run_production)
    _add_batched_model_order_arg(run_production)

    run_resume = run_subparsers.add_parser(
        "resume",
        help="Resume a previous run from its last checkpoint.",
    )
    _add_common_release_args(run_resume, default_run="resume")
    run_resume.add_argument(
        "--from-stage",
        required=False,
        type=str,
        default=None,
        help="Stage to resume from (default: last checkpoint stage).",
    )

    run_cleanup_plan = run_subparsers.add_parser(
        "cleanup-plan",
        help="Plan cleanup by enumerating deletable artifacts.",
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
        help="Force apply even if scope does not match plan.",
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
            )
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
                    stop_token=stop_token,
                ),
                stop_token=stop_token,
            )
            if result is _INTERRUPTED_STOP:
                return 130
            print(f"status={result['status']}")
            print(f"candidates_written={result['candidates_written']}")
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
            )
            if result is _INTERRUPTED_STOP:
                return 130
            print(f"status={result['status']}")
            print(f"translated_count={result['translated_count']}")
            print(f"candidates_artifact={result['candidates_artifact']}")
            return 0

        if args.preprocess_command == "glossary-promote":
            result = _with_cli_progress(
                lambda: promote_glossary_candidates(
                    release_id=args.release,
                    run_id=args.run,
                    config=config,
                    stop_token=stop_token,
                ),
                stop_token=stop_token,
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
                    stop_token=stop_token,
                ),
                stop_token=stop_token,
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
            )
            if stage_result is _INTERRUPTED_STOP:
                return 130
            print(f"status={_status_text(stage_result)}")
            print(f"message={stage_result.message}")
            return _exit_code(stage_result)

        if args.preprocess_command == "graph":
            stage_result = _with_cli_progress(
                lambda: OrchestrationRunner(args.release, args.run, config=config).run_stage(
                    "preprocess-graph",
                    stop_token=stop_token,
                ),
                stop_token=stop_token,
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
