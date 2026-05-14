from __future__ import annotations

import re
import warnings
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, cast

from loguru import logger

_HANLP_PIPELINE: Any | None = None
_HANLP_LOADED = False
_HANLP_AVAILABLE = False


@dataclass(slots=True)
class SegmentedToken:
    text: str
    pos: str
    ner: str | None
    offset_start: int
    offset_end: int


@contextmanager
def _suppress_hanlp_dependency_warnings() -> Iterator[None]:
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r".*invalid escape sequence.*",
            category=SyntaxWarning,
            module=r"phrasetree(\.|$).*",
        )
        warnings.filterwarnings(
            "ignore",
            message=r".*pynvml.*deprecated.*|.*deprecated.*pynvml.*",
            category=FutureWarning,
            module=r"torch\.cuda(\.|$).*",
        )
        warnings.filterwarnings(
            "ignore",
            message=r".*non-tuple.*multidimensional indexing.*",
            category=UserWarning,
            module=r"hanlp\.components\.parsers\.alg(\.|$).*",
        )
        yield


def _load_hanlp_pipeline() -> Any | None:
    global _HANLP_PIPELINE, _HANLP_LOADED, _HANLP_AVAILABLE
    if _HANLP_LOADED:
        return _HANLP_PIPELINE

    _HANLP_LOADED = True
    try:
        with _suppress_hanlp_dependency_warnings():
            import hanlp  # type: ignore

            # Load the MTL pipeline (tok/fine, pos/ctb, ner/msra)
            logger.info("Loading HanLP MTL pipeline. This may take a moment...")
            # Note: 'CLOSE_TOK_POS_NER' is a common MTL preset in HanLP
            _HANLP_PIPELINE = hanlp.load(hanlp.pretrained.mtl.CLOSE_TOK_POS_NER_SRL_DEP_SDP_CON_ELECTRA_BASE_ZH)
        _HANLP_AVAILABLE = True
        logger.info("HanLP pipeline loaded successfully.")
    except ImportError:
        logger.warning("HanLP not installed. Falling back to simple character/word segmentation.")
        _HANLP_AVAILABLE = False
    except Exception as exc:
        logger.error("Failed to load HanLP pipeline: {}. Falling back to simple segmentation.", exc)
        _HANLP_AVAILABLE = False

    return _HANLP_PIPELINE


def _fallback_segment(text: str) -> list[SegmentedToken]:
    """
    Fallback segmentation if HanLP is not available.
    Uses regex to extract Chinese words, character by character for CJK,
    and groups alphanumeric words.
    """
    tokens = []
    # Match alphanumeric sequences or individual non-whitespace characters
    for match in re.finditer(r"[a-zA-Z0-9]+|[^\s]", text):
        token_str = match.group(0)
        start = match.start()
        end = match.end()
        # Very crude POS tag guess based on ascii vs non-ascii
        pos = "FW" if token_str.isascii() and token_str.isalnum() else ""
        tokens.append(
            SegmentedToken(
                text=token_str,
                pos=pos,
                ner=None,
                offset_start=start,
                offset_end=end,
            )
        )
    return tokens


def segment_chapter(source_text: str) -> list[SegmentedToken]:
    """
    Run HanLP tokenization + POS + NER on source text.
    Lazy-loads the HanLP pipeline on first call.
    Returns flat token list with POS and NER annotations.
    Falls back to character-level iteration if HanLP is unavailable.
    """
    pipeline = _load_hanlp_pipeline()
    if pipeline is None:
        return _fallback_segment(source_text)

    # HanLP can process a string directly or a list of sentences.
    # To get accurate offsets, it's sometimes easier to process line by line,
    # or let HanLP handle the whole string. We'll pass the whole string.
    # The output dict has keys like 'tok/fine', 'pos/ctb', 'ner/msra'
    # Wait, HanLP expects a list of sentences or a single string (sentence).
    # Passing a very long string might fail or be slow. Let's split by lines first.

    tokens: list[SegmentedToken] = []
    lines = source_text.splitlines(keepends=True)

    current_offset = 0
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            current_offset += len(line)
            continue

        try:
            # Call pipeline on the line
            with _suppress_hanlp_dependency_warnings():
                doc = pipeline(line)
            toks = cast(list[str], doc["tok/fine"])
            # 'pos/ctb' for CTB pos tags
            poses = cast(list[str], doc.get("pos/ctb", [""] * len(toks)))
            # 'ner/msra' or similar gives a list of (entity, type, start, end)
            # or a list of tags. Typically HanLP NER output is list of lists: [['PERSON', start, end], ...]
            # Wait, the exact key might depend on the model. We'll look for common keys.
            ner_key = next((k for k in doc.keys() if k.startswith("ner")), None)
            ner_list = cast(list[list[Any]], doc[ner_key]) if ner_key else []

            # Convert NER ranges to a map of token_index -> label
            # HanLP NER format: [('Entity', 'TYPE', start_tok_idx, end_tok_idx), ...]
            # Note: start is inclusive, end is exclusive.
            ner_map: dict[int, str] = {}
            for ner_item in ner_list:
                if len(ner_item) >= 4:
                    # Depending on HanLP version, format could be (entity_str, label, start, end)
                    label = str(ner_item[1])
                    start_idx = int(ner_item[2])
                    end_idx = int(ner_item[3])
                    for i in range(start_idx, end_idx):
                        ner_map[i] = label

            # Now build the SegmentedTokens
            line_offset = 0
            for i, tok in enumerate(toks):
                # find the exact offset of tok in line[line_offset:]
                idx = line.find(tok, line_offset)
                if idx == -1:
                    # Fallback if mismatch (e.g. normalization)
                    idx = line_offset

                start = current_offset + idx
                end = start + len(tok)

                pos = poses[i] if i < len(poses) else ""
                ner = ner_map.get(i)

                tokens.append(
                    SegmentedToken(
                        text=tok,
                        pos=pos,
                        ner=ner,
                        offset_start=start,
                        offset_end=end,
                    )
                )
                line_offset = idx + len(tok)

        except Exception as exc:
            logger.warning(
                "HanLP failed on line {}; falling back to simple segmentation (line_length={}): {}",
                line_number,
                len(line),
                exc,
            )
            fallback_toks = _fallback_segment(line)
            for ft in fallback_toks:
                ft.offset_start += current_offset
                ft.offset_end += current_offset
                tokens.append(ft)

        current_offset += len(line)

    return tokens
