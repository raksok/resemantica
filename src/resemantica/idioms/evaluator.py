from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from loguru import logger

from resemantica.idioms.models import IdiomCandidate
from resemantica.llm.client import LLMClient


@dataclass(slots=True)
class IdiomEvalResult:
    candidate_id: str
    is_idiom: bool
    usage_type: str
    translation_strategy: str
    reason_code: str
    confidence: float
    meaning_zh: str


def _strip_json_fence(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def evaluate_idiom_candidate_batch(
    *,
    candidates: list[IdiomCandidate],
    llm_client: LLMClient,
    model_name: str,
    prompt_template: str,
    prompt_version: str,  # noqa: ARG001
    batch_size: int = 50,
    cache_root: Path | None = None,  # noqa: ARG001
    event_callback: Callable[[str, dict[str, object]], None] | None = None,
) -> list[IdiomEvalResult]:
    results: list[IdiomEvalResult] = []
    for index in range(0, len(candidates), batch_size):
        batch = candidates[index:index + batch_size]
        batch_index = index // batch_size + 1
        payload = [
            {
                "candidate_id": candidate.candidate_id,
                "surface_form": candidate.source_text,
                "frequency": candidate.appearance_count,
                "chapter_coverage": candidate.chapter_coverage or 1,
                "dictionary_match": bool(candidate.dictionary_match),
                "context_snippets": (
                    json.loads(candidate.context_snippets)
                    if candidate.context_snippets
                    else [candidate.evidence_snippet]
                ),
                "literal_meaning_zh": candidate.literal_meaning_zh or "",
                "idiomatic_meaning_zh": candidate.idiomatic_meaning_zh or "",
            }
            for candidate in batch
        ]
        prompt = prompt_template.replace(
            "{CANDIDATES_JSON}",
            json.dumps(payload, ensure_ascii=False, indent=2),
        )
        if event_callback is not None:
            event_callback(
                "eval_batch_start",
                {
                    "batch_index": batch_index,
                    "batch_size": len(batch),
                    "model_name": model_name,
                    "message": f"Evaluating idiom batch {batch_index}: {len(batch)} candidates",
                },
            )
        try:
            parsed = json.loads(_strip_json_fence(llm_client.generate_text(model_name=model_name, prompt=prompt)))
            if isinstance(parsed, dict):
                parsed = parsed.get("idioms", [])
            if not isinstance(parsed, list):
                raise ValueError("idiom evaluator output must be a JSON array")
            parsed_by_id = {
                str(item.get("candidate_id")): item
                for item in parsed
                if isinstance(item, dict) and item.get("candidate_id")
            }
            missing_count = sum(1 for candidate in batch if candidate.candidate_id not in parsed_by_id)
            if missing_count:
                logger.warning(
                    "Idiom eval batch {} omitted {} of {} candidates (model={})",
                    batch_index,
                    missing_count,
                    len(batch),
                    model_name,
                )
            for candidate in batch:
                item = parsed_by_id.get(candidate.candidate_id)
                if item is None:
                    results.append(_rejected(candidate.candidate_id, "eval_error"))
                    continue
                results.append(
                    IdiomEvalResult(
                        candidate_id=candidate.candidate_id,
                        is_idiom=bool(item.get("is_idiom", False)),
                        usage_type=str(item.get("usage_type", "unknown")),
                        translation_strategy=str(item.get("translation_strategy", "idiomatic")),
                        reason_code=str(item.get("reason_code", "ambiguous")),
                        confidence=float(item.get("confidence", 0.0)),
                        meaning_zh=str(item.get("meaning_zh", "")).strip(),
                    )
                )
            if event_callback is not None:
                event_callback(
                    "eval_batch_success",
                    {
                        "batch_index": batch_index,
                        "batch_size": len(batch),
                        "model_name": model_name,
                        "message": f"Idiom eval batch {batch_index} completed: {len(batch)} candidates",
                    },
                )
        except Exception as exc:
            if event_callback is not None:
                event_callback(
                    "eval_batch_error",
                    {
                        "batch_index": batch_index,
                        "batch_size": len(batch),
                        "model_name": model_name,
                        "error": str(exc),
                        "message": f"Idiom eval batch {batch_index} failed: {exc}",
                    },
                )
            logger.opt(exception=True).warning(
                "Idiom eval batch {} failed for model {} (batch_size={}): {}",
                batch_index,
                model_name,
                len(batch),
                exc,
            )
            results.extend(_rejected(candidate.candidate_id, "eval_error") for candidate in batch)
    return results


def _rejected(candidate_id: str, reason_code: str) -> IdiomEvalResult:
    return IdiomEvalResult(
        candidate_id=candidate_id,
        is_idiom=False,
        usage_type="unknown",
        translation_strategy="idiomatic",
        reason_code=reason_code,
        confidence=0.0,
        meaning_zh="",
    )
