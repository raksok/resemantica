from __future__ import annotations

from resemantica.glossary.models import LockedGlossaryEntry


def _format_glossary_context(entries: list[LockedGlossaryEntry]) -> str:
    if not entries:
        return "(empty)"
    return "\n".join(
        f"- {entry.source_term} => {entry.target_term} ({entry.category})"
        for entry in entries
    )
