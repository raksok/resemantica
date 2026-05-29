import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Callable

from loguru import logger

from resemantica.glossary.models import GlossaryCandidate
from resemantica.llm.client import LLMClient
from resemantica.settings import AppConfig


@dataclass(slots=True)
class EvalResult:
    candidate_id: str
    keep: bool
    term_type: str
    reason_code: str
    confidence: float


def _hash_batch(candidates: list[GlossaryCandidate], prompt_version: str) -> str:
    content = prompt_version + ":" + ",".join(sorted(c.candidate_id for c in candidates))
    return sha256(content.encode("utf-8")).hexdigest()[:16]


def evaluate_candidate_batch(
    *,
    candidates: list[GlossaryCandidate],
    llm_client: LLMClient,
    model_name: str,
    prompt_template: str,
    prompt_version: str,
    batch_size: int = 50,
    config: AppConfig | None = None,
    cache_root: Path | None = None,
    event_callback: Callable | None = None,
    persist_callback: Callable[[list[EvalResult]], None] | None = None,
) -> list[EvalResult]:
    """
    Batch candidates for LLM keep/reject evaluation.

    Per batch:
    1. Format candidates as JSON array with: surface, context_snippets,
       frequency, chapter_coverage, type_prior
    2. Render prompt template with candidate JSON
    3. Call LLM, parse schema-constrained JSON response
    4. Cache by batch content hash (not chapter hash)

    Error handling: per-batch try/except, skip failed batches.
    """
    results: list[EvalResult] = []
    total_batches = (len(candidates) + batch_size - 1) // batch_size if batch_size > 0 else 0

    for i in range(0, len(candidates), batch_size):
        batch = candidates[i:i + batch_size]
        batch_index = i // batch_size + 1
        batch_hash = _hash_batch(batch, prompt_version)

        cache_file = None
        if cache_root:
            cache_file = cache_root / f"eval_batch_{batch_hash}.json"
            if cache_file.exists():
                try:
                    with open(cache_file, "r", encoding="utf-8") as f:
                        cached_data = json.load(f)

                    batch_results = []
                    for item in cached_data:
                        batch_results.append(EvalResult(**item))
                    results.extend(batch_results)
                    if persist_callback:
                        persist_callback(batch_results)
                    if event_callback:
                        event_callback("eval_batch_cached", {
                            "batch_index": batch_index,
                            "total_batches": total_batches,
                            "batch_size": len(batch),
                            "candidate_count": len(batch),
                            "message": f"Eval batch {batch_index}: {len(batch)} candidates (cached)",
                        })
                    logger.debug(
                        "Eval batch {}: {} candidates loaded from cache",
                        batch_index,
                        len(batch),
                    )
                    continue
                except Exception:
                    pass

        # Prepare JSON payload
        candidates_json = []
        for c in batch:
            snippets = []
            if c.context_snippets:
                try:
                    snippets = json.loads(c.context_snippets)
                except Exception:
                    pass
            candidates_json.append({
                "candidate_id": c.candidate_id,
                "surface_form": c.source_term,
                "type_prior": c.type_prior or "unknown",
                "frequency": c.appearance_count,
                "chapter_coverage": c.chapter_coverage or 1,
                "context_snippets": snippets
            })

        prompt = prompt_template.replace("{CANDIDATES_JSON}", json.dumps(candidates_json, ensure_ascii=False, indent=2))

        if event_callback:
            event_callback("eval_batch_start", {
                "batch_index": batch_index,
                "total_batches": total_batches,
                "batch_size": len(batch),
                "candidate_count": len(batch),
                "message": f"Evaluating batch {batch_index}: {len(batch)} candidates",
            })
        logger.info(
            "Eval batch {}: sending {} candidates to LLM",
            batch_index,
            len(batch),
        )

        try:
            resp_text = llm_client.generate_text(prompt=prompt, model_name=model_name)
            resp_text = resp_text.strip()
            # Simple heuristic to extract JSON array
            if resp_text.startswith("```json"):
                resp_text = resp_text[7:]
            if resp_text.startswith("```"):
                resp_text = resp_text[3:]
            if resp_text.endswith("```"):
                resp_text = resp_text[:-3]
            resp_text = resp_text.strip()

            parsed = json.loads(resp_text)
            if not isinstance(parsed, list):
                raise ValueError("Expected JSON array")

            batch_results = []
            for item in parsed:
                # Basic validation
                if "candidate_id" not in item:
                    continue
                batch_results.append(
                    EvalResult(
                        candidate_id=item["candidate_id"],
                        keep=bool(item.get("keep", False)),
                        term_type=item.get("term_type", "unknown"),
                        reason_code=item.get("reason_code", "ambiguous"),
                        confidence=float(item.get("confidence", 0.0)),
                    )
                )

            results.extend(batch_results)

            if persist_callback:
                persist_callback(batch_results)

            if cache_file:
                cache_file.parent.mkdir(parents=True, exist_ok=True)
                with open(cache_file, "w", encoding="utf-8") as f:
                    import dataclasses
                    json.dump([dataclasses.asdict(r) for r in batch_results], f, ensure_ascii=False, indent=2)

            if event_callback:
                event_callback("eval_batch_success", {
                    "batch_index": batch_index,
                    "total_batches": total_batches,
                    "batch_size": len(batch),
                    "candidate_count": len(batch),
                    "result_count": len(batch_results),
                    "message": f"Eval batch {batch_index}: {len(batch_results)} results",
                })
            logger.debug(
                "Eval batch {}: {} results (kept={}, rejected={})",
                batch_index,
                len(batch_results),
                sum(1 for r in batch_results if r.keep),
                sum(1 for r in batch_results if not r.keep),
            )

        except Exception as e:
            if event_callback:
                event_callback("eval_batch_error", {
                    "batch_index": batch_index,
                    "total_batches": total_batches,
                    "error": str(e),
                    "batch_size": len(batch),
                    "candidate_count": len(batch),
                    "message": f"Eval batch {batch_index} failed: {e}",
                })
            logger.warning(
                "Eval batch {} failed ({}), defaulting {} candidates to rejected",
                batch_index,
                e,
                len(batch),
            )
            # Default to reject if LLM fails
            batch_results = []
            for c in batch:
                batch_results.append(
                    EvalResult(
                        candidate_id=c.candidate_id,
                        keep=False,
                        term_type="unknown",
                        reason_code="eval_error",
                        confidence=0.0
                    )
                )
            results.extend(batch_results)
            if persist_callback:
                persist_callback(batch_results)

    return results
