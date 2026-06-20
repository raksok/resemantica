from __future__ import annotations

from resemantica.glossary.models import LockedGlossaryEntry


def _format_glossary_context(entries: list[LockedGlossaryEntry]) -> str:
    if not entries:
        return "(empty)"
    return "\n".join(
        f"- {entry.source_term} => {entry.target_term}"
        for entry in entries
    )


def select_source_local_glossary(
    *,
    source_text_zh: str,
    locked_glossary: list[LockedGlossaryEntry],
) -> list[LockedGlossaryEntry]:
    return [
        entry
        for entry in locked_glossary
        if entry.source_term and entry.source_term in source_text_zh
    ]
