
import numpy as np

from resemantica.glossary.critic import deduplicate_and_cluster
from resemantica.glossary.models import GlossaryCandidate, LockedGlossaryEntry


class MockSentenceTransformer:
    def __init__(self, model_name: str):
        self.model_name = model_name

    def encode(self, texts: list[str] | str, normalize_embeddings: bool = False):
        if isinstance(texts, str):
            texts = [texts]
        # Just return dummy embeddings based on string hash to make it somewhat deterministic
        # For our test, we'll return hardcoded embeddings if texts match known patterns
        embeddings = []
        for t in texts:
            # We use a simple 3D embedding space for our tests
            # [1, 0, 0] = "李明"
            # [0, 1, 0] = "宗门"
            if "李明" in t:
                embeddings.append([1.0, 0.0, 0.0])
            elif "宗门" in t:
                embeddings.append([0.0, 1.0, 0.0])
            else:
                embeddings.append([0.0, 0.0, 1.0])
        return np.array(embeddings)


def _make_candidate(cid: str, term: str, score: float, status: str = "discovered") -> GlossaryCandidate:
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
        candidate_translation_en=None,
        normalized_target_term=None,
        translation_run_id=None,
        candidate_status=status,
        validation_status="pending",
        conflict_reason=None,
        corpus_score=score,
        schema_version=1,
    )


def test_deduplicate_and_cluster(monkeypatch):
    import resemantica.glossary.critic as critic

    # Mock _get_model to return MockSentenceTransformer
    def mock_get_model(model_name: str):
        return MockSentenceTransformer(model_name)

    monkeypatch.setattr(critic, "_get_model", mock_get_model)

    # "李明" -> [1, 0, 0]
    # "老李明" -> [1, 0, 0]
    c1 = _make_candidate("c1", "李明", 0.9)
    c2 = _make_candidate("c2", "老李明", 0.5)

    # "宗门" -> [0, 1, 0]
    c3 = _make_candidate("c3", "宗门", 0.8)

    candidates = [c1, c2, c3]

    processed_candidates, clusters = deduplicate_and_cluster(
        candidates,
        model_name="test-model",
        similarity_threshold=0.85
    )

    # We should have 1 cluster (the multi-item one)
    assert len(clusters) == 1

    c_liming = next(c for c in clusters if c.canonical_id == "c1")
    assert c_liming.canonical_term == "李明"
    assert "老李明" in c_liming.aliases
    assert "c2" in c_liming.member_ids
    assert c_liming.similarity_score == 1.0

    # Check that c2 was marked as alias_merged
    assert c2.candidate_status == "alias_merged"
    assert "merged_into:c1" in c2.conflict_reason

    # c3 is its own cluster, so it's not in clusters, but its status should be unchanged
    assert c3.candidate_status == "discovered"


def test_deduplicate_against_existing(monkeypatch):
    import resemantica.glossary.critic as critic

    def mock_get_model(model_name: str):
        return MockSentenceTransformer(model_name)

    monkeypatch.setattr(critic, "_get_model", mock_get_model)

    c1 = _make_candidate("c1", "李明", 0.9)

    locked_entry = LockedGlossaryEntry(
        glossary_entry_id="lex_liming",
        release_id="test",
        source_term="李明",
        normalized_source_term="李明",
        target_term="Li Ming",
        normalized_target_term="li ming",
        category="character",
        status="approved",
        approved_at="2024",
        approval_run_id="run",
        source_candidate_id="c_old",
        schema_version=1,
    )

    processed, clusters = deduplicate_and_cluster(
        [c1],
        model_name="test",
        existing_entries=[locked_entry],
        similarity_threshold=0.85
    )

    assert len(clusters) == 0
    assert c1.candidate_status == "pruned"
    assert "already_exists:lex_liming" in c1.conflict_reason
