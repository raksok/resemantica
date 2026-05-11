from dataclasses import dataclass, field

from loguru import logger

from resemantica.glossary.data import load_data_file
from resemantica.glossary.segmenter import SegmentedToken, segment_chapter


@dataclass(slots=True)
class RawCandidate:
    surface_form: str
    normalized_form: str
    pos_tags: list[str]
    ner_label: str | None
    type_prior: str
    strategies: set[str] = field(default_factory=set)
    appearances: int = 1
    # Store at most 3 snippets for context
    context_snippets: list[str] = field(default_factory=list)


# Categories we map to (matching models.py GlossaryCategory)
CAT_CHARACTER = "character"
CAT_LOCATION = "location"
CAT_FACTION = "faction"
CAT_TECHNIQUE = "technique"
CAT_ITEM = "item_artifact"
CAT_CONCEPT = "realm_concept"
CAT_OTHER = "generic_role"


# Load dictionaries
try:
    SURNAMES = load_data_file("surnames.txt")
except Exception:
    SURNAMES = set()

try:
    WEBNOVEL_DICT = load_data_file("webnovel_dict.txt")
except Exception:
    WEBNOVEL_DICT = set()

try:
    COMMON_WORDS = load_data_file("common_words.txt")
except Exception:
    COMMON_WORDS = set()


# Common suffixes for heuristics
FACTION_SUFFIXES = {"宗", "派", "教", "谷", "门", "岛", "宫", "阁", "殿", "会", "帮", "国"}
LOCATION_SUFFIXES = {"山", "海", "河", "江", "湖", "城", "镇", "村", "界", "境", "洞", "天", "府"}
TECHNIQUE_SUFFIXES = {"功", "法", "诀", "经", "术", "剑", "拳", "掌", "指", "腿", "步", "阵", "阵法"}


def _get_context_snippet(text: str, start: int, end: int, window: int = 20) -> str:
    s = max(0, start - window)
    e = min(len(text), end + window)
    return text[s:e].replace("\n", " ")


def extract_ner_candidates(tokens: list[SegmentedToken], text: str) -> list[RawCandidate]:
    candidates = []
    i = 0
    while i < len(tokens):
        if tokens[i].ner:
            label = tokens[i].ner
            start_i = i
            while i + 1 < len(tokens) and tokens[i + 1].ner == label:
                i += 1

            # Combine tokens
            entity_tokens = tokens[start_i : i + 1]
            surface = "".join(t.text for t in entity_tokens)

            type_prior = CAT_OTHER
            if label == "PERSON":
                type_prior = CAT_CHARACTER
            elif label == "LOC" or label == "GPE":
                type_prior = CAT_LOCATION
            elif label == "ORG":
                type_prior = CAT_FACTION

            snippet = _get_context_snippet(text, entity_tokens[0].offset_start, entity_tokens[-1].offset_end)

            candidates.append(
                RawCandidate(
                    surface_form=surface,
                    normalized_form=surface,
                    pos_tags=[t.pos for t in entity_tokens],
                    ner_label=label,
                    type_prior=type_prior,
                    strategies={"ner"},
                    context_snippets=[snippet]
                )
            )
        i += 1
    return candidates


def extract_pos_noun_phrases(tokens: list[SegmentedToken], text: str) -> list[RawCandidate]:
    candidates = []
    # Extract sequences of NR (proper noun) or NN (noun) or FW
    # We want at least length 2 if it's single char tokens, or length 1 if multi-char token
    i = 0
    valid_poses = {"NR", "NN", "NNP", "FW", "NZ"}
    while i < len(tokens):
        if tokens[i].pos in valid_poses:
            start_i = i
            while i + 1 < len(tokens) and tokens[i + 1].pos in valid_poses:
                i += 1

            entity_tokens = tokens[start_i : i + 1]
            surface = "".join(t.text for t in entity_tokens)

            # Filter out single character words unless they are specifically in webnovel dict
            if len(surface) > 1:
                snippet = _get_context_snippet(text, entity_tokens[0].offset_start, entity_tokens[-1].offset_end)
                candidates.append(
                    RawCandidate(
                        surface_form=surface,
                        normalized_form=surface,
                        pos_tags=[t.pos for t in entity_tokens],
                        ner_label=None,
                        type_prior=CAT_OTHER,
                        strategies={"pos_np"},
                        context_snippets=[snippet]
                    )
                )
        i += 1
    return candidates


def extract_heuristic_patterns(tokens: list[SegmentedToken], text: str) -> list[RawCandidate]:
    candidates = []

    # Check sequences up to length 4 for heuristics
    for i in range(len(tokens)):
        for j in range(i, min(i + 4, len(tokens))):
            entity_tokens = tokens[i : j + 1]
            surface = "".join(t.text for t in entity_tokens)

            if not surface or len(surface) < 2 or len(surface) > 6:
                continue

            type_prior = None

            # 1. Character names (Surname + 1-2 chars)
            if 2 <= len(surface) <= 3 and surface[0] in SURNAMES or surface[:2] in SURNAMES:
                type_prior = CAT_CHARACTER
            # 2. Factions
            elif surface[-1] in FACTION_SUFFIXES:
                type_prior = CAT_FACTION
            # 3. Locations
            elif surface[-1] in LOCATION_SUFFIXES:
                type_prior = CAT_LOCATION
            # 4. Techniques
            elif surface[-1] in TECHNIQUE_SUFFIXES or (len(surface) > 2 and surface[-2:] in TECHNIQUE_SUFFIXES):
                type_prior = CAT_TECHNIQUE

            if type_prior:
                snippet = _get_context_snippet(text, entity_tokens[0].offset_start, entity_tokens[-1].offset_end)
                candidates.append(
                    RawCandidate(
                        surface_form=surface,
                        normalized_form=surface,
                        pos_tags=[t.pos for t in entity_tokens],
                        ner_label=None,
                        type_prior=type_prior,
                        strategies={"heuristic"},
                        context_snippets=[snippet]
                    )
                )
    return candidates


def extract_webnovel_dict(tokens: list[SegmentedToken], text: str) -> list[RawCandidate]:
    candidates = []
    # Match any n-gram that is in WEBNOVEL_DICT
    for i in range(len(tokens)):
        for j in range(i, min(i + 4, len(tokens))):
            entity_tokens = tokens[i : j + 1]
            surface = "".join(t.text for t in entity_tokens)

            if surface in WEBNOVEL_DICT:
                snippet = _get_context_snippet(text, entity_tokens[0].offset_start, entity_tokens[-1].offset_end)
                candidates.append(
                    RawCandidate(
                        surface_form=surface,
                        normalized_form=surface,
                        pos_tags=[t.pos for t in entity_tokens],
                        ner_label=None,
                        type_prior=CAT_CONCEPT,
                        strategies={"dictionary"},
                        context_snippets=[snippet]
                    )
                )
    return candidates


def extract_ngrams(tokens: list[SegmentedToken], text: str) -> list[RawCandidate]:
    candidates = []
    # Simple extraction of 2-5 grams
    # The deduplication and filtering will handle frequencies
    for i in range(len(tokens)):
        for j in range(i + 1, min(i + 5, len(tokens))):
            entity_tokens = tokens[i : j + 1]
            surface = "".join(t.text for t in entity_tokens)
            # Skip if any token is punctuation or whitespace
            if not surface.isalnum():
                continue

            snippet = _get_context_snippet(text, entity_tokens[0].offset_start, entity_tokens[-1].offset_end)
            candidates.append(
                RawCandidate(
                    surface_form=surface,
                    normalized_form=surface,
                    pos_tags=[t.pos for t in entity_tokens],
                    ner_label=None,
                    type_prior=CAT_OTHER,
                    strategies={"n_gram"},
                    context_snippets=[snippet]
                )
            )
    return candidates


def merge_candidates(candidates: list[RawCandidate]) -> list[RawCandidate]:
    """
    Merge candidates with the same normalized_form.
    Aggregate strategies, appearances, and snippets.
    Prioritize certain type_priors over CAT_OTHER.
    """
    merged: dict[str, RawCandidate] = {}

    type_priority = {
        CAT_CHARACTER: 10,
        CAT_LOCATION: 9,
        CAT_FACTION: 8,
        CAT_TECHNIQUE: 7,
        CAT_ITEM: 6,
        CAT_CONCEPT: 5,
        CAT_OTHER: 0
    }

    for c in candidates:
        norm = c.normalized_form
        if norm not in merged:
            merged[norm] = RawCandidate(
                surface_form=c.surface_form,
                normalized_form=norm,
                pos_tags=c.pos_tags,
                ner_label=c.ner_label,
                type_prior=c.type_prior,
                strategies=set(c.strategies),
                appearances=c.appearances,
                context_snippets=list(c.context_snippets)
            )
        else:
            existing = merged[norm]
            existing.appearances += c.appearances
            existing.strategies.update(c.strategies)

            # Keep up to 3 unique snippets
            for snip in c.context_snippets:
                if snip not in existing.context_snippets:
                    existing.context_snippets.append(snip)
            existing.context_snippets = existing.context_snippets[:3]

            # Update type prior if current candidate has higher priority
            if type_priority.get(c.type_prior, 0) > type_priority.get(existing.type_prior, 0):
                existing.type_prior = c.type_prior

            # Keep NER label if we didn't have one
            if not existing.ner_label and c.ner_label:
                existing.ner_label = c.ner_label

    return list(merged.values())


def merge_across_chapters(
    accumulator: dict[str, RawCandidate],
    chapter_candidates: list[RawCandidate],
) -> dict[str, RawCandidate]:
    """
    Incremental merge: update accumulator with candidates from one chapter.
    Same merge logic as merge_candidates() but operates on a persistent dict
    owned by the caller. Call once per chapter.

    Returns the accumulator dict for convenience.
    """
    type_priority = {
        CAT_CHARACTER: 10,
        CAT_LOCATION: 9,
        CAT_FACTION: 8,
        CAT_TECHNIQUE: 7,
        CAT_ITEM: 6,
        CAT_CONCEPT: 5,
        CAT_OTHER: 0,
    }

    for c in chapter_candidates:
        norm = c.normalized_form
        if norm not in accumulator:
            accumulator[norm] = RawCandidate(
                surface_form=c.surface_form,
                normalized_form=norm,
                pos_tags=c.pos_tags,
                ner_label=c.ner_label,
                type_prior=c.type_prior,
                strategies=set(c.strategies),
                appearances=c.appearances,
                context_snippets=list(c.context_snippets),
            )
        else:
            existing = accumulator[norm]
            existing.appearances += c.appearances
            existing.strategies.update(c.strategies)

            for snip in c.context_snippets:
                if snip not in existing.context_snippets:
                    existing.context_snippets.append(snip)
            existing.context_snippets = existing.context_snippets[:3]

            if type_priority.get(c.type_prior, 0) > type_priority.get(existing.type_prior, 0):
                existing.type_prior = c.type_prior

            if not existing.ner_label and c.ner_label:
                existing.ner_label = c.ner_label

    return accumulator


def generate_chapter_candidates(text: str) -> list[RawCandidate]:
    """
    Orchestrate full candidate generation for a single chapter text.
    Returns deduplicated candidates.
    """
    logger.debug("Generating candidates from text ({} chars)", len(text))
    tokens = segment_chapter(text)

    all_candidates: list[RawCandidate] = []

    ner = extract_ner_candidates(tokens, text)
    all_candidates.extend(ner)
    logger.debug("NER strategy: {} candidates", len(ner))

    pos = extract_pos_noun_phrases(tokens, text)
    all_candidates.extend(pos)
    logger.debug("POS noun-phrase strategy: {} candidates", len(pos))

    heuristic = extract_heuristic_patterns(tokens, text)
    all_candidates.extend(heuristic)
    logger.debug("Heuristic pattern strategy: {} candidates", len(heuristic))

    webnovel = extract_webnovel_dict(tokens, text)
    all_candidates.extend(webnovel)
    logger.debug("Webnovel dictionary strategy: {} candidates", len(webnovel))

    ngrams = extract_ngrams(tokens, text)
    all_candidates.extend(ngrams)
    logger.debug("N-gram strategy: {} candidates", len(ngrams))

    merged = merge_candidates(all_candidates)
    logger.debug(
        "Merged {} raw candidates into {} unique terms",
        len(all_candidates),
        len(merged),
    )
    return merged
