from __future__ import annotations

import json
import re
import sqlite3
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from resemantica.db.glossary_repo import (
    ensure_glossary_schema,
    list_conflicts,
    list_locked_entries,
    list_translation_votes,
    promote_locked_entries,
    upsert_discovered_candidates,
)
from resemantica.db.sqlite import open_connection
from resemantica.epub.extractor import extract_epub
from resemantica.glossary.evaluator import EvalResult
from resemantica.glossary.models import AliasCluster, GlossaryCandidate, LockedGlossaryEntry
from resemantica.glossary.pipeline import (
    discover_glossary_candidates,
    promote_glossary_candidates,
    resolve_locked_glossary_term,
    review_glossary_candidates,
    translate_glossary_candidates,
)
from resemantica.glossary.validators import normalize_term
from resemantica.settings import AppConfig, LLMConfig, derive_paths, load_config


class ScriptedGlossaryLLM:
    def __init__(self, rows_by_chapter: dict[int, list[dict[str, str]]]) -> None:
        self.rows_by_chapter = rows_by_chapter

    def generate_text(self, *, model_name: str, prompt: str) -> str:  # noqa: ARG002
        chapter_match = re.search(r"## CHAPTER NUMBER\s+(\d+)", prompt)
        if chapter_match is None:
            raise RuntimeError("chapter number missing from glossary prompt")
        chapter_number = int(chapter_match.group(1))
        return json.dumps(
            {"glossary_terms": self.rows_by_chapter.get(chapter_number, [])},
            ensure_ascii=False,
        )


def _eval_all_keep(*, candidates, **kwargs) -> list:
    """Monkeypatch helper: LLM evaluator keeps every candidate."""
    return [
        EvalResult(
            candidate_id=c.candidate_id,
            keep=True,
            term_type=c.type_prior or "unknown",
            reason_code="test",
            confidence=0.9,
        )
        for c in candidates
    ]


def _dedup_noop(
    *,
    candidates: list[GlossaryCandidate],
    **kwargs: object,  # noqa: ARG001
) -> tuple[list[GlossaryCandidate], list[AliasCluster]]:
    return candidates, []


def _write_fixture_epub(epub_path: Path, chapter_xhtml: str) -> None:
    workspace = epub_path.parent / "fixture_book_glossary"
    meta_inf = workspace / "META-INF"
    oebps = workspace / "OEBPS"
    meta_inf.mkdir(parents=True, exist_ok=True)
    oebps.mkdir(parents=True, exist_ok=True)

    (workspace / "mimetype").write_text("application/epub+zip", encoding="utf-8")
    (meta_inf / "container.xml").write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
""",
        encoding="utf-8",
    )
    (oebps / "content.opf").write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<package version="3.0" xmlns="http://www.idpf.org/2007/opf">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Fixture</dc:title>
    <dc:language>zh-CN</dc:language>
    <dc:identifier>fixture-book</dc:identifier>
  </metadata>
  <manifest>
    <item id="chap1" href="chapter1.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="chap1"/>
  </spine>
</package>
""",
        encoding="utf-8",
    )
    (oebps / "chapter1.xhtml").write_text(chapter_xhtml, encoding="utf-8")

    with zipfile.ZipFile(epub_path, "w") as archive:
        archive.write(workspace / "mimetype", arcname="mimetype", compress_type=zipfile.ZIP_STORED)
        for file_path in sorted(workspace.rglob("*")):
            if not file_path.is_file() or file_path.name == "mimetype":
                continue
            archive.write(
                file_path,
                arcname=file_path.relative_to(workspace).as_posix(),
                compress_type=zipfile.ZIP_DEFLATED,
            )


def _extract_one_chapter(tmp_path: Path, *, release_id: str, source_text: str) -> None:
    input_epub = tmp_path / f"{release_id}.epub"
    chapter_xhtml = (
        """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body><p>"""
        + source_text
        + "</p></body></html>"
    )
    _write_fixture_epub(input_epub, chapter_xhtml)
    result = extract_epub(input_path=input_epub, release_id=release_id)
    assert result.status == "success"


class StaticGlossaryTranslator:
    def __init__(self, target_term: str) -> None:
        self.target_term = target_term

    def translate_glossary_candidate(  # noqa: D401
        self,
        *,
        model_name: str,  # noqa: ARG002
        prompt_template: str,  # noqa: ARG002
        source_term: str,  # noqa: ARG002
        category: str,  # noqa: ARG002
        evidence_snippet: str,  # noqa: ARG002
    ) -> str:
        return self.target_term


class ModelMappedGlossaryTranslator:
    def __init__(self, outputs: dict[tuple[str, str], str]) -> None:
        self.outputs = outputs
        self.calls: list[tuple[str, str]] = []

    def translate_glossary_candidate(
        self,
        *,
        model_name: str,
        prompt_template: str,  # noqa: ARG002
        source_term: str,
        category: str,  # noqa: ARG002
        evidence_snippet: str,  # noqa: ARG002
    ) -> str:
        self.calls.append((model_name, source_term))
        return self.outputs[(model_name, source_term)]


def _insert_glossary_candidate(
    *,
    release_id: str,
    source_term: str,
    category: str = "faction",
) -> None:
    config = load_config()
    paths = derive_paths(config, release_id=release_id)
    conn = open_connection(paths.db_path)
    ensure_glossary_schema(conn)
    try:
        upsert_discovered_candidates(
            conn,
            candidates=[
                GlossaryCandidate(
                    candidate_id=f"gcan_{normalize_term(source_term)}",
                    release_id=release_id,
                    source_term=source_term,
                    normalized_source_term=normalize_term(source_term),
                    category=category,
                    source_language="zh",
                    first_seen_chapter=1,
                    last_seen_chapter=1,
                    appearance_count=1,
                    evidence_snippet=source_term,
                    candidate_translation_en=None,
                    normalized_target_term=None,
                    discovery_run_id="seed",
                    translation_run_id=None,
                    candidate_status="discovered",
                    validation_status="pending",
                    conflict_reason=None,
                    llm_keep=1,
                )
            ],
        )
    finally:
        conn.close()


def test_discovery_writes_candidates_only(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _extract_one_chapter(
        tmp_path,
        release_id="m3-discovery",
        source_text="青云门弟子张三来到青云山。",
    )

    llm = ScriptedGlossaryLLM({
        1: [
            {"source_term": "青云门", "category": "faction", "evidence_snippet": "青云门弟子张三来到青云山"},
            {"source_term": "张三", "category": "character", "evidence_snippet": "青云门弟子张三来到青云山"},
            {"source_term": "青云山", "category": "location", "evidence_snippet": "青云门弟子张三来到青云山"},
        ],
    })

    result = discover_glossary_candidates(
        release_id="m3-discovery",
        run_id="discover-001",
        llm_client=llm,
    )
    assert result["status"] == "success"
    assert result["candidates_written"] > 0

    config = load_config()
    paths = derive_paths(config, release_id="m3-discovery")
    conn = open_connection(paths.db_path)
    ensure_glossary_schema(conn)
    try:
        candidate_count = conn.execute(
            "SELECT COUNT(*) AS count FROM glossary_candidates WHERE release_id = ?",
            ("m3-discovery",),
        ).fetchone()
        locked_count = conn.execute(
            "SELECT COUNT(*) AS count FROM locked_glossary WHERE release_id = ?",
            ("m3-discovery",),
        ).fetchone()
        assert candidate_count is not None and int(candidate_count["count"]) > 0
        assert locked_count is not None and int(locked_count["count"]) == 0
    finally:
        conn.close()


def test_multi_model_glossary_translation_majority_and_review_alternatives(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m42-glossary-votes"
    _insert_glossary_candidate(release_id=release_id, source_term="青云门")
    _insert_glossary_candidate(release_id=release_id, source_term="苍云门")
    translator = ModelMappedGlossaryTranslator(
        {
            ("model-a", "青云门"): "Azure Sect",
            ("model-b", "青云门"): "Azure Sect",
            ("model-c", "青云门"): "Blue Cloud Gate",
            ("model-a", "苍云门"): "Cangyun Gate",
            ("model-b", "苍云门"): "Azure Cloud Sect",
            ("model-c", "苍云门"): "Blue Cloud Gate",
        }
    )
    config = AppConfig()
    config.models.preprocess_translator_names = ["model-a", "model-b", "model-c"]

    result = translate_glossary_candidates(
        release_id=release_id,
        run_id="translate-001",
        config=config,
        llm_client=translator,
    )

    assert result["translated_count"] == 1
    assert result["unresolved_count"] == 1
    assert translator.calls == [
        ("model-a", "苍云门"),
        ("model-a", "青云门"),
        ("model-b", "苍云门"),
        ("model-b", "青云门"),
        ("model-c", "苍云门"),
        ("model-c", "青云门"),
    ]

    paths = derive_paths(load_config(), release_id=release_id)
    conn = open_connection(paths.db_path)
    ensure_glossary_schema(conn)
    try:
        rows = conn.execute(
            """
            SELECT candidate_id, source_term, candidate_translation_en, candidate_status
            FROM glossary_candidates
            WHERE release_id = ?
            ORDER BY source_term
            """,
            (release_id,),
        ).fetchall()
        assert [(row["source_term"], row["candidate_translation_en"], row["candidate_status"]) for row in rows] == [
            ("苍云门", None, "discovered"),
            ("青云门", "Azure Sect", "translated"),
        ]
        votes = list_translation_votes(conn, release_id=release_id)
        assert len(votes) == 6
        ids_by_source = {str(row["source_term"]): str(row["candidate_id"]) for row in rows}
        assert {
            vote.resolution_status
            for vote in votes
            if vote.candidate_id == ids_by_source["青云门"]
        } == {"majority"}
        assert {
            vote.resolution_status
            for vote in votes
            if vote.candidate_id == ids_by_source["苍云门"]
        } == {"unresolved"}
    finally:
        conn.close()

    review = review_glossary_candidates(release_id=release_id, run_id="review-001")
    assert review["entries_written"] == 2
    review_data = json.loads(paths.glossary_review_path.read_text(encoding="utf-8"))
    unresolved = next(entry for entry in review_data["entries"] if entry["source_term"] == "苍云门")
    assert unresolved["translation"] == ""
    assert [alt["translation"] for alt in unresolved["alternatives"]] == [
        "Cangyun Gate",
        "Azure Cloud Sect",
        "Blue Cloud Gate",
    ]


def test_review_csv_written_and_matches_json(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m46-csv"
    _insert_glossary_candidate(release_id=release_id, source_term="青云门")
    _insert_glossary_candidate(release_id=release_id, source_term="苍云门")
    translator = ModelMappedGlossaryTranslator({
        ("model-a", "青云门"): "Azure Sect",
        ("model-b", "青云门"): "Azure Sect",
        ("model-c", "青云门"): "Blue Cloud Gate",
        ("model-a", "苍云门"): "Cangyun Gate",
        ("model-b", "苍云门"): "Azure Cloud Sect",
        ("model-c", "苍云门"): "Blue Cloud Gate",
    })
    config = AppConfig()
    config.models.preprocess_translator_names = ["model-a", "model-b", "model-c"]
    translate_glossary_candidates(
        release_id=release_id, run_id="translate-001", config=config, llm_client=translator,
    )

    review = review_glossary_candidates(release_id=release_id, run_id="review-001")
    assert review["entries_written"] == 2

    paths = derive_paths(load_config(), release_id=release_id)
    csv_path = paths.glossary_review_path.with_suffix(".csv")
    assert csv_path.exists(), f"CSV review file not found: {csv_path}"

    import csv
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f, delimiter="\t")
        rows = list(reader)
    assert len(rows) == 3  # header + 2 entries
    assert rows[0] == ["action", "source_term", "category", "translation",
                       "candidate_id", "evidence_snippet", "alternatives"]
    row_keep = next(r for r in rows[1:] if r[1] == "青云门")
    assert row_keep[0] == "keep"
    assert row_keep[3] == "Azure Sect"
    assert "Azure Sect" in row_keep[6] and "Blue Cloud Gate" in row_keep[6]

    json_data = json.loads(paths.glossary_review_path.read_text(encoding="utf-8"))
    csv_sources = {r[1] for r in rows[1:]}
    json_sources = {e["source_term"] for e in json_data["entries"]}
    assert csv_sources == json_sources


def test_promote_with_csv_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m46-csv-promote"
    _insert_glossary_candidate(release_id=release_id, source_term="青云门")
    _insert_glossary_candidate(release_id=release_id, source_term="苍云门")

    translator = ModelMappedGlossaryTranslator({
        ("model-a", "青云门"): "Azure Sect",
        ("model-b", "青云门"): "Azure Sect",
        ("model-c", "青云门"): "Blue Cloud Gate",
        ("model-a", "苍云门"): "Cangyun Gate",
        ("model-b", "苍云门"): "Azure Cloud Sect",
        ("model-c", "苍云门"): "Blue Cloud Gate",
    })
    config = AppConfig()
    config.models.preprocess_translator_names = ["model-a", "model-b", "model-c"]
    translate_glossary_candidates(
        release_id=release_id, run_id="translate-001", config=config, llm_client=translator,
    )

    paths = derive_paths(load_config(), release_id=release_id)
    conn = open_connection(paths.db_path)
    ensure_glossary_schema(conn)
    try:
        rows = conn.execute(
            "SELECT candidate_id, source_term FROM glossary_candidates WHERE release_id = ?",
            (release_id,),
        ).fetchall()
        ids = {str(r["source_term"]): str(r["candidate_id"]) for r in rows}
    finally:
        conn.close()

    csv_path = paths.glossary_review_path.with_suffix(".csv")
    csv_content = (
        "action\tsource_term\tcategory\ttranslation\tcandidate_id\tevidence_snippet\talternatives\n"
        f"keep\t青云门\tfaction\tOverridden Azure\t{ids['青云门']}\t\t\n"
        f"delete\t苍云门\tfaction\t\t{ids['苍云门']}\t\t\n"
    )
    csv_path.write_text(csv_content, encoding="utf-8")

    result = promote_glossary_candidates(
        release_id=release_id, run_id="promote-001", review_file_path=csv_path,
    )
    assert result["status"] == "success"

    conn = open_connection(paths.db_path)
    ensure_glossary_schema(conn)
    try:
        locked = list_locked_entries(conn, release_id=release_id)
        locked_names = {e.source_term: e.target_term for e in locked}
        assert "青云门" in locked_names, "Overridden keep entry should be promoted"
        assert locked_names["青云门"] == "Overridden Azure"
        assert "苍云门" not in locked_names, "Deleted entry should not be promoted"
    finally:
        conn.close()


def test_promote_with_csv_add_entry(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m46-csv-add"
    _insert_glossary_candidate(release_id=release_id, source_term="青云门")

    translator = ModelMappedGlossaryTranslator({
        ("model-a", "青云门"): "Azure Sect",
        ("model-b", "青云门"): "Azure Sect",
        ("model-c", "青云门"): "Blue Cloud Gate",
    })
    config = AppConfig()
    config.models.preprocess_translator_names = ["model-a", "model-b", "model-c"]
    translate_glossary_candidates(
        release_id=release_id, run_id="translate-001", config=config, llm_client=translator,
    )

    paths = derive_paths(load_config(), release_id=release_id)
    conn = open_connection(paths.db_path)
    ensure_glossary_schema(conn)
    try:
        row = conn.execute(
            "SELECT candidate_id FROM glossary_candidates WHERE release_id = ? AND source_term = ?",
            (release_id, "青云门"),
        ).fetchone()
        qingyun_id = str(row["candidate_id"]) if row else ""
    finally:
        conn.close()

    csv_path = paths.glossary_review_path.with_suffix(".csv")
    csv_content = (
        "action\tsource_term\tcategory\ttranslation\tcandidate_id\tevidence_snippet\talternatives\n"
        f"keep\t青云门\tfaction\tAzure Sect\t{qingyun_id}\t\t\n"
        "add\t新门派\tfaction\tNew Sect\t\t源自新章节的文本\t\n"
    )
    csv_path.write_text(csv_content, encoding="utf-8")

    result = promote_glossary_candidates(
        release_id=release_id, run_id="promote-001", review_file_path=csv_path,
    )
    assert result["status"] == "success"

    conn = open_connection(paths.db_path)
    ensure_glossary_schema(conn)
    try:
        locked = list_locked_entries(conn, release_id=release_id)
        locked_names = {e.source_term: e.target_term for e in locked}
        assert "青云门" in locked_names
        assert "新门派" in locked_names
        assert locked_names["新门派"] == "New Sect"
    finally:
        conn.close()


def test_promote_csv_bad_header_raises(tmp_path: Path) -> None:
    csv_path = tmp_path / "bad.csv"
    csv_path.write_text("col1\tcol2\tcol3\n", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid header"):
        from resemantica.glossary.pipeline import _read_review_data
        _read_review_data(csv_path)


def test_promote_csv_empty_is_noop(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m46-csv-empty"
    _insert_glossary_candidate(release_id=release_id, source_term="青云门")

    translator = ModelMappedGlossaryTranslator({
        ("model-a", "青云门"): "Azure Sect",
        ("model-b", "青云门"): "Azure Sect",
        ("model-c", "青云门"): "Blue Cloud Gate",
    })
    config = AppConfig()
    config.models.preprocess_translator_names = ["model-a", "model-b", "model-c"]
    translate_glossary_candidates(
        release_id=release_id, run_id="translate-001", config=config, llm_client=translator,
    )

    paths = derive_paths(load_config(), release_id=release_id)
    csv_path = paths.glossary_review_path.with_suffix(".csv")
    csv_content = "action\tsource_term\tcategory\ttranslation\tcandidate_id\tevidence_snippet\talternatives\n"
    csv_path.write_text(csv_content, encoding="utf-8")

    result = promote_glossary_candidates(
        release_id=release_id, run_id="promote-001", review_file_path=csv_path,
    )
    assert result["status"] == "success"


def test_promote_json_still_works(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m46-json-backward"
    _insert_glossary_candidate(release_id=release_id, source_term="青云门")

    translator = ModelMappedGlossaryTranslator({
        ("model-a", "青云门"): "Azure Sect",
        ("model-b", "青云门"): "Azure Sect",
        ("model-c", "青云门"): "Blue Cloud Gate",
    })
    config = AppConfig()
    config.models.preprocess_translator_names = ["model-a", "model-b", "model-c"]
    translate_glossary_candidates(
        release_id=release_id, run_id="translate-001", config=config, llm_client=translator,
    )

    paths = derive_paths(load_config(), release_id=release_id)
    json_path = paths.glossary_review_path
    review = review_glossary_candidates(release_id=release_id, run_id="review-001")
    assert review["entries_written"] == 1

    result = promote_glossary_candidates(
        release_id=release_id, run_id="promote-001", review_file_path=json_path,
    )
    assert result["status"] == "success"

    conn = open_connection(paths.db_path)
    ensure_glossary_schema(conn)
    try:
        locked = list_locked_entries(conn, release_id=release_id)
        assert any(e.source_term == "青云门" for e in locked)
    finally:
        conn.close()


def test_discovery_builds_llm_client_from_config(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _extract_one_chapter(
        tmp_path,
        release_id="m3-configured-llm",
        source_text="青云门弟子张三来到青云山。",
    )

    built: dict[str, object] = {}

    class _FakeCompletions:
        def create(self, **kwargs: object) -> object:
            built["request"] = kwargs
            message = type(
                "Message",
                (),
                {
                    "content": json.dumps(
                        {
                            "glossary_terms": [
                                {
                                    "source_term": "青云门",
                                    "category": "faction",
                                    "evidence_snippet": "青云门弟子张三来到青云山",
                                }
                            ]
                        },
                        ensure_ascii=False,
                    )
                },
            )()
            choice = type("Choice", (), {"message": message})()
            return type("Response", (), {"choices": [choice]})()

    class _FakeChat:
        def __init__(self) -> None:
            self.completions = _FakeCompletions()

    class _FakeOpenAIClient:
        def __init__(self) -> None:
            self.chat = _FakeChat()

    def fake_build_openai_client(self):
        built["base_url"] = self.base_url
        built["timeout_seconds"] = self.timeout_seconds
        built["max_retries"] = self.max_retries
        return _FakeOpenAIClient()

    monkeypatch.setattr(
        "resemantica.llm.client.LLMClient._build_openai_client",
        fake_build_openai_client,
    )

    config = AppConfig()
    config.llm = LLMConfig(
        base_url="http://127.0.0.1:9999",
        timeout_seconds=123,
        max_retries=7,
        context_window=config.llm.context_window,
    )

    result = discover_glossary_candidates(
        release_id="m3-configured-llm",
        run_id="discover-configured-llm",
        config=config,
    )

    assert result["status"] == "success"
    assert result["candidates_written"] > 0
    assert built["base_url"] == "http://127.0.0.1:9999"
    assert built["timeout_seconds"] == 123
    assert built["max_retries"] == 7


def test_glossary_pipeline_emits_phase_events(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m19-glossary-events"
    _extract_one_chapter(
        tmp_path,
        release_id=release_id,
        source_text="青云门弟子张三来到青云山。",
    )
    llm = ScriptedGlossaryLLM({
        1: [
            {"source_term": "青云门", "category": "faction", "evidence_snippet": "青云门弟子"},
        ],
    })
    from resemantica.orchestration.events import subscribe, unsubscribe

    received = []

    def callback(event):
        if event.run_id == "glossary-events":
            received.append(event)

    monkeypatch.setattr("resemantica.glossary.pipeline.evaluate_candidate_batch", _eval_all_keep)
    monkeypatch.setattr("resemantica.glossary.pipeline.deduplicate_and_cluster", _dedup_noop)
    subscribe("*", callback)
    try:
        discover_glossary_candidates(
            release_id=release_id,
            run_id="glossary-events",
            llm_client=llm,
        )
        translate_glossary_candidates(
            release_id=release_id,
            run_id="glossary-events",
            llm_client=StaticGlossaryTranslator("Azure Sect"),
        )
        promote_glossary_candidates(
            release_id=release_id,
            run_id="glossary-events",
        )
    finally:
        unsubscribe("*", callback)

    event_types = [event.event_type for event in received]
    assert "preprocess-glossary.started" in event_types
    assert "preprocess-glossary.discover.started" in event_types
    assert "preprocess-glossary.discover.chapter_started" in event_types
    assert "preprocess-glossary.discover.chapter_completed" in event_types
    assert "preprocess-glossary.discover.scoring.started" in event_types
    assert "preprocess-glossary.discover.scoring.progress" in event_types
    assert "preprocess-glossary.discover.scoring.completed" in event_types
    assert "preprocess-glossary.discover.dedup.started" in event_types
    assert "preprocess-glossary.discover.dedup.completed" in event_types
    assert "preprocess-glossary.discover.dedup.persisted" in event_types
    assert "preprocess-glossary.discover.checkpoint.completed" in event_types
    assert "preprocess-glossary.discover.snapshot.artifact_written" in event_types
    assert "preprocess-glossary.discover.completed" in event_types
    assert "preprocess-glossary.translate.started" in event_types
    assert "preprocess-glossary.translate.chapter_started" in event_types
    assert "preprocess-glossary.translate.completed" in event_types
    assert "preprocess-glossary.promote.started" in event_types
    assert "preprocess-glossary.promote.completed" in event_types
    assert event_types[-1] == "preprocess-glossary.completed"
    chapter_completed_index = event_types.index("preprocess-glossary.discover.chapter_completed")
    scoring_started_index = event_types.index("preprocess-glossary.discover.scoring.started")
    scoring_completed_index = event_types.index("preprocess-glossary.discover.scoring.completed")
    filter_completed_index = event_types.index("preprocess-glossary.discover.filter_completed")
    dedup_started_index = event_types.index("preprocess-glossary.discover.dedup.started")
    dedup_completed_index = event_types.index("preprocess-glossary.discover.dedup.completed")
    dedup_persisted_index = event_types.index("preprocess-glossary.discover.dedup.persisted")
    checkpoint_completed_index = event_types.index("preprocess-glossary.discover.checkpoint.completed")
    snapshot_written_index = event_types.index("preprocess-glossary.discover.snapshot.artifact_written")
    discover_completed_index = event_types.index("preprocess-glossary.discover.completed")
    assert chapter_completed_index < scoring_started_index < scoring_completed_index < filter_completed_index
    assert (
        filter_completed_index
        < dedup_started_index
        < dedup_completed_index
        < dedup_persisted_index
        < checkpoint_completed_index
        < snapshot_written_index
        < discover_completed_index
    )
    scoring_completed = received[scoring_completed_index]
    assert {
        "candidate_count",
        "duration_ms",
        "top_score",
        "median_score",
        "min_score",
    }.issubset(scoring_completed.payload)
    assert all(
        event.message
        for event in received
        if event.event_type.startswith("preprocess-glossary") and ".eval." not in event.event_type
    )


def test_glossary_pipeline_emits_finalization_events_with_no_candidates(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m60-empty-finalization"
    run_id = "glossary-empty-finalization"
    _extract_one_chapter(
        tmp_path,
        release_id=release_id,
        source_text="。",
    )
    llm = ScriptedGlossaryLLM({1: []})
    from resemantica.orchestration.events import subscribe, unsubscribe

    received = []

    def callback(event):
        if event.run_id == run_id:
            received.append(event)

    monkeypatch.setattr(
        "resemantica.glossary.discovery.generate_chapter_candidates",
        lambda text, summary_data=None: [],  # noqa: ARG005
    )
    subscribe("*", callback)
    try:
        result = discover_glossary_candidates(
            release_id=release_id,
            run_id=run_id,
            llm_client=llm,
            skip_llm_eval=True,
        )
    finally:
        unsubscribe("*", callback)

    assert result["status"] == "success"
    assert result["candidates_written"] == 0
    event_types = [event.event_type for event in received]
    assert "preprocess-glossary.discover.dedup.completed" in event_types
    assert "preprocess-glossary.discover.dedup.persisted" in event_types
    assert "preprocess-glossary.discover.checkpoint.completed" in event_types
    assert "preprocess-glossary.discover.snapshot.artifact_written" in event_types
    dedup_completed = next(
        event for event in received if event.event_type == "preprocess-glossary.discover.dedup.completed"
    )
    assert dedup_completed.payload["skipped"] is True
    assert dedup_completed.payload["reason"] == "no_candidates"
    snapshot_written = next(
        event for event in received if event.event_type == "preprocess-glossary.discover.snapshot.artifact_written"
    )
    assert snapshot_written.payload["candidate_count"] == 0


def test_duplicate_target_conflict_blocks_promotion(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _extract_one_chapter(
        tmp_path,
        release_id="m3-conflict",
        source_text="紫霄宗。青冥宗。",
    )

    llm = ScriptedGlossaryLLM({
        1: [
            {"source_term": "紫霄宗", "category": "faction", "evidence_snippet": "紫霄宗"},
            {"source_term": "青冥宗", "category": "faction", "evidence_snippet": "青冥宗"},
        ],
    })

    monkeypatch.setattr("resemantica.glossary.pipeline.evaluate_candidate_batch", _eval_all_keep)
    discover_glossary_candidates(release_id="m3-conflict", run_id="discover-001", llm_client=llm)
    translate_glossary_candidates(
        release_id="m3-conflict",
        run_id="translate-001",
        llm_client=StaticGlossaryTranslator("Azure Sect"),
    )
    result = promote_glossary_candidates(
        release_id="m3-conflict",
        run_id="promote-001",
    )

    # Some non-conflicting candidates may still promote; verify conflict exists
    assert result["conflict_count"] > 0

    config = load_config()
    paths = derive_paths(config, release_id="m3-conflict")
    conn = open_connection(paths.db_path)
    ensure_glossary_schema(conn)
    try:
        locked = list_locked_entries(conn, release_id="m3-conflict")
        conflicts = list_conflicts(conn, release_id="m3-conflict")
        azure_factions = [e for e in locked if e.target_term == "Azure Sect" and e.category == "faction"]
        assert len(azure_factions) == 0, (
            f"Duplicate-target conflict should block Azure Sect faction entries (got {len(azure_factions)})"
        )
        assert any(conflict.conflict_type == "duplicate_target" for conflict in conflicts)
    finally:
        conn.close()


def test_promotion_insert_is_transactional(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    config = load_config()
    paths = derive_paths(config, release_id="m3-transaction")
    conn = open_connection(paths.db_path)
    ensure_glossary_schema(conn)
    approved_at = datetime.now(UTC).isoformat()

    entry_a = LockedGlossaryEntry(
        glossary_entry_id="glex_txn_a",
        release_id="m3-transaction",
        source_term="青云门",
        normalized_source_term=normalize_term("青云门"),
        target_term="Azure Sect",
        normalized_target_term=normalize_term("Azure Sect"),
        category="faction",
        status="approved",
        approved_at=approved_at,
        approval_run_id="promote-001",
        source_candidate_id="gcan_txn_a",
        schema_version=1,
    )
    entry_b = LockedGlossaryEntry(
        glossary_entry_id="glex_txn_b",
        release_id="m3-transaction",
        source_term="苍云门",
        normalized_source_term=normalize_term("苍云门"),
        target_term="Azure Sect",
        normalized_target_term=normalize_term("Azure Sect"),
        category="faction",
        status="approved",
        approved_at=approved_at,
        approval_run_id="promote-001",
        source_candidate_id="gcan_txn_b",
        schema_version=1,
    )

    with pytest.raises(sqlite3.IntegrityError):
        promote_locked_entries(conn, entries=[entry_a, entry_b])

    locked = list_locked_entries(conn, release_id="m3-transaction")
    assert locked == []
    conn.close()


def test_exact_match_precedence_over_fallback(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    config = load_config()
    paths = derive_paths(config, release_id="m3-precedence")
    conn = open_connection(paths.db_path)
    ensure_glossary_schema(conn)
    try:
        promote_locked_entries(
            conn,
            entries=[
                LockedGlossaryEntry(
                    glossary_entry_id="glex_precedence",
                    release_id="m3-precedence",
                    source_term="青云门",
                    normalized_source_term=normalize_term("青云门"),
                    target_term="Azure Sect",
                    normalized_target_term=normalize_term("Azure Sect"),
                    category="faction",
                    status="approved",
                    approved_at=datetime.now(UTC).isoformat(),
                    approval_run_id="promote-001",
                    source_candidate_id="gcan_precedence",
                    schema_version=1,
                )
            ],
        )
    finally:
        conn.close()

    resolved = resolve_locked_glossary_term(
        release_id="m3-precedence",
        source_term="青云门",
        category="faction",
        fallback_target_term="Fuzzy Candidate Name",
    )
    assert resolved == "Azure Sect"


def test_prompt_name_for_model() -> None:
    from resemantica.glossary.pipeline import _prompt_name_for_model

    # Default: HY-MT keeps the original prompt
    assert _prompt_name_for_model("HY-MT1.5-7B") == "glossary_translate.txt"

    # Gemma: gets model-specific prompt
    assert _prompt_name_for_model("Gemma-4-E4B-it-UD-Q6_K_XL") == "glossary_translate_gemma.txt"

    # Qwen: gets model-specific prompt
    assert _prompt_name_for_model("Qwopus3.5-9B") == "glossary_translate_qwen.txt"

    # Unknown model falls back to default
    assert _prompt_name_for_model("Some-Other-Model") == "glossary_translate.txt"
