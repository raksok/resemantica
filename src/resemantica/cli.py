from __future__ import annotations

import argparse
from pathlib import Path
import sys

from resemantica.epub.extractor import extract_epub
from resemantica.settings import load_config
from resemantica.translation.pipeline import translate_chapter


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

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
