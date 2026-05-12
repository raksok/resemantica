import math
from dataclasses import dataclass

from loguru import logger

from resemantica.glossary.candidate_gen import RawCandidate


@dataclass(slots=True)
class CorpusStats:
    term_frequency: dict[str, int]
    document_frequency: dict[str, int]
    total_chapters: int
    total_tokens: int


@dataclass(slots=True)
class ScoredCandidate:
    raw: RawCandidate
    tf_idf: float
    c_value: float
    composite_score: float


def compute_corpus_stats(per_chapter_candidates: dict[int, list[RawCandidate]]) -> CorpusStats:
    """
    Aggregate per-chapter candidate occurrences into corpus-level counts.
    Note: total_tokens is a rough estimate since we only have candidates here,
    we can just use the sum of all term frequencies as a proxy, or it can be passed in.
    For tf-idf, we don't necessarily need total_tokens if we just use raw TF.
    """
    term_freq: dict[str, int] = {}
    doc_freq: dict[str, int] = {}
    total_chapters = len(per_chapter_candidates)
    total_tokens = 0

    for _, candidates in per_chapter_candidates.items():
        chapter_terms = set()
        for c in candidates:
            norm = c.normalized_form
            # Since RawCandidate within a chapter already has appearances aggregated
            # for that chapter, we add it to term_freq.
            term_freq[norm] = term_freq.get(norm, 0) + c.appearances
            total_tokens += c.appearances
            chapter_terms.add(norm)

        for term in chapter_terms:
            doc_freq[term] = doc_freq.get(term, 0) + 1

    result = CorpusStats(
        term_frequency=term_freq,
        document_frequency=doc_freq,
        total_chapters=total_chapters,
        total_tokens=total_tokens
    )
    logger.debug(
        "Corpus stats: {} chapters, {} unique terms, {} total tokens",
        total_chapters,
        len(term_freq),
        total_tokens,
    )
    return result


def compute_c_value(
    candidates: list[RawCandidate],
    term_freq: dict[str, int]
) -> dict[str, float]:
    """
    Compute C-value for multi-word terms.
    C-value = log2(|term|) * ( freq - (1/c) * sum(freq_of_superstrings) )
    where |term| is length of term (in characters for Chinese, or tokens).
    c is number of unique superstrings.
    If no superstrings, C-value = log2(|term|) * freq.

    Uses O(n·L²) substring enumeration instead of the naive O(n²) nested loop,
    where L is max term length. At L ≤ 20 this is at most 400 checks per term
    regardless of total term count.
    """
    all_terms = {c.normalized_form for c in candidates}
    terms = sorted(all_terms, key=len, reverse=True)

    super_info: dict[str, tuple[int, int]] = {t: (0, 0) for t in terms}

    for term in terms:
        freq = term_freq.get(term, 0)
        t_len = len(term)

        # Enumerate all substrings (2 to t_len-1 chars) that are also terms.
        # Use a seen set to avoid double-counting the same substring appearing
        # at multiple positions within the same superstring.
        seen: set[str] = set()
        for sub_len in range(2, t_len):
            for start in range(t_len - sub_len + 1):
                sub = term[start : start + sub_len]
                if sub in all_terms and sub not in seen:
                    seen.add(sub)
                    s_freq, s_cnt = super_info[sub]
                    super_info[sub] = (s_freq + freq, s_cnt + 1)

    c_values: dict[str, float] = {}
    for term in terms:
        length = len(term)
        if length < 2:
            c_values[term] = 0.0
            continue

        freq = term_freq.get(term, 0)
        sum_freq, count = super_info[term]

        if count == 0:
            val = math.log2(length) * freq
        else:
            val = math.log2(length) * (freq - (1.0 / count) * sum_freq)

        c_values[term] = max(0.0, val)

    return c_values


def score_candidates(
    candidates: list[RawCandidate],
    stats: CorpusStats,
    summary_term_set: set[str] | None = None,
) -> list[ScoredCandidate]:
    """
    Compute TF-IDF and C-value for each candidate.

    Composite score formula:
      composite = 0.3 * norm_tf_idf + 0.3 * norm_c_value + 0.2 * strategy_count + 0.2 * coverage_ratio

    where:
      norm_tf_idf = tf_idf / max(tf_idf across all candidates)
      norm_c_value = c_value / max(c_value) for len >= 2, else 0
      strategy_count = len(source_strategies) / max_strategies
      coverage_ratio = document_frequency / total_chapters
    """
    if not candidates:
        return []

    c_values = compute_c_value(candidates, stats.term_frequency)

    # Compute TF-IDF
    tf_idfs = {}
    for c in candidates:
        norm = c.normalized_form
        tf = stats.term_frequency.get(norm, 0)
        df = stats.document_frequency.get(norm, 0)
        idf = math.log(stats.total_chapters / (df + 1e-9)) if stats.total_chapters > 0 else 0
        tf_idfs[norm] = tf * idf

    # Normalize TF-IDF and C-Value
    max_tf_idf = max(tf_idfs.values()) if tf_idfs else 1.0
    if max_tf_idf <= 0:
        max_tf_idf = 1.0

    max_c_value = max(c_values.values()) if c_values else 1.0
    if max_c_value <= 0:
        max_c_value = 1.0

    max_strategies = 5.0 # We have ~5 main strategies

    scored = []
    for c in candidates:
        norm = c.normalized_form
        tf_idf = tf_idfs[norm]
        c_val = c_values[norm]

        norm_tf_idf = tf_idf / max_tf_idf
        norm_c_value = c_val / max_c_value
        strategy_count = len(c.strategies) / max_strategies
        coverage_ratio = stats.document_frequency.get(norm, 0) / stats.total_chapters if stats.total_chapters > 0 else 0

        composite = 0.3 * norm_tf_idf + 0.3 * norm_c_value + 0.2 * strategy_count + 0.2 * coverage_ratio

        # Strategy signal multiplier: boost high-confidence strategies,
        # penalize pure n-gram (which is mostly noise).
        has_ner = "ner" in c.strategies
        has_heuristic = "heuristic" in c.strategies
        has_dict = "dictionary" in c.strategies
        n_gram_only = len(c.strategies) == 1 and "n_gram" in c.strategies
        if has_ner:
            composite *= 1.2
        elif has_heuristic or has_dict:
            composite *= 1.1
        elif n_gram_only:
            composite *= 0.8

        # Summary-verified term boost: terms appearing in new_terms or
        # characters_mentioned get a moderate lift.
        if summary_term_set and norm in summary_term_set:
            composite *= 1.15

        scored.append(
            ScoredCandidate(
                raw=c,
                tf_idf=tf_idf,
                c_value=c_val,
                composite_score=composite
            )
        )

    # Sort descending by composite score
    scored.sort(key=lambda x: x.composite_score, reverse=True)
    if scored:
        logger.debug(
            "Scored {} candidates: top={:.4f}, median={:.4f}, min={:.4f}",
            len(scored),
            scored[0].composite_score,
            scored[len(scored) // 2].composite_score,
            scored[-1].composite_score,
        )
    return scored
