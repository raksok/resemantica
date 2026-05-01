from __future__ import annotations

import re
from hashlib import sha256
from typing import Callable
from xml.etree import ElementTree as ET

from resemantica.epub.models import ChapterDocument, ChapterParseResult, ExtractedRecord
from resemantica.epub.placeholders import build_placeholder_map

_BLOCK_TAGS = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "div", "li", "td", "table"}


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag


def _has_text_content(element: ET.Element) -> bool:
    text_chunks = []
    if element.text:
        text_chunks.append(element.text)
    for child in list(element):
        if child.tail:
            text_chunks.append(child.tail)
    return bool("".join(text_chunks).strip())


def _is_leaf_block(element: ET.Element) -> bool:
    for child in list(element):
        child_tag = _local_name(child.tag).lower()
        if child_tag in _BLOCK_TAGS:
            return False
    return True


def _split_by_sentence(text: str, max_chars: int = 1500) -> list[str]:
    if len(text) <= max_chars:
        return [text]

    sentence_pattern = re.compile(r"[^。！？!?\.]+[。！？!?\.]?")
    sentences = [segment for segment in sentence_pattern.findall(text) if segment]
    if not sentences:
        return [text[idx : idx + max_chars] for idx in range(0, len(text), max_chars)]

    segments: list[str] = []
    current = ""
    for sentence in sentences:
        candidate = current + sentence
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            segments.append(current)
            current = sentence
            continue
        segments.append(sentence[:max_chars])
        current = sentence[max_chars:]

    if current:
        segments.append(current)

    normalized: list[str] = []
    for segment in segments:
        if len(segment) <= max_chars:
            normalized.append(segment)
            continue
        normalized.extend(segment[idx : idx + max_chars] for idx in range(0, len(segment), max_chars))
    return normalized


def parse_chapters(
    chapter_documents: list[ChapterDocument],
    placeholder_map_ref_builder: Callable[[int], str],
) -> list[ChapterParseResult]:
    chapter_results: list[ChapterParseResult] = []

    for chapter in chapter_documents:
        chapter_id = f"ch{chapter.chapter_number:03d}"
        chapter_bytes = chapter.absolute_path.read_bytes()
        chapter_hash = sha256(chapter_bytes).hexdigest()

        result = ChapterParseResult(
            chapter_number=chapter.chapter_number,
            chapter_id=chapter_id,
            source_document_path=chapter.href,
            chapter_source_hash=chapter_hash,
        )

        try:
            root = ET.fromstring(chapter_bytes)
        except ET.ParseError as exc:
            result.errors.append(f"Malformed XHTML: {exc}")
            chapter_results.append(result)
            continue

        block_elements = [
            element
            for element in root.iter()
            if _local_name(element.tag).lower() in _BLOCK_TAGS
            and _is_leaf_block(element)
            and (
                _has_text_content(element)
                or _local_name(element.tag).lower() == "table"
            )
        ]

        block_counter = 0
        for element in block_elements:
            block_counter += 1
            parent_block_id = f"{chapter_id}_blk{block_counter:03d}"
            source_text, placeholders, placeholder_warnings = build_placeholder_map(
                parent_block_id,
                element,
            )
            result.warnings.extend(placeholder_warnings)
            result.placeholders_by_block[parent_block_id] = placeholders

            segments = _split_by_sentence(source_text, max_chars=1500)
            placeholder_ref = placeholder_map_ref_builder(chapter.chapter_number)
            if len(segments) == 1:
                result.records.append(
                    ExtractedRecord(
                        chapter_id=chapter_id,
                        chapter_number=chapter.chapter_number,
                        source_document_path=chapter.href,
                        block_id=parent_block_id,
                        parent_block_id=parent_block_id,
                        segment_id=None,
                        block_order=block_counter,
                        segment_order=None,
                        source_text_zh=segments[0],
                        placeholder_map_ref=placeholder_ref,
                        chapter_source_hash=chapter_hash,
                    )
                )
                continue

            for segment_index, segment in enumerate(segments, start=1):
                segment_id = f"{parent_block_id}_seg{segment_index:02d}"
                result.records.append(
                    ExtractedRecord(
                        chapter_id=chapter_id,
                        chapter_number=chapter.chapter_number,
                        source_document_path=chapter.href,
                        block_id=segment_id,
                        parent_block_id=parent_block_id,
                        segment_id=segment_id,
                        block_order=block_counter,
                        segment_order=segment_index,
                        source_text_zh=segment,
                        placeholder_map_ref=placeholder_ref,
                        chapter_source_hash=chapter_hash,
                    )
                )

        chapter_results.append(result)

    return chapter_results
