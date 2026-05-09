from __future__ import annotations

import re
from dataclasses import dataclass, field

from resemantica.idioms.data import LexiconEntry, load_idiom_lexicon
from resemantica.idioms.validators import normalize_idiom_source

_CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]{4,}")
_FIXED_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"不[\u4e00-\u9fff]不[\u4e00-\u9fff]"),
    re.compile(r"又[\u4e00-\u9fff]又[\u4e00-\u9fff]"),
    re.compile(r"非[\u4e00-\u9fff]{1,3}不可"),
]


@dataclass(slots=True)
class RawIdiomCandidate:
    surface_form: str
    normalized_form: str
    strategies: set[str] = field(default_factory=set)
    appearances: int = 1
    first_seen_chapter: int = 0
    last_seen_chapter: int = 0
    context_snippets: list[str] = field(default_factory=list)
    dictionary_match: bool = False
    literal_meaning_zh: str = ""
    idiomatic_meaning_zh: str = ""
    pos_tags: list[str] = field(default_factory=list)


IDIOM_LEXICON: dict[str, LexiconEntry]
try:
    IDIOM_LEXICON = load_idiom_lexicon()
except Exception:
    IDIOM_LEXICON = {}


def _context_snippet(text: str, start: int, end: int, window: int = 24) -> str:
    left = max(0, start - window)
    right = min(len(text), end + window)
    return text[left:right].replace("\n", " ")


def _count_occurrences(text: str, term: str) -> tuple[int, list[str]]:
    snippets: list[str] = []
    count = 0
    start = 0
    while True:
        index = text.find(term, start)
        if index < 0:
            break
        count += 1
        snippet = _context_snippet(text, index, index + len(term))
        if snippet not in snippets:
            snippets.append(snippet)
        start = index + len(term)
    return count, snippets[:3]


def _add_candidate(
    merged: dict[str, RawIdiomCandidate],
    *,
    surface: str,
    strategy: str,
    appearances: int,
    chapter_number: int,
    snippets: list[str],
    dictionary_entry: LexiconEntry | None = None,
) -> None:
    normalized = normalize_idiom_source(surface)
    if not normalized:
        return
    existing = merged.get(normalized)
    if existing is None:
        merged[normalized] = RawIdiomCandidate(
            surface_form=surface,
            normalized_form=normalized,
            strategies={strategy},
            appearances=max(1, appearances),
            first_seen_chapter=chapter_number,
            last_seen_chapter=chapter_number,
            context_snippets=list(snippets[:3]),
            dictionary_match=dictionary_entry is not None,
            literal_meaning_zh="" if dictionary_entry is None else dictionary_entry.literal_meaning_zh,
            idiomatic_meaning_zh="" if dictionary_entry is None else dictionary_entry.idiomatic_meaning_zh,
        )
        return

    existing.strategies.add(strategy)
    existing.first_seen_chapter = min(existing.first_seen_chapter, chapter_number)
    existing.last_seen_chapter = max(existing.last_seen_chapter, chapter_number)
    for snippet in snippets:
        if snippet not in existing.context_snippets:
            existing.context_snippets.append(snippet)
    existing.context_snippets = existing.context_snippets[:3]
    if dictionary_entry is not None:
        existing.dictionary_match = True
        if not existing.literal_meaning_zh:
            existing.literal_meaning_zh = dictionary_entry.literal_meaning_zh
        if not existing.idiomatic_meaning_zh:
            existing.idiomatic_meaning_zh = dictionary_entry.idiomatic_meaning_zh


def _four_character_terms(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for run in _CJK_RUN_RE.finditer(text):
        value = run.group(0)
        for offset in range(0, len(value) - 3):
            term = value[offset:offset + 4]
            counts[term] = counts.get(term, 0) + 1
    return counts


def generate_chapter_idiom_candidates(
    *,
    chapter_number: int,
    source_text: str,
) -> list[RawIdiomCandidate]:
    merged: dict[str, RawIdiomCandidate] = {}

    for term, entry in IDIOM_LEXICON.items():
        count, snippets = _count_occurrences(source_text, term)
        if count:
            _add_candidate(
                merged,
                surface=term,
                strategy="lexicon",
                appearances=count,
                chapter_number=chapter_number,
                snippets=snippets,
                dictionary_entry=entry,
            )

    for term, count in _four_character_terms(source_text).items():
        lexicon_entry = IDIOM_LEXICON.get(term)
        if lexicon_entry is None and count < 2:
            continue
        _, snippets = _count_occurrences(source_text, term)
        _add_candidate(
            merged,
            surface=term,
            strategy="four_char",
            appearances=count,
            chapter_number=chapter_number,
            snippets=snippets,
            dictionary_entry=lexicon_entry,
        )

    for pattern in _FIXED_PATTERNS:
        for match in pattern.finditer(source_text):
            term = match.group(0)
            count, snippets = _count_occurrences(source_text, term)
            _add_candidate(
                merged,
                surface=term,
                strategy="fixed_pattern",
                appearances=count,
                chapter_number=chapter_number,
                snippets=snippets,
            )

    return sorted(merged.values(), key=lambda item: (item.first_seen_chapter, item.normalized_form))


def merge_across_chapters(
    accumulator: dict[str, RawIdiomCandidate],
    chapter_candidates: list[RawIdiomCandidate],
) -> dict[str, RawIdiomCandidate]:
    for candidate in chapter_candidates:
        existing = accumulator.get(candidate.normalized_form)
        if existing is None:
            accumulator[candidate.normalized_form] = RawIdiomCandidate(
                surface_form=candidate.surface_form,
                normalized_form=candidate.normalized_form,
                strategies=set(candidate.strategies),
                appearances=candidate.appearances,
                first_seen_chapter=candidate.first_seen_chapter,
                last_seen_chapter=candidate.last_seen_chapter,
                context_snippets=list(candidate.context_snippets),
                dictionary_match=candidate.dictionary_match,
                literal_meaning_zh=candidate.literal_meaning_zh,
                idiomatic_meaning_zh=candidate.idiomatic_meaning_zh,
                pos_tags=list(candidate.pos_tags),
            )
            continue

        existing.strategies.update(candidate.strategies)
        existing.appearances += candidate.appearances
        existing.first_seen_chapter = min(existing.first_seen_chapter, candidate.first_seen_chapter)
        existing.last_seen_chapter = max(existing.last_seen_chapter, candidate.last_seen_chapter)
        for snippet in candidate.context_snippets:
            if snippet not in existing.context_snippets:
                existing.context_snippets.append(snippet)
        existing.context_snippets = existing.context_snippets[:3]
        existing.dictionary_match = existing.dictionary_match or candidate.dictionary_match
        if not existing.literal_meaning_zh:
            existing.literal_meaning_zh = candidate.literal_meaning_zh
        if not existing.idiomatic_meaning_zh:
            existing.idiomatic_meaning_zh = candidate.idiomatic_meaning_zh
        if not existing.pos_tags:
            existing.pos_tags = list(candidate.pos_tags)
    return accumulator
