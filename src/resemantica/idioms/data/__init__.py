from __future__ import annotations

from dataclasses import dataclass
from importlib import resources


@dataclass(frozen=True, slots=True)
class LexiconEntry:
    source_text: str
    literal_meaning_zh: str
    idiomatic_meaning_zh: str


def load_idiom_lexicon() -> dict[str, LexiconEntry]:
    path = resources.files(__package__).joinpath("idiom_lexicon.tsv")
    entries: dict[str, LexiconEntry] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        source, literal, idiomatic = (part.strip() for part in parts[:3])
        if source:
            entries[source] = LexiconEntry(
                source_text=source,
                literal_meaning_zh=literal,
                idiomatic_meaning_zh=idiomatic,
            )
    return entries
