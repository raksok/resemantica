from __future__ import annotations

import argparse
from pathlib import Path
import sys

from resemantica.epub.extractor import extract_epub
from resemantica.settings import load_config


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
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "epub-roundtrip":
        config = load_config(args.config)
        result = extract_epub(
            input_path=args.input,
            release_id=args.release,
            config=config,
        )
        print(f"status={result.status}")
        print(f"release_root={result.release_root}")
        print(f"rebuilt_epub={result.rebuilt_epub_path}")
        print(f"validation_report={result.validation_report_path}")
        return 0 if result.status == "success" else 1

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

