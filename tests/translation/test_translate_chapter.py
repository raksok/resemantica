from __future__ import annotations

import json
import threading
import zipfile
from pathlib import Path

import pytest
from loguru import logger

from resemantica.epub.extractor import extract_epub
from resemantica.llm import budget as budget_mod
from resemantica.orchestration.stop import StopRequested, StopToken
from resemantica.settings import (
    AppConfig,
    BudgetConfig,
    LLMConfig,
    LLMThrottleGroupConfig,
    TranslationConfig,
    derive_paths,
)
from resemantica.tracking.repo import ensure_tracking_db, load_events
from resemantica.translation.pass2 import translate_pass2
from resemantica.translation.pipeline import (
    _split_for_retry,
    translate_chapter_pass1,
    translate_chapter_pass2,
)


def _write_fixture_epub(epub_path: Path, chapter_xhtml: str) -> None:
    workspace = epub_path.parent / "fixture_book_translation"
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


class ScriptedLLM:
    def __init__(self) -> None:
        self.pass1_calls = 0
        self.pass2_calls = 0
        self.fail_first_pass1 = False
        self.drop_placeholders = False

    def generate_text(self, *, model_name: str, prompt: str) -> str:  # noqa: ARG002
        if "PASS1" in prompt:
            self.pass1_calls += 1
            if self.fail_first_pass1 and self.pass1_calls <= 3:
                return ""
            if self.drop_placeholders and "⟦B_1⟧" in prompt:
                return "You good?"
            if "⟦B_1⟧" in prompt:
                return "You ⟦B_1⟧good⟦/B_1⟧?"
            return "Segment draft."

        if "translation auditor" in prompt:
            self.pass2_calls += 1
            if "⟦B_1⟧" in prompt:
                return json.dumps({
                    "fidelity_errors_found": True,
                    "analysis": "Missing word 'really'.",
                    "corrected_text": "You ⟦B_1⟧really good⟦/B_1⟧?"
                })
            return json.dumps({
                "fidelity_errors_found": False,
                "analysis": "No fidelity errors detected.",
                "corrected_text": "Segment corrected."
            })

        return "Unexpected."


class CountingPass1LLM:
    def __init__(self, responses_by_source: dict[str, list[str]]) -> None:
        self.responses_by_source = {key: iter(value) for key, value in responses_by_source.items()}
        self.pass1_prompts: list[str] = []

    def generate_text(self, *, model_name: str, prompt: str) -> str:  # noqa: ARG002
        self.pass1_prompts.append(prompt)
        for source, responses in self.responses_by_source.items():
            if source in prompt:
                return next(responses)
        raise AssertionError(f"Unexpected prompt: {prompt}")


class ScriptedPass2RetryLLM:
    def __init__(self, *, always_fail: bool = False) -> None:
        self.pass1_calls = 0
        self.placeholder_pass2_calls = 0
        self.plain_pass2_calls = 0
        self.always_fail = always_fail

    def generate_text(self, *, model_name: str, prompt: str) -> str:  # noqa: ARG002
        if "PASS1" in prompt:
            self.pass1_calls += 1
            if "⟦B_1⟧" in prompt:
                return "You ⟦B_1⟧good⟦/B_1⟧?"
            return "Plain draft."

        if "translation auditor" in prompt:
            if "⟦B_1⟧" in prompt:
                self.placeholder_pass2_calls += 1
                if self.always_fail or self.placeholder_pass2_calls == 1:
                    corrected = "You really good?"
                else:
                    corrected = "You ⟦B_1⟧really good⟦/B_1⟧?"
            else:
                self.plain_pass2_calls += 1
                corrected = "Plain draft."
            return json.dumps(
                {
                    "fidelity_errors_found": True,
                    "analysis": "scripted pass2 retry",
                    "corrected_text": corrected,
                }
            )

        return "Unexpected."


class ScriptedResegmentedPass2LLM:
    def __init__(self) -> None:
        self.segment_calls: list[str] = []

    def generate_text(self, *, model_name: str, prompt: str) -> str:  # noqa: ARG002
        if "translation auditor" not in prompt:
            return "Unexpected."
        if "segment-one-draft" in prompt:
            self.segment_calls.append("seg1")
            corrected = "Bad ⟦B_1⟧" if self.segment_calls.count("seg1") == 1 else "Segment one. "
        elif "segment-two-draft" in prompt:
            self.segment_calls.append("seg2")
            corrected = "Segment two."
        else:
            corrected = "Unexpected segment."
        return json.dumps(
            {
                "fidelity_errors_found": True,
                "analysis": "scripted resegmented pass2 retry",
                "corrected_text": corrected,
            }
        )


class MixedLanguageHandoffLLM:
    def __init__(self, *, pass2_responses: list[str]) -> None:
        self.pass1_calls = 0
        self.pass2_responses = iter(pass2_responses)
        self.pass2_calls = 0
        self.pass2_prompts: list[str] = []

    def generate_text(self, *, model_name: str, prompt: str) -> str:  # noqa: ARG002
        if "translation auditor" in prompt:
            self.pass2_calls += 1
            self.pass2_prompts.append(prompt)
            return next(self.pass2_responses)
        self.pass1_calls += 1
        return "Mao Xiaodong spoke of the 桐叶 Continent."


def _extract_one_chapter(tmp_path: Path, chapter_xhtml: str, release_id: str) -> None:
    input_epub = tmp_path / f"{release_id}.epub"
    _write_fixture_epub(input_epub, chapter_xhtml)
    result = extract_epub(input_path=input_epub, release_id=release_id)
    assert result.status == "success"


def test_pass1_stop_persists_completed_block_and_resume_reuses_it(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m81-pass1-stop"
    run_id = "run-001"
    _extract_one_chapter(
        tmp_path,
        """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body>
<p>第一段。</p><p>第二段。</p>
</body></html>
""",
        release_id,
    )
    token = StopToken()

    class StopAfterFirst:
        def __init__(self) -> None:
            self.calls = 0

        def generate_text(self, *, model_name: str, prompt: str) -> str:  # noqa: ARG002
            self.calls += 1
            token.request_stop()
            return "First paragraph."

    stopping_client = StopAfterFirst()
    with pytest.raises(StopRequested) as stopped:
        translate_chapter_pass1(
            release_id=release_id,
            chapter_number=1,
            run_id=run_id,
            llm_client=stopping_client,
            stop_token=token,
        )

    assert stopped.value.interrupt_report is not None
    assert stopped.value.interrupt_report.completed_count == 1
    paths = derive_paths(AppConfig(), release_id=release_id)
    artifact_path = paths.release_root / "runs" / run_id / "translation" / "chapter-1" / "pass1.json"
    stopped_payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert stopped_payload["status"] == "stopped"
    assert len(stopped_payload["blocks"]) == 1
    conn = ensure_tracking_db(release_id)
    try:
        event_types = [
            event.event_type
            for event in load_events(conn, run_id=run_id, release_id=release_id)
        ]
    finally:
        conn.close()
    assert "translate-chapter.pass1.failed" not in event_types

    class ResumeClient:
        def __init__(self) -> None:
            self.calls = 0

        def generate_text(self, *, model_name: str, prompt: str) -> str:  # noqa: ARG002
            self.calls += 1
            return "Second paragraph."

    resume_client = ResumeClient()
    resumed = translate_chapter_pass1(
        release_id=release_id,
        chapter_number=1,
        run_id=run_id,
        llm_client=resume_client,
    )

    assert resumed["status"] == "success"
    assert resume_client.calls == 1
    assert len(resumed["blocks"]) == 2


def test_pass2_stop_drains_active_unit_and_cancels_remaining_unit(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m81-pass2-stop"
    run_id = "run-001"
    _extract_one_chapter(
        tmp_path,
        """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body>
<p>第一段。</p><p>第二段。</p>
</body></html>
""",
        release_id,
    )
    config = _retry_test_config(retries=0)
    translate_chapter_pass1(
        release_id=release_id,
        chapter_number=1,
        run_id=run_id,
        config=config,
        llm_client=ScriptedLLM(),
    )

    started = threading.Event()
    release = threading.Event()
    token = StopToken()

    class BlockingPass2:
        def __init__(self) -> None:
            self.calls = 0

        def generate_text(self, *, model_name: str, prompt: str) -> str:  # noqa: ARG002
            self.calls += 1
            started.set()
            assert release.wait(timeout=5)
            return json.dumps(
                {
                    "fidelity_errors_found": False,
                    "analysis": "No fidelity errors.",
                    "corrected_text": "Segment draft.",
                }
            )

    client = BlockingPass2()
    errors: list[BaseException] = []

    def run_pass2() -> None:
        try:
            translate_chapter_pass2(
                release_id=release_id,
                chapter_number=1,
                run_id=run_id,
                config=config,
                llm_client=client,
                stop_token=token,
            )
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=run_pass2)
    thread.start()
    assert started.wait(timeout=5)
    token.request_stop()
    release.set()
    thread.join(timeout=5)

    assert not thread.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], StopRequested)
    report = errors[0].interrupt_report
    assert report is not None
    assert report.drained_count == 1
    assert report.canceled_count == 1
    assert client.calls == 1
    paths = derive_paths(config, release_id=release_id)
    artifact_path = paths.release_root / "runs" / run_id / "translation" / "chapter-1" / "pass2.json"
    stopped_payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert stopped_payload["status"] == "stopped"
    assert len(stopped_payload["blocks"]) == 1
    conn = ensure_tracking_db(release_id)
    try:
        event_types = [
            event.event_type
            for event in load_events(conn, run_id=run_id, release_id=release_id)
        ]
    finally:
        conn.close()
    assert "translate-chapter.pass2.failed" not in event_types


def _retry_test_config(*, retries: int) -> AppConfig:
    return AppConfig(
        translation=TranslationConfig(
            pass2_concurrency=1,
            pass2_batch_max_blocks=1,
            pass2_validation_retries=retries,
        )
    )


def _manual_pass2_config(
    *,
    batch_max_blocks: int = 8,
    max_context_per_pass: int = 49152,
) -> AppConfig:
    return AppConfig(
        budget=BudgetConfig(max_context_per_pass=max_context_per_pass),
        translation=TranslationConfig(
            pass2_concurrency=1,
            pass2_batch_max_blocks=batch_max_blocks,
            pass2_validation_retries=1,
        ),
    )


def _write_pass1_artifact(
    *,
    config: AppConfig,
    release_id: str,
    run_id: str,
    blocks: list[dict[str, object]],
) -> None:
    paths = derive_paths(config, release_id=release_id)
    translation_dir = paths.release_root / "runs" / run_id / "translation" / "chapter-1"
    translation_dir.mkdir(parents=True, exist_ok=True)
    (translation_dir / "pass1.json").write_text(
        json.dumps(
            {
                "release_id": release_id,
                "run_id": run_id,
                "chapter_number": 1,
                "pass_name": "pass1",
                "model_name": "model",
                "prompt_version": "test",
                "source_hash": "hash",
                "status": "success",
                "blocks": blocks,
                "structure_validation": [],
            }
        ),
        encoding="utf-8",
    )


def _normal_pass1_block(index: int, *, draft_text: str | None = None) -> dict[str, object]:
    block_id = f"ch001_blk{index:03d}"
    return {
        "block_id": block_id,
        "parent_block_id": block_id,
        "source_text_zh": f"源文本{index}。",
        "draft_text": draft_text or f"Draft {index}.",
        "restored_text": draft_text or f"Draft {index}.",
        "was_resegmented": False,
        "segments": [],
    }


class BatchPass2LLM:
    def __init__(
        self,
        *,
        batch_response: str | None = None,
        invalid_block_id: str | None = None,
        repair_mixed_single: bool = False,
    ) -> None:
        self.batch_response = batch_response
        self.invalid_block_id = invalid_block_id
        self.repair_mixed_single = repair_mixed_single
        self.batch_calls = 0
        self.single_calls = 0
        self.batch_block_counts: list[int] = []
        self.single_prompts: list[str] = []

    def generate_text(self, *, model_name: str, prompt: str) -> str:  # noqa: ARG002
        if "INPUT_BATCH_JSON" in prompt:
            self.batch_calls += 1
            if self.batch_response is not None:
                return self.batch_response
            payload = json.loads(prompt.rsplit("## INPUT_BATCH_JSON", 1)[1].strip())
            blocks = payload["blocks"]
            self.batch_block_counts.append(len(blocks))
            results = []
            for block in blocks:
                block_id = str(block["block_id"])
                if block_id == self.invalid_block_id:
                    results.append(
                        {
                            "block_id": block_id,
                            "fidelity_errors_found": True,
                            "corrected_text": "",
                        }
                    )
                else:
                    results.append(
                        {
                            "block_id": block_id,
                            "fidelity_errors_found": False,
                            "corrected_text": "",
                        }
                    )
            return json.dumps({"results": results})

        if "translation auditor" in prompt:
            self.single_calls += 1
            self.single_prompts.append(prompt)
            if self.repair_mixed_single and "桐叶" in prompt:
                return json.dumps(
                    {
                        "fidelity_errors_found": True,
                        "corrected_text": "Parasol Leaf draft.",
                    }
                )
            return json.dumps({"fidelity_errors_found": False, "corrected_text": ""})
        return "Unexpected."


def test_placeholder_preservation_and_pass2_correction(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _extract_one_chapter(
        tmp_path,
        """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body><p>你<b>好</b>吗？</p></body></html>
""",
        "m2-placeholder",
    )

    client = ScriptedLLM()
    translate_chapter_pass1(
        release_id="m2-placeholder",
        chapter_number=1,
        run_id="run-001",
        llm_client=client,
    )
    r2 = translate_chapter_pass2(
        release_id="m2-placeholder",
        chapter_number=1,
        run_id="run-001",
        llm_client=client,
    )
    assert r2["status"] == "success"

    pass2_artifact = json.loads(Path(r2["pass2_artifact"]).read_text(encoding="utf-8"))
    block = pass2_artifact["blocks"][0]
    assert block["output_text_en"] == "You ⟦B_1⟧really good⟦/B_1⟧?"
    assert "<b>really good</b>" in block["restored_text_en"]


@pytest.mark.parametrize("source", ["……", "⟦B_1⟧⟦/B_1⟧"])
def test_pass1_symbol_or_placeholder_only_block_is_exact_passthrough(
    tmp_path: Path,
    monkeypatch,
    source: str,
) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m76-pass1-passthrough"
    _extract_one_chapter(
        tmp_path,
        f'''<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body><p>{source}</p></body></html>
''',
        release_id,
    )
    client = CountingPass1LLM({})

    result = translate_chapter_pass1(
        release_id=release_id,
        chapter_number=1,
        run_id="run-001",
        llm_client=client,  # type: ignore[arg-type]
    )

    assert result["status"] == "success"
    assert client.pass1_prompts == []
    assert result["blocks"][0]["draft_text"] == source
    assert result["blocks"][0]["status"] == "success"
    pass2 = translate_chapter_pass2(
        release_id=release_id,
        chapter_number=1,
        run_id="run-001",
        llm_client=client,  # type: ignore[arg-type]
    )
    assert client.pass1_prompts == []
    assert pass2["blocks"][0]["output_text_en"] == source


def test_failed_pass1_artifact_resumes_only_failed_blocks(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m76-pass1-resume"
    run_id = "run-001"
    _extract_one_chapter(
        tmp_path,
        '''<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body><p>第一段。</p><p>第二段。</p></body></html>
''',
        release_id,
    )
    first_client = CountingPass1LLM(
        {"第一段。": ["First paragraph."], "第二段。": ["", "中文", "仍是中文"]}
    )
    first = translate_chapter_pass1(
        release_id=release_id,
        chapter_number=1,
        run_id=run_id,
        llm_client=first_client,  # type: ignore[arg-type]
    )
    assert first["status"] == "failed"
    failed_block = first["blocks"][1]
    assert failed_block["status"] == "failed"
    assert failed_block["was_resegmented"] is False
    assert failed_block["errors"] == [
        "Candidate output contains untranslated Chinese spans: 仍是中文."
    ]

    repair_client = CountingPass1LLM({"第二段。": ["Second paragraph."]})
    repaired = translate_chapter_pass1(
        release_id=release_id,
        chapter_number=1,
        run_id=run_id,
        llm_client=repair_client,  # type: ignore[arg-type]
    )

    assert repaired["status"] == "success"
    assert len(repair_client.pass1_prompts) == 1
    assert [block["draft_text"] for block in repaired["blocks"]] == [
        "First paragraph.",
        "Second paragraph.",
    ]


def test_hard_stop_on_placeholder_structural_failure(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _extract_one_chapter(
        tmp_path,
        """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body><p>你<b>好</b>吗？</p></body></html>
""",
        "m2-failure",
    )

    client = ScriptedLLM()
    client.drop_placeholders = True

    r1 = translate_chapter_pass1(
        release_id="m2-failure",
        chapter_number=1,
        run_id="run-001",
        llm_client=client,
    )
    assert r1["status"] == "failed"
    assert r1["blocks"][0]["was_resegmented"] is False
    assert r1["blocks"][0]["status"] == "failed"

    with pytest.raises(RuntimeError, match="Pass 1 is incomplete"):
        translate_chapter_pass2(
            release_id="m2-failure",
            chapter_number=1,
            run_id="run-001",
            llm_client=client,
        )


def test_reactive_resegmentation_on_long_structural_failure(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    long_text = "这是一个很长的句子。" * 220
    _extract_one_chapter(
        tmp_path,
        f"""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body><p>{long_text}</p></body></html>
""",
        "m2-resegment",
    )

    client = ScriptedLLM()
    client.fail_first_pass1 = True
    r1 = translate_chapter_pass1(
        release_id="m2-resegment",
        chapter_number=1,
        run_id="run-001",
        llm_client=client,
    )
    pass1_artifact = json.loads(Path(r1["pass1_artifact"]).read_text(encoding="utf-8"))
    first_block = pass1_artifact["blocks"][0]
    assert first_block["was_resegmented"] is True
    assert len(first_block["segments"]) >= 2
    assert (
        "".join(segment["source_text_zh"] for segment in first_block["segments"])
        == first_block["source_text_zh"]
    )


def test_split_for_retry_forces_short_block_at_safe_boundary() -> None:
    source = "甲甲甲，乙乙乙乙，丙丙。"

    segments = _split_for_retry(source, max_chars=750, force=True)

    assert len(segments) == 2
    assert segments[0][-1] in "，,；;：:。！？!?."
    assert "".join(segments) == source


def test_short_pass1_failure_recovers_with_clause_resegmentation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m78-short-pass1-resegment"
    source = (
        "陈平安见钱袋子和铜钱应该真没有什么玄机，反而心情好转几分，犹豫了一下，"
        "没有放入地盘更大的咫尺物，而是收起来放入方寸物飞剑十五当中，"
        "陈平安笑着揉了揉裴钱的小脑袋，黑炭小丫头笑眯起眼。"
    )
    _extract_one_chapter(
        tmp_path,
        f'''<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body><p>{source}</p></body></html>
''',
        release_id,
    )
    retry_segments = _split_for_retry(source, max_chars=750, force=True)
    assert len(retry_segments) == 2
    client = CountingPass1LLM(
        {
            source: ["", "", ""],
            retry_segments[0]: ["Recovered first clause."],
            retry_segments[1]: ["Recovered second clause."],
        }
    )
    events: list[dict[str, object]] = []
    monkeypatch.setattr(
        "resemantica.translation.pipeline._emit_translation_event",
        lambda **kwargs: events.append(kwargs),
    )

    result = translate_chapter_pass1(
        release_id=release_id,
        chapter_number=1,
        run_id="run-001",
        llm_client=client,  # type: ignore[arg-type]
    )

    assert result["status"] == "success"
    assert len(client.pass1_prompts) == 5
    block = result["blocks"][0]
    assert block["status"] == "success"
    assert block["was_resegmented"] is True
    assert [segment["draft_text"] for segment in block["segments"]] == [
        "Recovered first clause.",
        "Recovered second clause.",
    ]
    assert "".join(segment["source_text_zh"] for segment in block["segments"]) == source
    retry_event = next(event for event in events if event["event_type"] == "paragraph_retry")
    assert retry_event["block_id"] == "ch001_blk001"
    assert retry_event["payload"] == {
        "segment_count": 2,
        "pass_name": "pass1",
    }


def test_mixed_language_pass1_candidate_recovers_without_resegmentation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m79-mixed-language-repair"
    source = (
        "茅小冬哈哈笑道：“可你以为宝瓶洲的上五境修士，是裴钱和李槐收藏的那些小玩意儿，"
        "随随便便就能拿出来显摆？大隋唯一一位玉璞境，是位戈阳高氏的老祖宗，"
        "还是个不擅长厮杀的说书先生，早已经去了你家乡的披云山。"
        "加上如今那位桐叶洲飞升境大修士身死道消。”"
    )
    mixed_candidate = (
        "Mao Xiaodong laughed heartily. The great cultivator from the桐叶 Continent "
        "had already passed away."
    )
    repaired_candidate = (
        "Mao Xiaodong laughed heartily. The great cultivator from the Parasol Leaf "
        "Continent had already passed away."
    )
    _extract_one_chapter(
        tmp_path,
        f'''<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body><p>{source}</p></body></html>
''',
        release_id,
    )
    client = CountingPass1LLM({source: [mixed_candidate, repaired_candidate]})

    result = translate_chapter_pass1(
        release_id=release_id,
        chapter_number=1,
        run_id="run-001",
        llm_client=client,  # type: ignore[arg-type]
    )

    assert result["status"] == "success"
    assert len(client.pass1_prompts) == 2
    assert mixed_candidate in client.pass1_prompts[1]
    assert "桐叶" in client.pass1_prompts[1]
    block = result["blocks"][0]
    assert block["status"] == "success"
    assert block["was_resegmented"] is False
    assert block["draft_text"] == repaired_candidate


def test_exhausted_mixed_pass1_candidate_is_repaired_by_pass2(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m80-mixed-language-handoff"
    source = "茅小冬提到了桐叶洲。"
    _extract_one_chapter(
        tmp_path,
        f'''<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body><p>{source}</p></body></html>
''',
        release_id,
    )
    corrected = "Mao Xiaodong spoke of the Parasol Leaf Continent."
    client = MixedLanguageHandoffLLM(
        pass2_responses=[
            json.dumps(
                {
                    "fidelity_errors_found": True,
                    "corrected_text": "Mao Xiaodong spoke of the 桐叶 Continent.",
                }
            ),
            json.dumps(
                {
                    "fidelity_errors_found": True,
                    "corrected_text": corrected,
                }
            ),
        ]
    )
    config = _retry_test_config(retries=1)

    pass1 = translate_chapter_pass1(
        release_id=release_id,
        chapter_number=1,
        run_id="run-001",
        config=config,
        llm_client=client,  # type: ignore[arg-type]
    )

    assert pass1["status"] == "success"
    assert client.pass1_calls == 3
    block = pass1["blocks"][0]
    assert block["status"] == "success"
    assert block["was_resegmented"] is False
    assert block["draft_text"] == "Mao Xiaodong spoke of the 桐叶 Continent."
    assert block["untranslated_chinese_spans"] == ["桐叶"]
    pass1_artifact = json.loads(Path(pass1["pass1_artifact"]).read_text(encoding="utf-8"))
    assert pass1_artifact["structure_validation"][0]["warnings"] == [
        "Deferred untranslated Chinese spans to Pass 2: 桐叶."
    ]

    pass2 = translate_chapter_pass2(
        release_id=release_id,
        chapter_number=1,
        run_id="run-001",
        config=config,
        llm_client=client,  # type: ignore[arg-type]
    )

    assert pass2["status"] == "success"
    assert pass2["blocks"][0]["output_text_en"] == corrected
    assert client.pass2_calls == 2
    assert all("untranslated Chinese" in prompt for prompt in client.pass2_prompts)


def test_pass2_fails_when_mixed_output_survives_validation_retries(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m80-mixed-language-exhausted"
    source = "茅小冬提到了桐叶洲。"
    _extract_one_chapter(
        tmp_path,
        f'''<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body><p>{source}</p></body></html>
''',
        release_id,
    )
    mixed_response = json.dumps(
        {
            "fidelity_errors_found": False,
            "corrected_text": "",
        }
    )
    client = MixedLanguageHandoffLLM(pass2_responses=[mixed_response, mixed_response])
    config = _retry_test_config(retries=1)
    translate_chapter_pass1(
        release_id=release_id,
        chapter_number=1,
        run_id="run-001",
        config=config,
        llm_client=client,  # type: ignore[arg-type]
    )

    with pytest.raises(RuntimeError, match="Pass 2 failed validation"):
        translate_chapter_pass2(
            release_id=release_id,
            chapter_number=1,
            run_id="run-001",
            config=config,
            llm_client=client,  # type: ignore[arg-type]
        )

    assert client.pass2_calls == 2
    paths = derive_paths(config, release_id=release_id)
    artifact = json.loads(
        (
            paths.release_root
            / "runs"
            / "run-001"
            / "translation"
            / "chapter-1"
            / "pass2.json"
        ).read_text(encoding="utf-8")
    )
    assert artifact["fidelity_validation"][0]["errors"] == [
        "Translated output contains untranslated Chinese spans: 桐叶."
    ]


def test_failed_resegmentation_reports_child_errors(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m79-resegmentation-errors"
    source = "甲甲甲，乙乙乙乙，丙丙。"
    _extract_one_chapter(
        tmp_path,
        f'''<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body><p>{source}</p></body></html>
''',
        release_id,
    )
    segments = _split_for_retry(source, max_chars=750, force=True)
    client = CountingPass1LLM(
        {
            source: ["", "", ""],
            segments[0]: ["", "", ""],
            segments[1]: ["", "", ""],
        }
    )

    result = translate_chapter_pass1(
        release_id=release_id,
        chapter_number=1,
        run_id="run-001",
        llm_client=client,  # type: ignore[arg-type]
    )

    assert result["status"] == "failed"
    assert result["blocks"][0]["errors"] == [
        "ch001_blk001_seg01: Candidate output is empty.",
        "ch001_blk001_seg02: Candidate output is empty.",
    ]


def test_pass2_retries_structural_failure_for_one_block(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m74-pass2-retry"
    run_id = "run-001"
    _extract_one_chapter(
        tmp_path,
        """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body>
<p>你<b>好</b>吗？</p>
<p>普通文本。</p>
</body></html>
""",
        release_id,
    )

    client = ScriptedPass2RetryLLM()
    config = _retry_test_config(retries=2)
    translate_chapter_pass1(
        release_id=release_id,
        chapter_number=1,
        run_id=run_id,
        llm_client=client,
        config=config,
    )
    result = translate_chapter_pass2(
        release_id=release_id,
        chapter_number=1,
        run_id=run_id,
        llm_client=client,
        config=config,
    )

    assert result["status"] == "success"
    assert client.placeholder_pass2_calls == 2
    assert client.plain_pass2_calls == 1

    from resemantica.tracking.repo import ensure_tracking_db, load_events

    conn = ensure_tracking_db(release_id)
    try:
        events = load_events(conn, run_id=run_id, release_id=release_id, limit=100)
    finally:
        conn.close()
    retries = [event for event in events if event.event_type == "translate-chapter.pass2.retry"]
    assert len(retries) == 1
    assert retries[0].payload["reason"] == "structural_validation_failed"


def test_pass2_retry_exhaustion_fails_chapter(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m74-pass2-retry-exhausted"
    run_id = "run-001"
    _extract_one_chapter(
        tmp_path,
        """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body><p>你<b>好</b>吗？</p></body></html>
""",
        release_id,
    )

    client = ScriptedPass2RetryLLM(always_fail=True)
    config = _retry_test_config(retries=1)
    translate_chapter_pass1(
        release_id=release_id,
        chapter_number=1,
        run_id=run_id,
        llm_client=client,
        config=config,
    )
    with pytest.raises(RuntimeError, match="Pass 2 structural validation failed"):
        translate_chapter_pass2(
            release_id=release_id,
            chapter_number=1,
            run_id=run_id,
            llm_client=client,
            config=config,
        )

    assert client.placeholder_pass2_calls == 2


def test_pass2_zero_validation_retries_preserves_immediate_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m74-pass2-no-retry"
    run_id = "run-001"
    _extract_one_chapter(
        tmp_path,
        """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body><p>你<b>好</b>吗？</p></body></html>
""",
        release_id,
    )

    client = ScriptedPass2RetryLLM(always_fail=True)
    config = _retry_test_config(retries=0)
    translate_chapter_pass1(
        release_id=release_id,
        chapter_number=1,
        run_id=run_id,
        llm_client=client,
        config=config,
    )
    with pytest.raises(RuntimeError, match="Pass 2 structural validation failed"):
        translate_chapter_pass2(
            release_id=release_id,
            chapter_number=1,
            run_id=run_id,
            llm_client=client,
            config=config,
        )

    assert client.placeholder_pass2_calls == 1


def test_pass2_repairs_only_missing_cached_blocks(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m76-pass2-repair"
    run_id = "run-001"
    _extract_one_chapter(
        tmp_path,
        '''<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body><p>第一段。</p><p>第二段。</p></body></html>
''',
        release_id,
    )
    config = _manual_pass2_config(batch_max_blocks=1)
    translate_chapter_pass1(
        release_id=release_id,
        chapter_number=1,
        run_id=run_id,
        config=config,
        llm_client=ScriptedLLM(),
    )
    first_client = BatchPass2LLM()
    first = translate_chapter_pass2(
        release_id=release_id,
        chapter_number=1,
        run_id=run_id,
        config=config,
        llm_client=first_client,  # type: ignore[arg-type]
    )
    artifact_path = Path(first["pass2_artifact"])
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    preserved = payload["blocks"][0]
    payload["blocks"] = [preserved]
    artifact_path.write_text(json.dumps(payload), encoding="utf-8")

    repair_client = BatchPass2LLM()
    repaired = translate_chapter_pass2(
        release_id=release_id,
        chapter_number=1,
        run_id=run_id,
        config=config,
        llm_client=repair_client,  # type: ignore[arg-type]
    )

    assert repaired["status"] == "success"
    assert repair_client.single_calls == 1
    assert len(repaired["blocks"]) == 2
    assert repaired["blocks"][0] == preserved


def test_pass2_rejects_extra_cached_block_mapping(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m76-pass2-extra"
    run_id = "run-001"
    _extract_one_chapter(
        tmp_path,
        '''<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body><p>正文。</p></body></html>
''',
        release_id,
    )
    config = _manual_pass2_config(batch_max_blocks=1)
    translate_chapter_pass1(
        release_id=release_id,
        chapter_number=1,
        run_id=run_id,
        config=config,
        llm_client=ScriptedLLM(),
    )
    first = translate_chapter_pass2(
        release_id=release_id,
        chapter_number=1,
        run_id=run_id,
        config=config,
        llm_client=BatchPass2LLM(),  # type: ignore[arg-type]
    )
    artifact_path = Path(first["pass2_artifact"])
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    payload["blocks"].append({**payload["blocks"][0], "block_id": "unexpected"})
    artifact_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(RuntimeError, match="extra block mappings"):
        translate_chapter_pass2(
            release_id=release_id,
            chapter_number=1,
            run_id=run_id,
            config=config,
            llm_client=BatchPass2LLM(),  # type: ignore[arg-type]
        )


def test_pass2_resegmented_block_retry_preserves_segment_order(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m74-pass2-resegmented-retry"
    run_id = "run-001"
    _extract_one_chapter(
        tmp_path,
        """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body><p>第一段。第二段。</p></body></html>
""",
        release_id,
    )
    config = _retry_test_config(retries=1)
    paths = derive_paths(config, release_id=release_id)
    translation_dir = paths.release_root / "runs" / run_id / "translation" / "chapter-1"
    translation_dir.mkdir(parents=True, exist_ok=True)
    (translation_dir / "pass1.json").write_text(
        json.dumps(
            {
                "release_id": release_id,
                "run_id": run_id,
                "chapter_number": 1,
                "pass_name": "pass1",
                "model_name": "model",
                "prompt_version": "test",
                "source_hash": "hash",
                "status": "success",
                "blocks": [
                    {
                        "block_id": "ch001_blk001",
                        "parent_block_id": "ch001_blk001",
                        "source_text_zh": "第一段。第二段。",
                        "was_resegmented": True,
                        "segments": [
                            {
                                "segment_id": "ch001_blk001_seg01",
                                "source_text_zh": "第一段。",
                                "draft_text": "segment-one-draft",
                            },
                            {
                                "segment_id": "ch001_blk001_seg02",
                                "source_text_zh": "第二段。",
                                "draft_text": "segment-two-draft",
                            },
                        ],
                    }
                ],
                "structure_validation": [],
            }
        ),
        encoding="utf-8",
    )

    client = ScriptedResegmentedPass2LLM()
    result = translate_chapter_pass2(
        release_id=release_id,
        chapter_number=1,
        run_id=run_id,
        llm_client=client,
        config=config,
    )

    assert result["status"] == "success"
    assert client.segment_calls == ["seg1", "seg1", "seg2"]
    pass2_artifact = json.loads(Path(result["pass2_artifact"]).read_text(encoding="utf-8"))
    assert pass2_artifact["blocks"][0]["output_text_en"] == "Segment one. Segment two."


def test_pass2_batches_multiple_normal_blocks_and_preserves_order(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m75-pass2-batch"
    run_id = "run-001"
    config = _manual_pass2_config(batch_max_blocks=8)
    _extract_one_chapter(
        tmp_path,
        """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body>
<p>甲。</p><p>乙。</p><p>丙。</p>
</body></html>
""",
        release_id,
    )
    _write_pass1_artifact(
        config=config,
        release_id=release_id,
        run_id=run_id,
        blocks=[_normal_pass1_block(1), _normal_pass1_block(2), _normal_pass1_block(3)],
    )

    client = BatchPass2LLM()
    result = translate_chapter_pass2(
        release_id=release_id,
        chapter_number=1,
        run_id=run_id,
        llm_client=client,
        config=config,
    )

    assert client.batch_calls == 1
    assert client.single_calls == 0
    assert [block["block_id"] for block in result["blocks"]] == [
        "ch001_blk001",
        "ch001_blk002",
        "ch001_blk003",
    ]
    assert [block["output_text_en"] for block in result["blocks"]] == [
        "Draft 1.",
        "Draft 2.",
        "Draft 3.",
    ]
    artifact = json.loads(Path(result["pass2_artifact"]).read_text(encoding="utf-8"))
    assert artifact["batching"]["batches_attempted"] == 1
    assert artifact["batching"]["batch_fallbacks"] == 0


def test_pass2_batch_packing_splits_at_max_blocks(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m75-pass2-batch-max"
    run_id = "run-001"
    config = _manual_pass2_config(batch_max_blocks=2)
    _extract_one_chapter(
        tmp_path,
        """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body>
<p>甲。</p><p>乙。</p><p>丙。</p>
</body></html>
""",
        release_id,
    )
    _write_pass1_artifact(
        config=config,
        release_id=release_id,
        run_id=run_id,
        blocks=[_normal_pass1_block(1), _normal_pass1_block(2), _normal_pass1_block(3)],
    )

    client = BatchPass2LLM()
    translate_chapter_pass2(
        release_id=release_id,
        chapter_number=1,
        run_id=run_id,
        llm_client=client,
        config=config,
    )

    assert client.batch_calls == 2
    assert client.batch_block_counts == [2, 1]


def test_pass2_batch_packing_splits_before_prompt_budget_with_system_prompt(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        budget_mod,
        "count_tokens",
        lambda text: text.count("ch001_blk") * 100 + (50 if text.startswith("SYS") else 0),
    )
    release_id = "m75-pass2-batch-budget"
    run_id = "run-001"
    config = AppConfig(
        budget=BudgetConfig(max_context_per_pass=200),
        llm=LLMConfig(
            throttle_groups={
                "qwen": LLMThrottleGroupConfig(
                    model_names=["Qwen3.5-9B-GLM5.1"],
                    max_concurrent_requests=1,
                    system_prompt="SYS",
                )
            }
        ),
        translation=TranslationConfig(
            pass2_concurrency=1,
            pass2_batch_max_blocks=8,
            pass2_validation_retries=1,
        ),
    )
    _extract_one_chapter(
        tmp_path,
        """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body>
<p>甲。</p><p>乙。</p><p>丙。</p>
</body></html>
""",
        release_id,
    )
    _write_pass1_artifact(
        config=config,
        release_id=release_id,
        run_id=run_id,
        blocks=[_normal_pass1_block(1), _normal_pass1_block(2), _normal_pass1_block(3)],
    )

    client = BatchPass2LLM()
    translate_chapter_pass2(
        release_id=release_id,
        chapter_number=1,
        run_id=run_id,
        llm_client=client,
        config=config,
    )

    assert client.batch_block_counts == [1, 1, 1]


def test_pass2_invalid_batch_json_falls_back_to_single_blocks(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m75-pass2-batch-invalid-json"
    run_id = "run-001"
    config = _manual_pass2_config(batch_max_blocks=8)
    _extract_one_chapter(
        tmp_path,
        """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body><p>甲。</p><p>乙。</p></body></html>
""",
        release_id,
    )
    _write_pass1_artifact(
        config=config,
        release_id=release_id,
        run_id=run_id,
        blocks=[_normal_pass1_block(1), _normal_pass1_block(2)],
    )

    client = BatchPass2LLM(batch_response="not json")
    result = translate_chapter_pass2(
        release_id=release_id,
        chapter_number=1,
        run_id=run_id,
        llm_client=client,
        config=config,
    )

    assert result["status"] == "success"
    assert client.batch_calls == 1
    assert client.single_calls == 2
    artifact = json.loads(Path(result["pass2_artifact"]).read_text(encoding="utf-8"))
    assert artifact["batching"]["batch_fallbacks"] == 1
    assert artifact["batching"]["batch_fallback_blocks"] == 2


def test_pass2_invalid_batch_result_falls_back_only_affected_block(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m75-pass2-batch-one-invalid"
    run_id = "run-001"
    config = _manual_pass2_config(batch_max_blocks=8)
    _extract_one_chapter(
        tmp_path,
        """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body><p>甲。</p><p>乙。</p></body></html>
""",
        release_id,
    )
    _write_pass1_artifact(
        config=config,
        release_id=release_id,
        run_id=run_id,
        blocks=[_normal_pass1_block(1), _normal_pass1_block(2)],
    )

    client = BatchPass2LLM(invalid_block_id="ch001_blk002")
    result = translate_chapter_pass2(
        release_id=release_id,
        chapter_number=1,
        run_id=run_id,
        llm_client=client,
        config=config,
    )

    assert result["status"] == "success"
    assert client.batch_calls == 1
    assert client.single_calls == 1
    assert "源文本2" in client.single_prompts[0]
    artifact = json.loads(Path(result["pass2_artifact"]).read_text(encoding="utf-8"))
    assert artifact["batching"]["batch_fallback_blocks"] == 1


def test_pass2_batch_mixed_draft_falls_back_only_affected_block(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m80-pass2-batch-mixed"
    run_id = "run-001"
    config = _manual_pass2_config(batch_max_blocks=8)
    _extract_one_chapter(
        tmp_path,
        """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body><p>甲。</p><p>乙。</p></body></html>
""",
        release_id,
    )
    mixed_draft = "Mostly English with 桐叶 left."
    _write_pass1_artifact(
        config=config,
        release_id=release_id,
        run_id=run_id,
        blocks=[
            _normal_pass1_block(1, draft_text=mixed_draft),
            _normal_pass1_block(2),
        ],
    )

    client = BatchPass2LLM(repair_mixed_single=True)
    result = translate_chapter_pass2(
        release_id=release_id,
        chapter_number=1,
        run_id=run_id,
        llm_client=client,
        config=config,
    )

    assert result["status"] == "success"
    assert client.batch_calls == 1
    assert client.single_calls == 1
    assert mixed_draft in client.single_prompts[0]
    assert [block["output_text_en"] for block in result["blocks"]] == [
        "Parasol Leaf draft.",
        "Draft 2.",
    ]
    artifact = json.loads(Path(result["pass2_artifact"]).read_text(encoding="utf-8"))
    assert artifact["batching"]["batch_fallback_blocks"] == 1


def test_pass2_batch_max_blocks_one_uses_existing_single_block_path(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    release_id = "m75-pass2-batch-off"
    run_id = "run-001"
    config = _manual_pass2_config(batch_max_blocks=1)
    _extract_one_chapter(
        tmp_path,
        """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body><p>甲。</p><p>乙。</p></body></html>
""",
        release_id,
    )
    _write_pass1_artifact(
        config=config,
        release_id=release_id,
        run_id=run_id,
        blocks=[_normal_pass1_block(1), _normal_pass1_block(2)],
    )

    client = BatchPass2LLM()
    translate_chapter_pass2(
        release_id=release_id,
        chapter_number=1,
        run_id=run_id,
        llm_client=client,
        config=config,
    )

    assert client.batch_calls == 0
    assert client.single_calls == 2


def test_resume_from_successful_pass1_skips_pass1(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _extract_one_chapter(
        tmp_path,
        """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body><p>普通文本。</p></body></html>
""",
        "m2-resume",
    )

    first_client = ScriptedLLM()
    translate_chapter_pass1(
        release_id="m2-resume",
        chapter_number=1,
        run_id="run-001",
        llm_client=first_client,
    )
    r1p2 = translate_chapter_pass2(
        release_id="m2-resume",
        chapter_number=1,
        run_id="run-001",
        llm_client=first_client,
    )
    assert r1p2["status"] == "success"
    assert first_client.pass1_calls > 0

    second_client = ScriptedLLM()
    translate_chapter_pass1(
        release_id="m2-resume",
        chapter_number=1,
        run_id="run-001",
        llm_client=second_client,
    )
    r2p2 = translate_chapter_pass2(
        release_id="m2-resume",
        chapter_number=1,
        run_id="run-001",
        llm_client=second_client,
    )
    assert r2p2["status"] == "success"
    assert second_client.pass1_calls == 0


class MockLLMClient:
    def __init__(self, response: str) -> None:
        self.response = response

    def generate_text(self, *, model_name: str, prompt: str) -> str:
        return self.response


def test_pass2_no_fidelity_errors_returns_original_draft() -> None:
    client = MockLLMClient(json.dumps({
        "fidelity_errors_found": False,
        "analysis": "No fidelity errors detected.",
        "corrected_text": "This is different but should be ignored.",
    }))
    result = translate_pass2(
        client=client,
        model_name="test-model",
        prompt_template="# version: 2.0\nSource: {SOURCE_TEXT}\nDraft: {DRAFT_TEXT}",
        source_text="源文本",
        draft_text="Original draft text.",
        full_source_block="源文本",
    )
    assert result == "Original draft text."


def test_pass2_no_fidelity_errors_accepts_empty_corrected_text() -> None:
    client = MockLLMClient(json.dumps({
        "fidelity_errors_found": False,
        "corrected_text": "",
    }))
    result = translate_pass2(
        client=client,
        model_name="test-model",
        prompt_template="# version: 2.3\nSource: {SOURCE_TEXT}\nDraft: {DRAFT_TEXT}",
        source_text="源文本",
        draft_text="Original draft text.",
        full_source_block="源文本",
    )
    assert result == "Original draft text."


def test_pass2_fidelity_errors_with_corrected_text_returns_corrected() -> None:
    client = MockLLMClient(json.dumps({
        "fidelity_errors_found": True,
        "analysis": "Missing sentence detected.",
        "corrected_text": "Original draft text. Added missing sentence.",
    }))
    result = translate_pass2(
        client=client,
        model_name="test-model",
        prompt_template="# version: 2.0\nSource: {SOURCE_TEXT}\nDraft: {DRAFT_TEXT}",
        source_text="源文本",
        draft_text="Original draft text.",
        full_source_block="源文本",
    )
    assert result == "Original draft text. Added missing sentence."


def test_pass2_json_parse_failure_falls_back_to_draft() -> None:
    client = MockLLMClient("This is not JSON.")
    fallbacks = []
    result = translate_pass2(
        client=client,
        model_name="test-model",
        prompt_template="# version: 2.0\nSource: {SOURCE_TEXT}\nDraft: {DRAFT_TEXT}",
        source_text="源文本",
        draft_text="Original draft text.",
        full_source_block="源文本",
        chapter_number=7,
        block_id="block-1",
        fallback_callback=fallbacks.append,
    )
    assert result == "Original draft text."
    assert fallbacks == [
        {
            "reason": "json_parse_failed",
            "model_name": "test-model",
            "chapter_number": 7,
            "block_id": "block-1",
            "segment_id": None,
        }
    ]


def test_pass2_json_parse_failure_logs_context() -> None:
    messages: list[str] = []
    sink_id = logger.add(lambda message: messages.append(str(message)), level="DEBUG", format="{message}")
    try:
        client = MockLLMClient("This is not JSON.")
        result = translate_pass2(
            client=client,
            model_name="audit-model",
            prompt_template="# version: 2.0\nSource: {SOURCE_TEXT}\nDraft: {DRAFT_TEXT}",
            source_text="源文本",
            draft_text="Original draft text.",
            full_source_block="源文本",
            chapter_number=12,
            block_id="block-3",
            segment_id="seg-4",
        )
    finally:
        logger.remove(sink_id)

    assert result == "Original draft text."
    log_output = "\n".join(messages)
    assert "Pass 2 JSON parse failed" in log_output
    assert "audit-model" in log_output
    assert "chapter=12" in log_output
    assert "block=block-3" in log_output
    assert "segment=seg-4" in log_output


def test_pass2_fidelity_errors_empty_corrected_text_falls_back() -> None:
    client = MockLLMClient(json.dumps({
        "fidelity_errors_found": True,
        "analysis": "Errors found but no correction provided.",
        "corrected_text": "",
    }))
    fallbacks = []
    result = translate_pass2(
        client=client,
        model_name="test-model",
        prompt_template="# version: 2.0\nSource: {SOURCE_TEXT}\nDraft: {DRAFT_TEXT}",
        source_text="源文本",
        draft_text="Original draft text.",
        full_source_block="源文本",
        fallback_callback=fallbacks.append,
    )
    assert result == "Original draft text."
    assert fallbacks[0]["reason"] == "empty_corrected_text"


def test_pass2_fidelity_false_non_identical_corrected_text_ignored() -> None:
    client = MockLLMClient(json.dumps({
        "fidelity_errors_found": False,
        "analysis": "No errors.",
        "corrected_text": "Completely different text that should be ignored.",
    }))
    result = translate_pass2(
        client=client,
        model_name="test-model",
        prompt_template="# version: 2.0\nSource: {SOURCE_TEXT}\nDraft: {DRAFT_TEXT}",
        source_text="源文本",
        draft_text="Original draft text.",
        full_source_block="源文本",
    )
    assert result == "Original draft text."
