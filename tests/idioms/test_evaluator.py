from __future__ import annotations

import json

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


def _candidate() -> IdiomCandidate:
    return IdiomCandidate(
        candidate_id="ican_eval",
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
