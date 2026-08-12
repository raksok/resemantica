from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from loguru import logger

from resemantica.llm.budget import ensure_prompt_within_budget
from resemantica.llm.client import LLMClient
from resemantica.llm.prompts import render_named_sections
from resemantica.settings import AppConfig, load_config


@dataclass(slots=True)
class Pass2BatchResponseError(ValueError):
    reason: str
    affected_block_ids: list[str]
    prompt_token_count: int = 0
    partial_outputs: dict[str, str] | None = None

    def __str__(self) -> str:
        ids = ",".join(self.affected_block_ids)
        return f"pass2_batch_response_invalid: reason={self.reason} block_ids={ids}"


def _system_prompt_for_model(config: AppConfig, model_name: str) -> str:
    for group in config.llm.throttle_groups.values():
        if model_name in group.model_names:
            return group.system_prompt
    return ""


def _prompt_budget_text(prompt: str, *, config: AppConfig, model_name: str) -> str:
    system_prompt = _system_prompt_for_model(config, model_name)
    if not system_prompt:
        return prompt
    return f"{system_prompt}\n{prompt}"


def render_pass2_batch_prompt(
    *,
    prompt_template: str,
    batch_items: list[dict[str, Any]],
) -> str:
    batch_json = json.dumps(
        {"blocks": batch_items},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return render_named_sections(prompt_template, sections={"BATCH_JSON": batch_json})


def ensure_pass2_batch_prompt_within_budget(
    prompt: str,
    *,
    model_name: str,
    config: AppConfig,
    chapter_number: int | None = None,
) -> int:
    return ensure_prompt_within_budget(
        _prompt_budget_text(prompt, config=config, model_name=model_name),
        config=config,
        stage_name="translate.pass2.batch",
        chapter_number=chapter_number,
    )


def parse_pass2_batch_response(
    response: str,
    *,
    expected_block_ids: list[str],
    drafts_by_block_id: dict[str, str],
    prompt_token_count: int = 0,
) -> dict[str, str]:
    try:
        payload = json.loads(response)
    except json.JSONDecodeError as exc:
        raise Pass2BatchResponseError(
            reason="json_parse_failed",
            affected_block_ids=list(expected_block_ids),
            prompt_token_count=prompt_token_count,
        ) from exc

    if not isinstance(payload, dict):
        raise Pass2BatchResponseError(
            reason="root_not_object",
            affected_block_ids=list(expected_block_ids),
            prompt_token_count=prompt_token_count,
        )
    results = payload.get("results")
    if not isinstance(results, list):
        raise Pass2BatchResponseError(
            reason="results_not_list",
            affected_block_ids=list(expected_block_ids),
            prompt_token_count=prompt_token_count,
        )

    expected = set(expected_block_ids)
    seen: set[str] = set()
    outputs: dict[str, str] = {}
    for item in results:
        if not isinstance(item, dict):
            raise Pass2BatchResponseError(
                reason="result_not_object",
                affected_block_ids=list(expected_block_ids),
                prompt_token_count=prompt_token_count,
            )
        raw_block_id = item.get("block_id")
        if not isinstance(raw_block_id, str) or not raw_block_id:
            raise Pass2BatchResponseError(
                reason="invalid_block_id",
                affected_block_ids=list(expected_block_ids),
                prompt_token_count=prompt_token_count,
            )
        block_id = raw_block_id
        if block_id not in expected:
            raise Pass2BatchResponseError(
                reason="unexpected_block_id",
                affected_block_ids=list(expected_block_ids),
                prompt_token_count=prompt_token_count,
            )
        if block_id in seen:
            raise Pass2BatchResponseError(
                reason="duplicate_block_id",
                affected_block_ids=[block_id],
                prompt_token_count=prompt_token_count,
                partial_outputs=outputs,
            )
        seen.add(block_id)

        fidelity_errors_found = item.get("fidelity_errors_found")
        if not isinstance(fidelity_errors_found, bool):
            raise Pass2BatchResponseError(
                reason="invalid_fidelity_errors_found",
                affected_block_ids=[block_id],
                prompt_token_count=prompt_token_count,
                partial_outputs=outputs,
            )
        corrected_text = item.get("corrected_text", "")
        if not isinstance(corrected_text, str):
            raise Pass2BatchResponseError(
                reason="invalid_corrected_text",
                affected_block_ids=[block_id],
                prompt_token_count=prompt_token_count,
                partial_outputs=outputs,
            )
        if fidelity_errors_found and not corrected_text:
            raise Pass2BatchResponseError(
                reason="empty_corrected_text",
                affected_block_ids=[block_id],
                prompt_token_count=prompt_token_count,
                partial_outputs=outputs,
            )
        outputs[block_id] = corrected_text if fidelity_errors_found else drafts_by_block_id[block_id]

    missing = [block_id for block_id in expected_block_ids if block_id not in seen]
    if missing:
        raise Pass2BatchResponseError(
            reason="missing_block_id",
            affected_block_ids=missing,
            prompt_token_count=prompt_token_count,
            partial_outputs=outputs,
        )
    return outputs


def translate_pass2_batch(
    *,
    client: LLMClient,
    model_name: str,
    prompt_template: str,
    batch_items: list[dict[str, Any]],
    config: AppConfig | None = None,
    chapter_number: int | None = None,
) -> tuple[dict[str, str], int]:
    config_obj = config or load_config()
    prompt = render_pass2_batch_prompt(
        prompt_template=prompt_template,
        batch_items=batch_items,
    )
    prompt_token_count = ensure_pass2_batch_prompt_within_budget(
        prompt,
        model_name=model_name,
        config=config_obj,
        chapter_number=chapter_number,
    )
    response = client.generate_text(model_name=model_name, prompt=prompt)
    block_ids = [str(item["block_id"]) for item in batch_items]
    return (
        parse_pass2_batch_response(
            response,
            expected_block_ids=block_ids,
            drafts_by_block_id={str(item["block_id"]): str(item["draft_text"]) for item in batch_items},
            prompt_token_count=prompt_token_count,
        ),
        prompt_token_count,
    )


def translate_pass2(
    *,
    client: LLMClient,
    model_name: str,
    prompt_template: str,
    source_text: str,
    draft_text: str,
    full_source_block: str,
    prior_segment_translations: list[str] | None = None,
    glossary: str = "",
    alias_resolutions: str = "",
    matched_idioms: str = "",
    local_relationships: str = "",
    continuity_notes: str = "",
    retrieval_evidence: str = "",
    validation_feedback: list[str] | None = None,
    chapter_number: int | None = None,
    block_id: str | None = None,
    segment_id: str | None = None,
    fallback_callback: Callable[[dict[str, Any]], None] | None = None,
    config: AppConfig | None = None,
) -> str:
    prior_segments = "\n".join(prior_segment_translations or [])
    prompt = render_named_sections(
        prompt_template,
        sections={
            "GLOSSARY": glossary,
            "SOURCE_TEXT": source_text,
            "DRAFT_TEXT": draft_text,
            "FULL_SOURCE_BLOCK": full_source_block,
            "PRIOR_SEGMENTS": prior_segments,
            "ALIAS_RESOLUTIONS": alias_resolutions,
            "MATCHED_IDIOMS": matched_idioms,
            "LOCAL_RELATIONSHIPS": local_relationships,
            "CONTINUITY_NOTES": continuity_notes,
            "RETRIEVAL_EVIDENCE": retrieval_evidence,
        },
    )
    if validation_feedback:
        feedback = "\n".join(f"- {error}" for error in validation_feedback)
        prompt = (
            f"{prompt}\n\n## VALIDATION_FEEDBACK\n"
            "The previous candidate failed deterministic validation. "
            "Correct every issue below in this attempt:\n"
            f"{feedback}"
        )
    ensure_prompt_within_budget(
        prompt,
        config=config or load_config(),
        stage_name="translate.pass2",
        chapter_number=chapter_number,
    )
    response = client.generate_text(model_name=model_name, prompt=prompt)

    try:
        result: dict[str, Any] = json.loads(response)
    except json.JSONDecodeError:
        payload = {
            "reason": "json_parse_failed",
            "model_name": model_name,
            "chapter_number": chapter_number,
            "block_id": block_id,
            "segment_id": segment_id,
        }
        if fallback_callback is not None:
            fallback_callback(payload)
        else:
            logger.warning(
                "Pass 2 JSON parse failed; falling back to original draft "
                "(model={}, chapter={}, block={}, segment={})",
                model_name,
                chapter_number,
                block_id,
                segment_id,
            )
        return draft_text

    fidelity_errors_found = result.get("fidelity_errors_found", False)
    if not fidelity_errors_found:
        return draft_text

    corrected_text = result.get("corrected_text", "")
    if not corrected_text:
        payload = {
            "reason": "empty_corrected_text",
            "model_name": model_name,
            "chapter_number": chapter_number,
            "block_id": block_id,
            "segment_id": segment_id,
        }
        if fallback_callback is not None:
            fallback_callback(payload)
        else:
            logger.warning(
                "Pass 2 fidelity errors found but corrected_text is empty; falling back to original draft "
                "(model={}, chapter={}, block={}, segment={})",
                model_name,
                chapter_number,
                block_id,
                segment_id,
            )
        return draft_text

    return str(corrected_text)
