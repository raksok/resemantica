import json
from pathlib import Path

from resemantica.glossary.evaluator import evaluate_candidate_batch
from resemantica.glossary.models import GlossaryCandidate
from resemantica.llm.client import LLMClient


class MockLLMResponse:
    def __init__(self, text: str):
        self.text = text


class MockLLMClient(LLMClient):
    def __init__(self, response_text: str):
        self.response_text = response_text
        self.prompts_received = []

    def generate_text(self, prompt: str, model_name: str) -> str:
        self.prompts_received.append(prompt)
        return self.response_text


def _make_candidate(cid: str, term: str) -> GlossaryCandidate:
    return GlossaryCandidate(
        candidate_id=cid,
        release_id="test",
        source_term=term,
        normalized_source_term=term,
        category="character",
        source_language="zh",
        first_seen_chapter=1,
        last_seen_chapter=1,
        appearance_count=1,
        evidence_snippet="",
        discovery_run_id="run",
        candidate_status="discovered",
        candidate_translation_en=None,
        normalized_target_term=None,
        translation_run_id=None,
        validation_status="pending",
        conflict_reason=None,
        schema_version=1,
    )


def test_evaluate_candidate_batch():
    candidates = [
        _make_candidate("c1", "李明"),
        _make_candidate("c2", "宗门"),
    ]

    response_json = [
        {
            "candidate_id": "c1", "keep": True, "term_type": "character",
            "reason_code": "proper_noun", "confidence": 0.9
        },
        {
            "candidate_id": "c2", "keep": False, "term_type": "generic_noun",
            "reason_code": "common_word", "confidence": 0.8
        },
    ]

    mock_llm = MockLLMClient(json.dumps(response_json))

    results = evaluate_candidate_batch(
        candidates=candidates,
        llm_client=mock_llm,
        model_name="test-model",
        prompt_template="{CANDIDATES_JSON}",
        prompt_version="1.0",
        batch_size=50,
    )

    assert len(results) == 2
    assert results[0].candidate_id == "c1"
    assert results[0].keep is True
    assert results[0].term_type == "character"

    assert results[1].candidate_id == "c2"
    assert results[1].keep is False
    assert results[1].term_type == "generic_noun"


def test_evaluate_candidate_batch_caching(tmp_path: Path):
    candidates = [_make_candidate("c1", "李明")]

    response_json = [
        {"candidate_id": "c1", "keep": True, "term_type": "character", "reason_code": "proper_noun", "confidence": 0.9},
    ]

    mock_llm = MockLLMClient(json.dumps(response_json))

    # First call, should call LLM and cache
    results1 = evaluate_candidate_batch(
        candidates=candidates,
        llm_client=mock_llm,
        model_name="test-model",
        prompt_template="{CANDIDATES_JSON}",
        prompt_version="1.0",
        batch_size=50,
        cache_root=tmp_path,
    )

    assert len(mock_llm.prompts_received) == 1
    assert results1[0].keep is True

    # Second call, should use cache
    mock_llm2 = MockLLMClient("invalid json")

    results2 = evaluate_candidate_batch(
        candidates=candidates,
        llm_client=mock_llm2,
        model_name="test-model",
        prompt_template="{CANDIDATES_JSON}",
        prompt_version="1.0",
        batch_size=50,
        cache_root=tmp_path,
    )

    # Should not have called mock_llm2
    assert len(mock_llm2.prompts_received) == 0
    assert results2[0].keep is True


def test_evaluate_candidate_batch_error():
    candidates = [_make_candidate("c1", "李明")]

    mock_llm = MockLLMClient("invalid json response")

    results = evaluate_candidate_batch(
        candidates=candidates,
        llm_client=mock_llm,
        model_name="test-model",
        prompt_template="{CANDIDATES_JSON}",
        prompt_version="1.0",
        batch_size=50,
    )

    assert len(results) == 1
    assert results[0].candidate_id == "c1"
    assert results[0].keep is False
    assert results[0].reason_code == "eval_error"
