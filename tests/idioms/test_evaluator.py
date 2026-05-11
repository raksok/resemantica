from __future__ import annotations

import json

from loguru import logger

from resemantica.idioms.evaluator import evaluate_idiom_candidate_batch
from resemantica.idioms.models import IdiomCandidate


class ScriptedEvaluatorLLM:
    def generate_text(self, *, model_name: str, prompt: str) -> str:  # noqa: ARG002
        assert "IDIOM_EVALUATE" in prompt
        return json.dumps(
            [
                {
                    "candidate_id": "ican_eval",
                    "is_idiom": True,
                    "usage_type": "idiomatic",
                    "translation_strategy": "idiomatic",
                    "reason_code": "lexicon_match",
                    "confidence": 0.91,
                    "meaning_zh": "一举两得",
                }
            ],
            ensure_ascii=False,
        )


class InvalidJsonEvaluatorLLM:
    def generate_text(self, *, model_name: str, prompt: str) -> str:  # noqa: ARG002
        return "not json"


class OmittedCandidateEvaluatorLLM:
    def generate_text(self, *, model_name: str, prompt: str) -> str:  # noqa: ARG002
        return json.dumps([])


def _candidate(candidate_id: str = "ican_eval") -> IdiomCandidate:
    return IdiomCandidate(
        candidate_id=candidate_id,
        release_id="rel",
        source_text="一箭双雕",
        normalized_source_text="一箭双雕",
        meaning_zh="",
        preferred_rendering_en="",
        usage_notes=None,
        first_seen_chapter=1,
        last_seen_chapter=1,
        appearance_count=1,
        evidence_snippet="此计一箭双雕。",
        detection_run_id="run",
        candidate_status="discovered",
        validation_status="pending",
        conflict_reason=None,
        analyst_model_name="analyst",
        analyst_prompt_version="1.0",
    )


def test_evaluate_idiom_candidate_batch_parses_schema_json() -> None:
    results = evaluate_idiom_candidate_batch(
        candidates=[_candidate()],
        llm_client=ScriptedEvaluatorLLM(),
        model_name="analyst",
        prompt_template="# version: 1.0\n\n## TASK\nIDIOM_EVALUATE\n\n## CANDIDATES\n{CANDIDATES_JSON}",
        prompt_version="1.0",
        batch_size=10,
    )

    assert len(results) == 1
    result = results[0]
    assert result.candidate_id == "ican_eval"
    assert result.is_idiom is True
    assert result.usage_type == "idiomatic"
    assert result.translation_strategy == "idiomatic"
    assert result.reason_code == "lexicon_match"
    assert result.confidence == 0.91
    assert result.meaning_zh == "一举两得"


def test_evaluate_idiom_candidate_batch_rejects_invalid_json_and_logs_warning() -> None:
    messages: list[str] = []
    sink_id = logger.add(lambda message: messages.append(str(message)), level="WARNING", format="{message}")
    events: list[tuple[str, dict[str, object]]] = []
    try:
        results = evaluate_idiom_candidate_batch(
            candidates=[_candidate()],
            llm_client=InvalidJsonEvaluatorLLM(),
            model_name="analyst",
            prompt_template="# version: 1.0\n\n## TASK\nIDIOM_EVALUATE\n\n## CANDIDATES\n{CANDIDATES_JSON}",
            prompt_version="1.0",
            batch_size=10,
            event_callback=lambda event_name, payload: events.append((event_name, payload)),
        )
    finally:
        logger.remove(sink_id)

    assert len(results) == 1
    assert results[0].candidate_id == "ican_eval"
    assert results[0].is_idiom is False
    assert results[0].reason_code == "eval_error"
    assert events[-1][0] == "eval_batch_error"
    assert events[-1][1]["model_name"] == "analyst"
    assert events[-1][1]["batch_index"] == 1
    assert any("Idiom eval batch 1 failed for model analyst" in message for message in messages)


def test_evaluate_idiom_candidate_batch_logs_omitted_candidates_without_changing_rejection() -> None:
    messages: list[str] = []
    sink_id = logger.add(lambda message: messages.append(str(message)), level="WARNING", format="{message}")
    try:
        results = evaluate_idiom_candidate_batch(
            candidates=[_candidate("ican_missing")],
            llm_client=OmittedCandidateEvaluatorLLM(),
            model_name="analyst",
            prompt_template="# version: 1.0\n\n## TASK\nIDIOM_EVALUATE\n\n## CANDIDATES\n{CANDIDATES_JSON}",
            prompt_version="1.0",
            batch_size=10,
        )
    finally:
        logger.remove(sink_id)

    assert len(results) == 1
    assert results[0].candidate_id == "ican_missing"
    assert results[0].is_idiom is False
    assert results[0].reason_code == "eval_error"
    assert any("omitted 1 of 1 candidates" in message for message in messages)
