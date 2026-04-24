from __future__ import annotations

import argparse
from pathlib import Path
import sys

from resemantica.epub.extractor import extract_epub
from resemantica.graph.pipeline import preprocess_graph
from resemantica.glossary.pipeline import (
    discover_glossary_candidates,
    promote_glossary_candidates,
    translate_glossary_candidates,
)
from resemantica.idioms.pipeline import preprocess_idioms
from resemantica.settings import load_config
from resemantica.summaries.pipeline import preprocess_summaries
from resemantica.translation.pipeline import translate_chapter


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
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "epub-roundtrip":
        config = load_config(args.config)
        roundtrip_result = extract_epub(
            input_path=args.input,
            release_id=args.release,
            config=config,
        )
        print(f"status={roundtrip_result.status}")
        print(f"release_root={roundtrip_result.release_root}")
        print(f"rebuilt_epub={roundtrip_result.rebuilt_epub_path}")
        print(f"validation_report={roundtrip_result.validation_report_path}")
        return 0 if roundtrip_result.status == "success" else 1

    if args.command == "translate-chapter":
        config = load_config(args.config)
        translation_result = translate_chapter(
            release_id=args.release,
            chapter_number=args.chapter,
            run_id=args.run,
            config=config,
            force_pass1=args.force_pass1,
        )
        print(f"status={translation_result['status']}")
        print(f"pass1_artifact={translation_result['pass1_artifact']}")
        print(f"pass2_artifact={translation_result['pass2_artifact']}")
        print(f"structure_report={translation_result['structure_report']}")
        print(f"fidelity_report={translation_result['fidelity_report']}")
        return 0

    if args.command == "preprocess":
        config = load_config(args.config)

        if args.preprocess_command == "glossary-discover":
            result = discover_glossary_candidates(
                release_id=args.release,
                run_id=args.run,
                config=config,
            )
            print(f"status={result['status']}")
            print(f"candidates_written={result['candidates_written']}")
            print(f"candidates_artifact={result['candidates_artifact']}")
            return 0

        if args.preprocess_command == "glossary-translate":
            result = translate_glossary_candidates(
                release_id=args.release,
                run_id=args.run,
                config=config,
            )
            print(f"status={result['status']}")
            print(f"translated_count={result['translated_count']}")
            print(f"candidates_artifact={result['candidates_artifact']}")
            return 0

        if args.preprocess_command == "glossary-promote":
            result = promote_glossary_candidates(
                release_id=args.release,
                run_id=args.run,
                config=config,
            )
            print(f"status={result['status']}")
            print(f"candidate_count={result['candidate_count']}")
            print(f"promoted_count={result['promoted_count']}")
            print(f"conflict_count={result['conflict_count']}")
            print(f"candidates_artifact={result['candidates_artifact']}")
            print(f"conflicts_artifact={result['conflicts_artifact']}")
            return 0

        if args.preprocess_command == "summaries":
            result = preprocess_summaries(
                release_id=args.release,
                run_id=args.run,
                config=config,
            )
            print(f"status={result['status']}")
            print(f"chapters_processed={result['chapters_processed']}")
            return 0

        if args.preprocess_command == "idioms":
            result = preprocess_idioms(
                release_id=args.release,
                run_id=args.run,
                config=config,
            )
            print(f"status={result['status']}")
            print(f"chapters_processed={result['chapters_processed']}")
            print(f"candidates_written={result['candidates_written']}")
            print(f"promoted_count={result['promoted_count']}")
            print(f"conflict_count={result['conflict_count']}")
            print(f"candidates_artifact={result['candidates_artifact']}")
            print(f"policies_artifact={result['policies_artifact']}")
            print(f"conflicts_artifact={result['conflicts_artifact']}")
            return 0

        if args.preprocess_command == "graph":
            result = preprocess_graph(
                release_id=args.release,
                run_id=args.run,
                config=config,
            )
            print(f"status={result['status']}")
            print(f"provisional_entities={result['provisional_entities']}")
            print(f"confirmed_entities={result['confirmed_entities']}")
            print(f"deferred_pending_count={result['deferred_pending_count']}")
            print(f"deferred_graph_created_count={result['deferred_graph_created_count']}")
            print(f"snapshot_hash={result['snapshot_hash']}")
            print(f"snapshot_artifact={result['snapshot_artifact']}")
            print(f"warnings_artifact={result['warnings_artifact']}")
            return 0

        parser.print_help()
        return 2

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
