from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re

from resemantica.glossary.models import GlossaryCandidate
from resemantica.glossary.validators import normalize_term

_PLACEHOLDER_RE = re.compile(r"⟦/?[A-Z]+_\d+⟧")
_CJK_TERM_RE = re.compile(r"[\u4e00-\u9fff]{2,12}")


@dataclass(slots=True)
class _Aggregate:
    source_term: str
    category: str
    first_seen_chapter: int
    last_seen_chapter: int
    appearance_count: int
    evidence_snippet: str


def _strip_placeholders(text: str) -> str:
    return _PLACEHOLDER_RE.sub("", text)


def _infer_category(source_term: str) -> str:
    if source_term.endswith(("门", "派", "宗", "帮", "盟")):
        return "faction"
    if source_term.endswith(("山", "城", "宫", "谷", "峰", "州", "国", "镇", "村")):
        return "location"
    return "generic_role"


def _snippet(text: str, term: str) -> str:
    position = text.find(term)
    if position < 0:
        return text[:80]
    start = max(0, position - 20)
    end = min(len(text), position + len(term) + 20)
    return text[start:end]


def discover_candidates_from_extracted(
    *,
    release_id: str,
    extracted_chapters_dir: Path,
    discovery_run_id: str,
) -> list[GlossaryCandidate]:
    aggregates: dict[tuple[str, str], _Aggregate] = {}
    chapter_files = sorted(extracted_chapters_dir.glob("chapter-*.json"))

    for chapter_file in chapter_files:
        payload = json.loads(chapter_file.read_text(encoding="utf-8"))
        chapter_number = int(payload.get("chapter_number", 0))
        records = list(payload.get("records", []))
        for record in records:
            text = _strip_placeholders(str(record.get("source_text_zh", "")))
            if not text.strip():
                continue
            matches = _CJK_TERM_RE.findall(text)
            if not matches:
                continue

            counts: defaultdict[str, int] = defaultdict(int)
            for term in matches:
                counts[term] += 1

            for term, count in counts.items():
                normalized_source = normalize_term(term)
                if not normalized_source:
                    continue
                category = _infer_category(term)
                key = (category, normalized_source)
                current = aggregates.get(key)
                if current is None:
                    aggregates[key] = _Aggregate(
                        source_term=term,
                        category=category,
                        first_seen_chapter=chapter_number,
                        last_seen_chapter=chapter_number,
                        appearance_count=count,
                        evidence_snippet=_snippet(text, term),
                    )
                    continue
                current.first_seen_chapter = min(current.first_seen_chapter, chapter_number)
                current.last_seen_chapter = max(current.last_seen_chapter, chapter_number)
                current.appearance_count += count

    discovered: list[GlossaryCandidate] = []
    for category, normalized_source in sorted(aggregates.keys()):
        aggregate = aggregates[(category, normalized_source)]
        candidate_id = f"gcan_{sha256(f'{release_id}:{category}:{normalized_source}'.encode('utf-8')).hexdigest()[:24]}"
        discovered.append(
            GlossaryCandidate(
                candidate_id=candidate_id,
                release_id=release_id,
                source_term=aggregate.source_term,
                normalized_source_term=normalized_source,
                category=category,
                source_language="zh",
                first_seen_chapter=aggregate.first_seen_chapter,
                last_seen_chapter=aggregate.last_seen_chapter,
                appearance_count=aggregate.appearance_count,
                evidence_snippet=aggregate.evidence_snippet,
                candidate_translation_en=None,
                normalized_target_term=None,
                discovery_run_id=discovery_run_id,
                translation_run_id=None,
                candidate_status="discovered",
                validation_status="pending",
                conflict_reason=None,
                translator_model_name=None,
                translator_prompt_version=None,
                schema_version=1,
            )
        )
    return discovered
