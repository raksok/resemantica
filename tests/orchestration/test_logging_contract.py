from __future__ import annotations

import re
from pathlib import Path

PIPELINE_MODULES = [
    Path("src/resemantica/summaries/pipeline.py"),
    Path("src/resemantica/summaries/continuity.py"),
    Path("src/resemantica/graph/pipeline.py"),
    Path("src/resemantica/translation/pipeline.py"),
    Path("src/resemantica/orchestration/runner.py"),
]

LOGGER_WARNING_OR_ERROR = re.compile(r"logger(?:\.opt\([^)]*\))?\.(?:warning|error)\(")
PAIRING_TOKENS = (
    "emit_event(",
    "_emit(",
    "_emit_translation_event(",
    "event_callback",
    "warning_callback",
    "fallback_callback",
)
ALLOWLIST = {
    ("src/resemantica/translation/pipeline.py", "packet_metadata table not found, continuing without packet hash"),
    ("src/resemantica/orchestration/runner.py", "Failed to generate glossary review artifacts"),
    ("src/resemantica/orchestration/runner.py", "Failed to generate idiom review artifacts"),
}


def test_run_context_warnings_and_errors_are_event_paired() -> None:
    violations: list[str] = []
    for path in PIPELINE_MODULES:
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            if LOGGER_WARNING_OR_ERROR.search(line) is None:
                continue
            window = "\n".join(lines[max(0, index - 8) : min(len(lines), index + 36)])
            if any(path.as_posix() == item_path and text in window for item_path, text in ALLOWLIST):
                continue
            if not any(token in window for token in PAIRING_TOKENS):
                violations.append(f"{path}:{index + 1}: {line.strip()}")

    assert violations == []
