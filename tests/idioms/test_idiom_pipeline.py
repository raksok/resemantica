from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from loguru import logger

from resemantica.db.idiom_repo import (
    ensure_idiom_schema,
    get_checkpoint,
    list_candidates,
    list_candidates_for_promotion,
    list_candidates_for_translation,
    list_conflicts,
    list_policies,
    list_translation_votes,
    promote_policies,
    save_idiom_translation,
    set_checkpoint,
    upsert_discovered_candidates,
)
from resemantica.db.sqlite import open_connection
from resemantica.idioms.extractor import extract_idioms
from resemantica.idioms.matching import match_idioms
from resemantica.idioms.models import IdiomCandidate, IdiomPolicy
from resemantica.idioms.pipeline import (
    preprocess_idioms,
    promote_idiom_candidates,
    resolve_idiom_policy,
    review_idiom_candidates,
    translate_idiom_candidates,
)
from resemantica.idioms.validators import normalize_idiom_source
from resemantica.llm.prompts import load_prompt
from resemantica.settings import AppConfig, derive_paths, load_config


class ScriptedIdiomLLM:
    def __init__(self, *, keep_all: bool = True) -> None:
        self.keep_all = keep_all

    def generate_text(self, *, model_name: str, prompt: str) -> str:  # noqa: ARG002
        if "IDIOM_DETECT" in prompt:
            raise AssertionError("raw-chapter LLM idiom discovery should not run")
        if "IDIOM_EVALUATE" in prompt:
            match = re.search(r"## CANDIDATES\s+(.+?)(?:\n\n## |\Z)", prompt, flags=re.DOTALL)
            if match is None:
                raise RuntimeError("candidate JSON missing from idiom evaluator prompt")
            rows = json.loads(match.group(1))
            return json.dumps(
                [
                    {
                        "candidate_id": row["candidate_id"],
                        "is_idiom": self.keep_all,
                        "usage_type": "idiomatic",
                        "translation_strategy": "idiomatic",
                        "reason_code": "lexicon_match",
                        "confidence": 0.95,
                        "meaning_zh": "一举两得",
                    }
                    for row in rows
                ],
                ensure_ascii=False,
            )
        raise RuntimeError("Unexpected prompt type")


class ScriptedTranslatorLLM:
    def __init__(self, response: str) -> None:
        self.response = response

    def generate_text(self, *, model_name: str, prompt: str) -> str:  # noqa: ARG002
        return self.response


class ModelMappedIdiomTranslator:
    def __init__(self, outputs: dict[tuple[str, str], str]) -> None:
        self.outputs = outputs
        self.calls: list[tuple[str, str]] = []

    def generate_text(self, *, model_name: str, prompt: str) -> str:
        kind = "meaning" if "Translate the following term" in prompt else "rendering"
        self.calls.append((model_name, kind))
        return self.outputs[(model_name, kind)]


def _write_extracted_chapter(
    *,
    release_id: str,
    chapter_number: int,
    source_text: str,
) -> None:
    config = load_config()
    paths = derive_paths(config, release_id=release_id)
    paths.extracted_chapters_dir.mkdir(parents=True, exist_ok=True)
    block_id = f"ch{chapter_number:03d}_blk001"
    payload = {
        "chapter_id": f"chapter-{chapter_number}",
        "chapter_number": chapter_number,
        "source_document_path": f"OEBPS/chapter{chapter_number}.xhtml",
        "chapter_source_hash": f"hash-ch{chapter_number}",
        "schema_version": 1,
        "records": [
            {
                "chapter_id": f"chapter-{chapter_number}",
                "chapter_number": chapter_number,
                "source_document_path": f"OEBPS/chapter{chapter_number}.xhtml",
                "block_id": block_id,
                "parent_block_id": block_id,
                "segment_id": None,
                "block_order": 1,
                "segment_order": None,
                "source_text_zh": source_text,
                "placeholder_map_ref": "",
                "chapter_source_hash": f"hash-ch{chapter_number}",
                "schema_version": 1,
            }
        ],
    }
    chapter_path = paths.extracted_chapters_dir / f"chapter-{chapter_number}.json"
    chapter_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _insert_policy(
    *,
    release_id: str,
    source_text: str,
    meaning_zh: str,
    preferred_rendering_en: str,
) -> None:
    config = load_config()
    paths = derive_paths(config, release_id=release_id)
    conn = open_connection(paths.db_path)
    ensure_idiom_schema(conn)
    try:
        promote_policies(
            conn,
            policies=[
                IdiomPolicy(
                    idiom_id="idi_test_existing",
                    release_id=release_id,
                    source_text=source_text,
                    normalized_source_text=normalize_idiom_source(source_text),
                    meaning_zh=meaning_zh,
                    preferred_rendering_en=preferred_rendering_en,
                    usage_notes=None,
                    policy_status="approved",
                    first_seen_chapter=1,
                    last_seen_chapter=1,
                    appearance_count=1,
                    promoted_from_candidate_id="ican_existing",
                    approval_run_id=f"seed-{datetime.now(UTC).isoformat()}",
                    schema_version=1,
                )
            ],
        )
    finally:
        conn.close()


def _insert_idiom_candidate(
    *,
    release_id: str,
    source_text: str = "一箭双雕",
    meaning_zh: str = "一举两得",
    candidate_id: str = "ican_m42",
) -> str:
    config = load_config()
    paths = derive_paths(config, release_id=release_id)
    conn = open_connection(paths.db_path)
    ensure_idiom_schema(conn)
    try:
        upsert_discovered_candidates(
            conn,
            candidates=[
                IdiomCandidate(
                    candidate_id=candidate_id,
                    release_id=release_id,
                    source_text=source_text,
                    normalized_source_text=normalize_idiom_source(source_text),
                    meaning_zh=meaning_zh,
                    meaning_en="",
                    preferred_rendering_en="",
                    usage_notes=None,
                    first_seen_chapter=1,
                    last_seen_chapter=1,
                    appearance_count=1,
                    evidence_snippet=source_text,
                    detection_run_id="seed",
                    candidate_status="discovered",
                    validation_status="pending",
                    conflict_reason=None,
                    analyst_model_name="analyst",
                    analyst_prompt_version="1.0",
                )
            ],
        )
    finally:
        conn.close()
    return candidate_id


def test_detected_idiom_candidate_starts_without_english_rendering(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m18d-detect"
    _write_extracted_chapter(
        release_id=release_id,
        chapter_number=1,
        source_text="他可谓一箭双雕。",
    )
    config = load_config()
    paths = derive_paths(config, release_id=release_id)
    prompt = load_prompt("idiom_detect.txt")
    llm = ScriptedIdiomLLM()

    candidates = extract_idioms(
        release_id=release_id,
        extracted_chapters_dir=paths.extracted_chapters_dir,
        detection_run_id="idioms-001",
        llm_client=llm,
        model_name=config.models.analyst_name,
        prompt_template=prompt.template,
        prompt_version=prompt.version,
        skip_llm_eval=True,
    )

    assert len(candidates) == 1
    assert candidates[0].preferred_rendering_en == ""
    assert candidates[0].candidate_status == "discovered"


def test_multi_model_idiom_translation_resolves_rendering_and_stores_votes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m42-idiom-votes"
    candidate_id = _insert_idiom_candidate(release_id=release_id)
    translator = ModelMappedIdiomTranslator(
        {
            ("model-a", "rendering"): "kill two birds with one stone",
            ("model-b", "rendering"): "kill two birds with one stone",
            ("model-c", "rendering"): "one arrow, two eagles",
            ("model-a", "meaning"): "achieve two things at once",
            ("model-b", "meaning"): "achieve two things at once",
            ("model-c", "meaning"): "gain two benefits with one action",
        }
    )
    config = AppConfig()
    config.models.preprocess_translator_names = ["model-a", "model-b", "model-c"]
    rendering_prompt = load_prompt("idiom_translate.txt")
    meaning_prompt = load_prompt("idiom_meaning.txt")
    paths = derive_paths(load_config(), release_id=release_id)
    conn = open_connection(paths.db_path)
    ensure_idiom_schema(conn)
    events: list[tuple[str, dict[str, object]]] = []
    try:
        translated = translate_idiom_candidates(
            conn=conn,
            release_id=release_id,
            run_id="idioms-001",
            translator_client=translator,
            translator_model_names=config.models.effective_preprocess_translator_names(),
            rendering_prompt_template=rendering_prompt.template,
            rendering_prompt_version=rendering_prompt.version,
            meaning_prompt_template=meaning_prompt.template,
            meaning_prompt_version=meaning_prompt.version,
            event_callback=lambda event_name, payload: events.append((event_name, payload)),
        )

        assert translated == 1
        saved = list_candidates(conn, release_id=release_id)[0]
        assert saved.candidate_id == candidate_id
        assert saved.preferred_rendering_en == "kill two birds with one stone"
        assert saved.meaning_en == "achieve two things at once"
        assert saved.candidate_status == "translated"
        assert translator.calls == [
            ("model-a", "rendering"),
            ("model-a", "meaning"),
            ("model-b", "rendering"),
            ("model-b", "meaning"),
            ("model-c", "rendering"),
            ("model-c", "meaning"),
        ]
        votes = list_translation_votes(conn, release_id=release_id)
        assert len(votes) == 6
        assert {vote.vote_kind for vote in votes} == {"rendering", "meaning"}
        event_names = [event_name for event_name, _ in events]
        assert event_names[0] == "translate.started"
        assert event_names.count("translate.model_started") == 3
        assert event_names.count("translate.model_completed") == 3
        assert event_names[-1] == "translate.completed"
        assert events[-1][1]["translated_count"] == 1
        assert events[-1][1]["unresolved_count"] == 0
    finally:
        conn.close()


def test_unresolved_idiom_translation_warns_and_preserves_unresolved_behavior(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m42-idiom-unresolved"
    candidate_id = _insert_idiom_candidate(release_id=release_id)
    translator = ModelMappedIdiomTranslator(
        {
            ("model-a", "rendering"): "kill two birds with one stone",
            ("model-b", "rendering"): "one arrow, two eagles",
            ("model-a", "meaning"): "achieve two things at once",
            ("model-b", "meaning"): "achieve two things at once",
        }
    )
    rendering_prompt = load_prompt("idiom_translate.txt")
    meaning_prompt = load_prompt("idiom_meaning.txt")
    paths = derive_paths(load_config(), release_id=release_id)
    conn = open_connection(paths.db_path)
    ensure_idiom_schema(conn)
    events: list[tuple[str, dict[str, object]]] = []
    messages: list[str] = []
    sink_id = logger.add(lambda message: messages.append(str(message)), level="WARNING", format="{message}")
    try:
        translated = translate_idiom_candidates(
            conn=conn,
            release_id=release_id,
            run_id="idioms-001",
            translator_client=translator,
            translator_model_names=["model-a", "model-b"],
            rendering_prompt_template=rendering_prompt.template,
            rendering_prompt_version=rendering_prompt.version,
            meaning_prompt_template=meaning_prompt.template,
            meaning_prompt_version=meaning_prompt.version,
            event_callback=lambda event_name, payload: events.append((event_name, payload)),
        )

        assert translated == 0
        saved = list_candidates(conn, release_id=release_id)[0]
        assert saved.candidate_id == candidate_id
        assert saved.preferred_rendering_en == ""
        assert saved.candidate_status == "discovered"
        votes = list_translation_votes(conn, release_id=release_id)
        rendering_votes = [vote for vote in votes if vote.vote_kind == "rendering"]
        meaning_votes = [vote for vote in votes if vote.vote_kind == "meaning"]
        assert {vote.resolution_status for vote in rendering_votes} == {"unresolved"}
        assert {vote.resolution_status for vote in meaning_votes} == {"consensus"}
        warning_events = [payload for event_name, payload in events if event_name == "translate.unresolved"]
        assert warning_events
        assert warning_events[0]["severity"] == "warning"
        assert warning_events[0]["candidate_id"] == candidate_id
        assert events[-1][0] == "translate.completed"
        assert events[-1][1]["translated_count"] == 0
        assert events[-1][1]["unresolved_count"] == 1
        assert any("rendering vote prevented saving" in message for message in messages)
    finally:
        logger.remove(sink_id)
        conn.close()


def test_idiom_review_csv_written_and_matches_json(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m46-idiom-csv"
    _insert_idiom_candidate(release_id=release_id)
    translator = ModelMappedIdiomTranslator(
        {
            ("model-a", "rendering"): "kill two birds with one stone",
            ("model-b", "rendering"): "kill two birds with one stone",
            ("model-c", "rendering"): "one arrow, two eagles",
            ("model-a", "meaning"): "achieve two things at once",
            ("model-b", "meaning"): "achieve two things at once",
            ("model-c", "meaning"): "gain two benefits with one action",
        }
    )
    config = AppConfig()
    config.models.preprocess_translator_names = ["model-a", "model-b", "model-c"]
    rendering_prompt = load_prompt("idiom_translate.txt")
    meaning_prompt = load_prompt("idiom_meaning.txt")
    paths = derive_paths(load_config(), release_id=release_id)
    conn = open_connection(paths.db_path)
    ensure_idiom_schema(conn)
    try:
        translate_idiom_candidates(
            conn=conn,
            release_id=release_id,
            run_id="idioms-001",
            translator_client=translator,
            translator_model_names=config.models.effective_preprocess_translator_names(),
            rendering_prompt_template=rendering_prompt.template,
            rendering_prompt_version=rendering_prompt.version,
            meaning_prompt_template=meaning_prompt.template,
            meaning_prompt_version=meaning_prompt.version,
        )
    finally:
        conn.close()

    review = review_idiom_candidates(release_id=release_id, run_id="review-001")
    assert review["entries_written"] == 1

    csv_path = paths.idiom_review_path.with_suffix(".csv")
    assert csv_path.exists(), f"CSV review file not found: {csv_path}"

    import csv
    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f, delimiter="\t"))
    assert rows[0] == [
        "action",
        "source_text",
        "meaning_zh",
        "meaning_en",
        "rendering",
        "candidate_id",
        "evidence_snippet",
        "alternatives",
    ]
    assert rows[1][0] == "keep"
    assert rows[1][1] == "一箭双雕"
    assert rows[1][3] == "achieve two things at once"
    assert rows[1][4] == "kill two birds with one stone"
    assert "rendering:kill two birds with one stone" in rows[1][7]

    json_data = json.loads(paths.idiom_review_path.read_text(encoding="utf-8"))
    assert {row[1] for row in rows[1:]} == {entry["source_text"] for entry in json_data["entries"]}


def test_promote_idiom_with_csv_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m46-idiom-csv-promote"
    first_id = _insert_idiom_candidate(release_id=release_id)
    second_id = _insert_idiom_candidate(
        release_id=release_id,
        source_text="杯弓蛇影",
        meaning_zh="疑神疑鬼",
        candidate_id="ican_second",
    )
    paths = derive_paths(load_config(), release_id=release_id)
    conn = open_connection(paths.db_path)
    ensure_idiom_schema(conn)
    try:
        save_idiom_translation(
            conn,
            candidate_id=first_id,
            translation_run_id="translate-001",
            target_term="kill two birds with one stone",
            meaning_en="achieve two things at once",
            translator_model_name="model-a",
            translator_prompt_version="1.0",
        )
        save_idiom_translation(
            conn,
            candidate_id=second_id,
            translation_run_id="translate-001",
            target_term="seeing snakes in shadows",
            meaning_en="being paranoid",
            translator_model_name="model-a",
            translator_prompt_version="1.0",
        )
    finally:
        conn.close()

    paths.idioms_dir.mkdir(parents=True, exist_ok=True)
    csv_path = paths.idiom_review_path.with_suffix(".csv")
    csv_content = (
        "action\tsource_text\tmeaning_zh\tmeaning_en\trendering\tcandidate_id\tevidence_snippet\talternatives\n"
        f"keep\t一箭双雕\t一举两得\twin twice with one move\tone arrow, two wins\t{first_id}\t\t\n"
        f"delete\t杯弓蛇影\t疑神疑鬼\t\t\t{second_id}\t\t\n"
    )
    csv_path.write_text(csv_content, encoding="utf-8")

    result = promote_idiom_candidates(
        release_id=release_id,
        run_id="promote-001",
        review_file_path=csv_path,
    )
    assert result["status"] == "success"

    conn = open_connection(paths.db_path)
    ensure_idiom_schema(conn)
    try:
        policies = list_policies(conn, release_id=release_id)
        by_source = {policy.source_text: policy for policy in policies}
        assert by_source["一箭双雕"].preferred_rendering_en == "one arrow, two wins"
        assert by_source["一箭双雕"].meaning_en == "win twice with one move"
        assert "杯弓蛇影" not in by_source
    finally:
        conn.close()


def test_promote_idiom_with_csv_add_entry(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m46-idiom-csv-add"
    paths = derive_paths(load_config(), release_id=release_id)
    paths.idioms_dir.mkdir(parents=True, exist_ok=True)
    csv_path = paths.idiom_review_path.with_suffix(".csv")
    csv_content = (
        "action\tsource_text\tmeaning_zh\tmeaning_en\trendering\tcandidate_id\tevidence_snippet\talternatives\n"
        "add\t新成语\t新的含义\tnew meaning\tnew rendering\t\t源自新章节的文本\t\n"
    )
    csv_path.write_text(csv_content, encoding="utf-8")

    result = promote_idiom_candidates(
        release_id=release_id,
        run_id="promote-001",
        review_file_path=csv_path,
    )
    assert result["status"] == "success"

    conn = open_connection(paths.db_path)
    ensure_idiom_schema(conn)
    try:
        policies = list_policies(conn, release_id=release_id)
        assert {policy.source_text: policy.preferred_rendering_en for policy in policies} == {
            "新成语": "new rendering",
        }
    finally:
        conn.close()


def test_promote_idiom_csv_bad_header_raises(tmp_path: Path) -> None:
    csv_path = tmp_path / "bad.csv"
    csv_path.write_text("col1\tcol2\tcol3\n", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid header"):
        from resemantica.idioms.pipeline import _read_idiom_review_data
        _read_idiom_review_data(csv_path)


def test_promote_idiom_csv_empty_is_noop(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m46-idiom-csv-empty"
    paths = derive_paths(load_config(), release_id=release_id)
    paths.idioms_dir.mkdir(parents=True, exist_ok=True)
    csv_path = paths.idiom_review_path.with_suffix(".csv")
    csv_content = (
        "action\tsource_text\tmeaning_zh\tmeaning_en\trendering"
        "\tcandidate_id\tevidence_snippet\talternatives\n"
    )
    csv_path.write_text(csv_content, encoding="utf-8")

    result = promote_idiom_candidates(
        release_id=release_id,
        run_id="promote-001",
        review_file_path=csv_path,
    )
    assert result["status"] == "success"
    assert result["promoted_count"] == 0


def test_save_idiom_translation_fills_candidate_rendering(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m18d-translate"
    _write_extracted_chapter(
        release_id=release_id,
        chapter_number=1,
        source_text="他可谓一箭双雕。",
    )
    config = load_config()
    paths = derive_paths(config, release_id=release_id)
    prompt = load_prompt("idiom_detect.txt")
    llm = ScriptedIdiomLLM()
    candidates = extract_idioms(
        release_id=release_id,
        extracted_chapters_dir=paths.extracted_chapters_dir,
        detection_run_id="idioms-001",
        llm_client=llm,
        model_name=config.models.analyst_name,
        prompt_template=prompt.template,
        prompt_version=prompt.version,
        skip_llm_eval=True,
    )

    conn = open_connection(paths.db_path)
    ensure_idiom_schema(conn)
    try:
        upsert_discovered_candidates(conn, candidates=candidates)
        pending_translation = list_candidates_for_translation(conn, release_id=release_id)
        assert len(pending_translation) == 1
        assert list_candidates_for_promotion(conn, release_id=release_id) == []

        save_idiom_translation(
            conn,
            candidate_id=pending_translation[0].candidate_id,
            translation_run_id="idioms-001",
            target_term="kill two birds with one stone",
            meaning_en="achieve two things at once",
            translator_model_name=config.models.translator_name,
            translator_prompt_version="1.0",
        )

        saved = list_candidates(conn, release_id=release_id)[0]
        assert saved.preferred_rendering_en == "kill two birds with one stone"
        assert saved.meaning_en == "achieve two things at once"
        assert saved.translation_run_id == "idioms-001"
        assert saved.translator_model_name == config.models.translator_name
        assert saved.translator_prompt_version == "1.0"
        assert saved.candidate_status == "translated"
        assert list_candidates_for_translation(conn, release_id=release_id) == []
        promotable_ids = [
            candidate.candidate_id
            for candidate in list_candidates_for_promotion(conn, release_id=release_id)
        ]
        assert promotable_ids == [saved.candidate_id]
    finally:
        conn.close()


def test_preprocess_idioms_merges_normalized_duplicates(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m5-merge"
    _write_extracted_chapter(
        release_id=release_id,
        chapter_number=1,
        source_text="他可谓一箭双雕。",
    )
    _write_extracted_chapter(
        release_id=release_id,
        chapter_number=2,
        source_text="这一招真是一箭双雕。",
    )

    llm = ScriptedIdiomLLM()
    translator = ScriptedTranslatorLLM("kill two birds with one stone")
    result = preprocess_idioms(
        release_id=release_id,
        run_id="idioms-001",
        llm_client=llm,
        translator_llm_client=translator,
    )

    assert result["status"] == "success"
    assert result["promoted_count"] == 1
    assert result["conflict_count"] == 0

    config = load_config()
    paths = derive_paths(config, release_id=release_id)
    conn = open_connection(paths.db_path)
    ensure_idiom_schema(conn)
    try:
        policies = list_policies(conn, release_id=release_id)
        assert len(policies) == 1
        policy = policies[0]
        assert policy.first_seen_chapter == 1
        assert policy.last_seen_chapter == 2
        assert policy.appearance_count >= 2
    finally:
        conn.close()


def test_preprocess_idioms_emits_chapter_events(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m19-idiom-events"
    _write_extracted_chapter(
        release_id=release_id,
        chapter_number=1,
        source_text="他可谓一箭双雕。",
    )
    llm = ScriptedIdiomLLM()
    translator = ScriptedTranslatorLLM("kill two birds with one stone")
    from resemantica.orchestration.events import subscribe, unsubscribe

    received = []

    def callback(event):
        if event.run_id == "idioms-events":
            received.append(event)

    subscribe("*", callback)
    try:
        preprocess_idioms(
            release_id=release_id,
            run_id="idioms-events",
            llm_client=llm,
            translator_llm_client=translator,
        )
    finally:
        unsubscribe("*", callback)

    event_types = [event.event_type for event in received]
    assert event_types[0] == "preprocess-idioms.started"
    assert "preprocess-idioms.chapter_started" in event_types
    assert "preprocess-idioms.chapter_completed" in event_types
    assert "preprocess-idioms.eval_batch_start" in event_types
    assert "preprocess-idioms.eval_batch_success" in event_types
    assert "preprocess-idioms.translate.started" in event_types
    assert "preprocess-idioms.translate.model_started" in event_types
    assert "preprocess-idioms.translate.model_completed" in event_types
    assert "preprocess-idioms.translate.completed" in event_types
    assert event_types[-1] == "preprocess-idioms.completed"


def test_extract_idioms_forwards_eval_batch_events_with_no_chapter(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m19-idiom-extract-eval-events"
    _write_extracted_chapter(
        release_id=release_id,
        chapter_number=1,
        source_text="他可谓一箭双雕。",
    )
    config = load_config()
    paths = derive_paths(config, release_id=release_id)
    prompt = load_prompt("idiom_evaluate.txt")
    events: list[tuple[str, int | None, dict[str, object]]] = []

    extract_idioms(
        release_id=release_id,
        extracted_chapters_dir=paths.extracted_chapters_dir,
        detection_run_id="idioms-001",
        llm_client=ScriptedIdiomLLM(),
        model_name=config.models.analyst_name,
        prompt_template=prompt.template,
        prompt_version=prompt.version,
        event_callback=lambda event_name, chapter_number, payload: events.append(
            (event_name, chapter_number, payload)
        ),
    )

    eval_events = [event for event in events if event[0].startswith("eval_batch_")]
    assert [event[0] for event in eval_events] == ["eval_batch_start", "eval_batch_success"]
    assert [event[1] for event in eval_events] == [None, None]
    assert eval_events[0][2]["model_name"] == config.models.analyst_name


def test_duplicate_conflict_rejects_policy_promotion(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m5-duplicate-conflict"

    # Write two chapters with the same idiom to test upsert merge
    _write_extracted_chapter(
        release_id=release_id,
        chapter_number=1,
        source_text="他想一箭双雕。",
    )
    _write_extracted_chapter(
        release_id=release_id,
        chapter_number=2,
        source_text="此计可谓一箭双雕。",
    )

    # Both chapters detect the same idiom — should merge into one candidate
    llm = ScriptedIdiomLLM()
    translator = ScriptedTranslatorLLM("kill two birds with one stone")
    result = preprocess_idioms(
        release_id=release_id,
        run_id="idioms-001",
        llm_client=llm,
        translator_llm_client=translator,
    )

    assert result["status"] == "success"
    assert result["promoted_count"] == 1

    config = load_config()
    paths = derive_paths(config, release_id=release_id)
    conn = open_connection(paths.db_path)
    ensure_idiom_schema(conn)
    try:
        policies = list_policies(conn, release_id=release_id)
        assert len(policies) == 1
        policy = policies[0]
        assert policy.normalized_source_text == "一箭双雕"
        # appearance_count should be summed across chapters
        assert policy.appearance_count == 2
    finally:
        conn.close()


def test_existing_policy_conflict_is_recorded(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m5-canon-conflict"
    _write_extracted_chapter(
        release_id=release_id,
        chapter_number=1,
        source_text="此计可谓一箭双雕。",
    )
    _insert_policy(
        release_id=release_id,
        source_text="一箭双雕",
        meaning_zh="一举两得",
        preferred_rendering_en="kill two birds with one stone",
    )

    llm = ScriptedIdiomLLM()
    translator = ScriptedTranslatorLLM("one move, two wins")
    result = preprocess_idioms(
        release_id=release_id,
        run_id="idioms-001",
        llm_client=llm,
        translator_llm_client=translator,
    )

    assert result["status"] == "success"
    assert result["promoted_count"] == 0
    assert result["conflict_count"] == 1

    config = load_config()
    paths = derive_paths(config, release_id=release_id)
    conn = open_connection(paths.db_path)
    ensure_idiom_schema(conn)
    try:
        conflicts = list_conflicts(conn, release_id=release_id)
        assert len(conflicts) == 1
        assert conflicts[0].conflict_type == "canon_conflict"
    finally:
        conn.close()


def test_exact_match_precedence_hook_uses_locked_policy(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m5-precedence"
    _insert_policy(
        release_id=release_id,
        source_text="一箭双雕",
        meaning_zh="一举两得",
        preferred_rendering_en="kill two birds with one stone",
    )

    resolved = resolve_idiom_policy(
        release_id=release_id,
        source_text="一箭双雕",
        fallback_rendering="fuzzy fallback",
    )
    assert resolved == "kill two birds with one stone"

    missing = resolve_idiom_policy(
        release_id=release_id,
        source_text="杯弓蛇影",
        fallback_rendering="fuzzy fallback",
    )
    assert missing == "fuzzy fallback"

    config = load_config()
    paths = derive_paths(config, release_id=release_id)
    conn = open_connection(paths.db_path)
    ensure_idiom_schema(conn)
    try:
        matched = match_idioms(text="他这招可谓一箭双雕。", idiom_policies=list_policies(conn, release_id=release_id))
        assert len(matched) == 1
        assert matched[0].source_text == "一箭双雕"
    finally:
        conn.close()


def test_idiom_checkpoint_read_write(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    config = load_config()
    paths = derive_paths(config, release_id="idi-cp-test")
    conn = open_connection(paths.db_path)
    ensure_idiom_schema(conn)
    try:
        assert get_checkpoint(conn, release_id="idi-cp-test", run_id="r1") is None

        set_checkpoint(conn, release_id="idi-cp-test", run_id="r1", stage_name="detect_completed")
        assert get_checkpoint(conn, release_id="idi-cp-test", run_id="r1") == "detect_completed"

        set_checkpoint(conn, release_id="idi-cp-test", run_id="r1", stage_name="translated")
        assert get_checkpoint(conn, release_id="idi-cp-test", run_id="r1") == "translated"

        assert get_checkpoint(conn, release_id="idi-cp-test", run_id="other") is None
    finally:
        conn.close()


def test_preprocess_idioms_handles_missing_summaries_table(tmp_path: Path, monkeypatch) -> None:
    """Verify preprocess_idioms doesn't crash when summary_drafts table doesn't exist."""
    monkeypatch.chdir(tmp_path)
    config = load_config()
    paths = derive_paths(config, release_id="idi-no-sum")
    conn = open_connection(paths.db_path)
    ensure_idiom_schema(conn)
    conn.close()

    _write_extracted_chapter(
        release_id="idi-no-sum",
        chapter_number=1,
        source_text="汝此计可谓一箭双雕。",
    )

    llm = ScriptedIdiomLLM()
    translator = ScriptedTranslatorLLM("one move, two wins")
    result = preprocess_idioms(
        release_id="idi-no-sum",
        run_id="idioms-001",
        llm_client=llm,
        translator_llm_client=translator,
    )
    assert result["status"] == "success"
