from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from resemantica.epub.extractor import extract_epub
from resemantica.packets.models import ParagraphBundle
from resemantica.settings import derive_paths, load_config
from resemantica.translation.bundle_context import (
    extract_glossary_target_terms_for_pass3,
    format_bundle_for_pass3,
)
from resemantica.translation.pass3 import translate_pass3
from resemantica.translation.pipeline import (
    translate_chapter_pass1,
    translate_chapter_pass2,
    translate_chapter_pass3,
)
from resemantica.translation.risk import classify_paragraph_risk, classify_paragraph_risk_from_text
from resemantica.translation.validators import validate_pass3_integrity


def test_pass3_disabled_event_is_info(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    from resemantica.orchestration.events import subscribe, unsubscribe

    received = []
    callback = received.append
    subscribe("*", callback)
    try:
        result = translate_chapter_pass3(
            release_id="pass3-disabled-info",
            chapter_number=1,
            run_id="run-001",
        )
    finally:
        unsubscribe("*", callback)

    assert result["status"] == "skipped"
    event = next(event for event in received if event.event_type == "translate-chapter.pass3.skipped")
    assert event.severity == "info"


def _write_fixture_epub(epub_path: Path, chapter_xhtml: str) -> None:
    workspace = epub_path.parent / "fixture_book_m9"
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


def _extract_one_chapter(tmp_path: Path, chapter_xhtml: str, release_id: str) -> None:
    input_epub = tmp_path / f"{release_id}.epub"
    _write_fixture_epub(input_epub, chapter_xhtml)
    result = extract_epub(input_path=input_epub, release_id=release_id)
    assert result.status == "success"


def _run_full_pipeline(
    *,
    release_id: str,
    chapter_number: int,
    run_id: str,
    llm_client,
    config=None,
    project_root=None,
):
    if config is None:
        from resemantica.settings import AppConfig, TranslationConfig
        config = AppConfig(translation=TranslationConfig(pass3_default=True))
    r1 = translate_chapter_pass1(
        release_id=release_id, chapter_number=chapter_number,
        run_id=run_id, llm_client=llm_client, config=config, project_root=project_root,
    )
    r2 = translate_chapter_pass2(
        release_id=release_id, chapter_number=chapter_number,
        run_id=run_id, llm_client=llm_client, config=config, project_root=project_root,
    )
    r3 = translate_chapter_pass3(
        release_id=release_id, chapter_number=chapter_number,
        run_id=run_id, llm_client=llm_client, config=config, project_root=project_root,
    )
    config_obj = config or load_config()
    paths = derive_paths(config_obj, release_id=release_id, project_root=project_root)
    validation_dir = paths.release_root / "runs" / run_id / "validation" / f"chapter-{chapter_number}"
    return {
        "status": "success",
        "pass1_artifact": r1.get("pass1_artifact"),
        "pass2_artifact": r2.get("pass2_artifact"),
        "pass3_artifact": r3.get("pass3_artifact"),
        "chapter_report": str(validation_dir / "chapter.json"),
    }


class ScriptedLLMPass3:
    def __init__(self) -> None:
        self.pass1_calls = 0
        self.pass2_calls = 0
        self.pass3_calls = 0
        self.pass3_override: str | None = None

    def generate_text(self, *, model_name: str, prompt: str) -> str:
        if "PASS3" in prompt:
            self.pass3_calls += 1
            if self.pass3_override is not None:
                return self.pass3_override
            if "⟦B_1⟧" in prompt:
                return "You ⟦B_1⟧are really quite good⟦/B_1⟧!"
            return "Polished text."

        if "PASS1" in prompt:
            self.pass1_calls += 1
            if "⟦B_1⟧" in prompt:
                return "You ⟦B_1⟧good⟦/B_1⟧?"
            return "Draft text."

        if "translation auditor" in prompt:
            self.pass2_calls += 1
            if "⟦B_1⟧" in prompt:
                corrected = "You ⟦B_1⟧really good⟦/B_1⟧?"
            else:
                corrected = "Corrected text."
            return json.dumps(
                {
                    "fidelity_errors_found": True,
                    "analysis": "scripted correction",
                    "corrected_text": corrected,
                }
            )

        return "Unexpected."


class TestRiskClassifier:
    def test_zero_risk_is_low(self) -> None:
        result = classify_paragraph_risk(
            idiom_count=0,
            title_count=0,
            has_reveal_gated_relationship=False,
            ambiguous_pronoun_count=0,
            placeholder_count=0,
            distinct_entity_count=0,
        )
        assert result.risk_score == 0.0
        assert result.risk_class == "LOW"

    def test_deterministic_output_for_identical_inputs(self) -> None:
        kwargs = dict(
            idiom_count=2,
            title_count=1,
            has_reveal_gated_relationship=True,
            ambiguous_pronoun_count=1,
            placeholder_count=3,
            distinct_entity_count=2,
        )
        first = classify_paragraph_risk(**kwargs)
        second = classify_paragraph_risk(**kwargs)
        assert first.risk_score == second.risk_score
        assert first.risk_class == second.risk_class
        assert first.to_dict() == second.to_dict()

    def test_idiom_density_saturates_at_three(self) -> None:
        result = classify_paragraph_risk(
            idiom_count=3,
            title_count=0,
            has_reveal_gated_relationship=False,
            ambiguous_pronoun_count=0,
            placeholder_count=0,
            distinct_entity_count=0,
        )
        assert result.idiom_density_score == 1.0
        assert result.risk_score == pytest.approx(0.20)

    def test_title_density_saturates_at_three(self) -> None:
        result = classify_paragraph_risk(
            idiom_count=0,
            title_count=3,
            has_reveal_gated_relationship=False,
            ambiguous_pronoun_count=0,
            placeholder_count=0,
            distinct_entity_count=0,
        )
        assert result.title_density_score == 1.0
        assert result.risk_score == pytest.approx(0.15)

    def test_pronoun_ambiguity_saturates_at_two(self) -> None:
        result = classify_paragraph_risk(
            idiom_count=0,
            title_count=0,
            has_reveal_gated_relationship=False,
            ambiguous_pronoun_count=2,
            placeholder_count=0,
            distinct_entity_count=0,
        )
        assert result.pronoun_ambiguity_score == 1.0
        assert result.risk_score == pytest.approx(0.20)

    def test_xhtml_fragility_saturates_at_five(self) -> None:
        result = classify_paragraph_risk(
            idiom_count=0,
            title_count=0,
            has_reveal_gated_relationship=False,
            ambiguous_pronoun_count=0,
            placeholder_count=5,
            distinct_entity_count=0,
        )
        assert result.xhtml_fragility_score == 1.0
        assert result.risk_score == pytest.approx(0.15)

    def test_entity_density_saturates_at_four(self) -> None:
        result = classify_paragraph_risk(
            idiom_count=0,
            title_count=0,
            has_reveal_gated_relationship=False,
            ambiguous_pronoun_count=0,
            placeholder_count=0,
            distinct_entity_count=4,
        )
        assert result.entity_density_score == 1.0
        assert result.risk_score == pytest.approx(0.10)

    def test_relationship_reveal_is_binary(self) -> None:
        result = classify_paragraph_risk(
            idiom_count=0,
            title_count=0,
            has_reveal_gated_relationship=True,
            ambiguous_pronoun_count=0,
            placeholder_count=0,
            distinct_entity_count=0,
        )
        assert result.relationship_reveal_score == 1.0
        assert result.risk_score == pytest.approx(0.20)

    def test_threshold_edge_at_0_7_is_high(self) -> None:
        result = classify_paragraph_risk(
            idiom_count=3,
            title_count=3,
            has_reveal_gated_relationship=True,
            ambiguous_pronoun_count=2,
            placeholder_count=5,
            distinct_entity_count=4,
            threshold_high=0.7,
        )
        assert result.risk_score == 1.0
        assert result.risk_class == "HIGH"

    def test_just_below_threshold_is_medium(self) -> None:
        result = classify_paragraph_risk(
            idiom_count=0,
            title_count=0,
            has_reveal_gated_relationship=True,
            ambiguous_pronoun_count=1,
            placeholder_count=2,
            distinct_entity_count=0,
            threshold_high=0.7,
        )
        expected = 0.0 * 0.20 + 0.0 * 0.15 + 1.0 * 0.20 + 0.5 * 0.20 + 0.4 * 0.15 + 0.0 * 0.10
        assert result.risk_score == pytest.approx(expected)
        assert result.risk_score < 0.7
        assert result.risk_class == "MEDIUM"

    def test_all_sub_scores_persisted_in_report(self) -> None:
        result = classify_paragraph_risk(
            idiom_count=1,
            title_count=2,
            has_reveal_gated_relationship=True,
            ambiguous_pronoun_count=3,
            placeholder_count=4,
            distinct_entity_count=5,
        )
        report = result.to_dict()
        assert "idiom_density_score" in report
        assert "title_density_score" in report
        assert "relationship_reveal_score" in report
        assert "pronoun_ambiguity_score" in report
        assert "xhtml_fragility_score" in report
        assert "entity_density_score" in report
        assert "risk_score" in report
        assert "risk_class" in report

    def test_risk_clamped_to_one(self) -> None:
        result = classify_paragraph_risk(
            idiom_count=10,
            title_count=10,
            has_reveal_gated_relationship=True,
            ambiguous_pronoun_count=10,
            placeholder_count=10,
            distinct_entity_count=10,
        )
        assert result.risk_score == 1.0

    def test_from_text_counts_placeholders_and_pronouns(self) -> None:
        result = classify_paragraph_risk_from_text(
            source_text="Text ⟦B_1⟧and⟦/B_1⟧ ⟦I_1⟧more⟦/I_1⟧",
            pass2_text="He said she was there.",
        )
        assert result.xhtml_fragility_score == pytest.approx(min(1.0, 2 / 5.0))
        assert result.pronoun_ambiguity_score == pytest.approx(min(1.0, 3 / 2.0))


class TestPass3Integrity:
    def test_valid_pass3_passes(self) -> None:
        result = validate_pass3_integrity(
            source_text="Source ⟦B_1⟧text⟦/B_1⟧",
            pass2_output="Draft ⟦B_1⟧text⟦/B_1⟧",
            pass3_output="Polished ⟦B_1⟧text⟦/B_1⟧",
        )
        assert result.is_valid

    def test_empty_pass3_fails(self) -> None:
        result = validate_pass3_integrity(
            source_text="Source",
            pass2_output="Draft",
            pass3_output="",
        )
        assert not result.is_valid
        assert any("empty" in e.lower() for e in result.errors)

    def test_placeholder_mismatch_fails(self) -> None:
        result = validate_pass3_integrity(
            source_text="Source ⟦B_1⟧text⟦/B_1⟧",
            pass2_output="Draft ⟦B_1⟧text⟦/B_1⟧",
            pass3_output="Polished text",
        )
        assert not result.is_valid
        assert any("placeholder" in e.lower() for e in result.errors)

    def test_terminology_drift_detected(self) -> None:
        result = validate_pass3_integrity(
            source_text="Source",
            pass2_output="Zhang San fought Li Si.",
            pass3_output="Zhang fought the warrior.",
            glossary_terms=["Li Si"],
        )
        assert not result.is_valid
        assert any("Li Si" in e for e in result.errors)

    def test_no_terminology_drift_when_terms_preserved(self) -> None:
        result = validate_pass3_integrity(
            source_text="Source",
            pass2_output="Zhang San fought Li Si.",
            pass3_output="Zhang San battled Li Si.",
            glossary_terms=["Zhang San", "Li Si"],
        )
        assert result.is_valid

    def test_glossary_terms_extracted_for_integrity_validation(self) -> None:
        bundle = ParagraphBundle(
            bundle_id="b1",
            release_id="rel",
            chapter_number=1,
            block_id="blk",
            matched_glossary_entries=[
                {"source_term": "张三", "target_term": "Zhang San", "category": "character"}
            ],
            alias_resolutions=[],
            matched_idioms=[],
            local_relationships=[],
            continuity_notes=[],
            retrieval_evidence_summary=[],
            risk_classification="unscored",
            packet_ref="pkt",
        )
        result = validate_pass3_integrity(
            source_text="Source",
            pass2_output="Zhang San arrived.",
            pass3_output="He arrived.",
            glossary_terms=extract_glossary_target_terms_for_pass3(bundle),
        )

        assert not result.is_valid
        assert any("Zhang San" in error for error in result.errors)


class TestBundleInformedRisk:
    def test_bundle_path_computes_pronouns_from_pass2_output(self) -> None:
        result = classify_paragraph_risk_from_text(
            source_text="普通文本。",
            pass2_text="He told her they should leave.",
            idiom_count=0,
            title_count=0,
            has_reveal_gated_relationship=False,
            distinct_entity_count=0,
        )
        assert result.pronoun_ambiguity_score == 1.0

    def test_title_glossary_entries_increase_title_risk(self) -> None:
        from resemantica.translation import pipeline as pipeline_mod

        bundle = ParagraphBundle(
            bundle_id="b1",
            release_id="rel",
            chapter_number=1,
            block_id="blk",
            matched_glossary_entries=[
                {"source_term": "战神", "target_term": "War God", "category": "title_honorific"}
            ],
            alias_resolutions=[],
            matched_idioms=[],
            local_relationships=[],
            continuity_notes=[],
            retrieval_evidence_summary=[],
            risk_classification="unscored",
            packet_ref="pkt",
        )

        assert pipeline_mod._count_title_honorific_glossary_entries(bundle) == 1

    def test_relationship_reveal_risk_requires_reveal_data(self) -> None:
        from resemantica.translation import pipeline as pipeline_mod

        plain = ParagraphBundle(
            bundle_id="b1",
            release_id="rel",
            chapter_number=1,
            block_id="blk",
            matched_glossary_entries=[],
            alias_resolutions=[],
            matched_idioms=[],
            local_relationships=[{"relationship_id": "r1", "is_masked_identity": False}],
            continuity_notes=[],
            retrieval_evidence_summary=[],
            risk_classification="unscored",
            packet_ref="pkt",
        )
        revealed_without_range = ParagraphBundle(
            bundle_id="b0",
            release_id="rel",
            chapter_number=1,
            block_id="blk",
            matched_glossary_entries=[],
            alias_resolutions=[],
            matched_idioms=[],
            local_relationships=[{"relationship_id": "r0", "revealed_chapter": 1}],
            continuity_notes=[],
            retrieval_evidence_summary=[],
            risk_classification="unscored",
            packet_ref="pkt",
        )
        masked = ParagraphBundle(
            bundle_id="b2",
            release_id="rel",
            chapter_number=1,
            block_id="blk",
            matched_glossary_entries=[],
            alias_resolutions=[],
            matched_idioms=[],
            local_relationships=[{"relationship_id": "r2", "is_masked_identity": True}],
            continuity_notes=[],
            retrieval_evidence_summary=[],
            risk_classification="unscored",
            packet_ref="pkt",
        )
        gated = ParagraphBundle(
            bundle_id="b3",
            release_id="rel",
            chapter_number=1,
            block_id="blk",
            matched_glossary_entries=[],
            alias_resolutions=[],
            matched_idioms=[],
            local_relationships=[{"relationship_id": "r3", "revealed_chapter": 5, "source_chapter": 3}],
            continuity_notes=[],
            retrieval_evidence_summary=[],
            risk_classification="unscored",
            packet_ref="pkt",
        )

        assert pipeline_mod._has_reveal_gated_relationship(plain) is False
        assert pipeline_mod._has_reveal_gated_relationship(revealed_without_range) is False
        assert pipeline_mod._has_reveal_gated_relationship(masked) is True
        assert pipeline_mod._has_reveal_gated_relationship(gated) is True

    def test_pass3_prompt_includes_preservation_constraints(self) -> None:
        class CaptureClient:
            def __init__(self) -> None:
                self.last_prompt = ""

            def generate_text(self, *, model_name: str, prompt: str) -> str:  # noqa: ARG002
                self.last_prompt = prompt
                return "polished"

        bundle = ParagraphBundle(
            bundle_id="b1",
            release_id="rel",
            chapter_number=1,
            block_id="blk",
            matched_glossary_entries=[
                {"source_term": "战神", "target_term": "War God", "category": "title_honorific"}
            ],
            alias_resolutions=[{"alias_text": "老张", "entity_name": "Zhang San"}],
            matched_idioms=[{"source_text": "画蛇添足", "preferred_rendering_en": "gild the lily"}],
            local_relationships=[{"type": "ALLY_OF", "source_entity_id": "e1", "target_entity_id": "e2"}],
            continuity_notes=[],
            retrieval_evidence_summary=[],
            risk_classification="unscored",
            packet_ref="pkt",
        )
        context = format_bundle_for_pass3(bundle)
        client = CaptureClient()

        translate_pass3(
            client=client,
            model_name="model",
            prompt_template=(
                "PASS3\n{GLOSSARY}\n{ALIAS_RESOLUTIONS}\n"
                "{MATCHED_IDIOMS}\n{RELATIONSHIP_CONSTRAINTS}\n"
                "{SOURCE_TEXT}\n{PASS2_OUTPUT}"
            ),
            source_text="source",
            pass2_output="pass2",
            glossary_text=context["glossary"],
            alias_resolutions=context["alias_resolutions"],
            matched_idioms=context["matched_idioms"],
            relationship_constraints=context["relationship_constraints"],
        )

        assert "War God" in client.last_prompt
        assert "老张" in client.last_prompt
        assert "gild the lily" in client.last_prompt
        assert "ALLY_OF" in client.last_prompt


class TestPass3SkipAndPipeline:
    def test_high_risk_skips_pass3(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        _extract_one_chapter(
            tmp_path,
            """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body><p>普通文本。</p></body></html>
""",
            "m9-skip-high",
        )

        from resemantica.translation import pipeline as pipeline_mod
        from resemantica.translation.risk import RiskClassification

        def _force_high(*args, **kwargs):
            return RiskClassification(
                risk_score=0.9,
                risk_class="HIGH",
                idiom_density_score=1.0,
                title_density_score=1.0,
                relationship_reveal_score=1.0,
                pronoun_ambiguity_score=0.0,
                xhtml_fragility_score=0.0,
                entity_density_score=0.0,
            )

        monkeypatch.setattr(pipeline_mod, "classify_paragraph_risk_from_text", _force_high)

        client = ScriptedLLMPass3()
        result = _run_full_pipeline(
            release_id="m9-skip-high",
            chapter_number=1,
            run_id="run-skip-high",
            llm_client=client,
        )
        assert result["status"] == "success"
        assert client.pass3_calls == 0

        chapter_report = json.loads(Path(result["chapter_report"]).read_text(encoding="utf-8"))
        assert chapter_report["pass3_enabled"] is True

        pass3_artifact = json.loads(Path(result["pass3_artifact"]).read_text(encoding="utf-8"))
        block = pass3_artifact["blocks"][0]
        assert block["pass_decision"] == "skipped_high_risk"
        assert block["final_output"] == block["pass2_output"]

    def test_low_risk_runs_pass3(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        _extract_one_chapter(
            tmp_path,
            """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body><p>你<b>好</b>吗？</p></body></html>
""",
            "m9-low-risk",
        )

        client = ScriptedLLMPass3()
        result = _run_full_pipeline(
            release_id="m9-low-risk",
            chapter_number=1,
            run_id="run-low-risk",
            llm_client=client,
        )
        assert result["status"] == "success"
        assert result["pass3_artifact"] is not None
        assert client.pass3_calls > 0

        pass3_artifact = json.loads(Path(result["pass3_artifact"]).read_text(encoding="utf-8"))
        block = pass3_artifact["blocks"][0]
        assert block["pass_decision"] == "pass3_accepted"
        assert block["pass3_output"] is not None

    def test_integrity_failure_falls_back_to_pass2(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        _extract_one_chapter(
            tmp_path,
            """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body><p>你<b>好</b>吗？</p></body></html>
""",
            "m9-fallback",
        )

        client = ScriptedLLMPass3()
        client.pass3_override = "No placeholders here"
        result = _run_full_pipeline(
            release_id="m9-fallback",
            chapter_number=1,
            run_id="run-fallback",
            llm_client=client,
        )
        assert result["status"] == "success"

        pass3_artifact = json.loads(Path(result["pass3_artifact"]).read_text(encoding="utf-8"))
        block = pass3_artifact["blocks"][0]
        assert block["pass_decision"] == "pass3_rejected_integrity_failure"
        assert block["final_output"] == block["pass2_output"]
        assert block["pass3_output"] is None

    def test_risk_report_includes_all_sub_scores(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        _extract_one_chapter(
            tmp_path,
            """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body><p>普通文本。</p></body></html>
""",
            "m9-risk-report",
        )

        client = ScriptedLLMPass3()
        result = _run_full_pipeline(
            release_id="m9-risk-report",
            chapter_number=1,
            run_id="run-risk-report",
            llm_client=client,
        )

        pass3_artifact = json.loads(Path(result["pass3_artifact"]).read_text(encoding="utf-8"))
        risk = pass3_artifact["risk_classifications"][0]
        assert "idiom_density_score" in risk
        assert "title_density_score" in risk
        assert "relationship_reveal_score" in risk
        assert "pronoun_ambiguity_score" in risk
        assert "xhtml_fragility_score" in risk
        assert "entity_density_score" in risk
        assert "risk_score" in risk
        assert "risk_class" in risk

    def test_chapter_report_includes_pass_decisions(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        _extract_one_chapter(
            tmp_path,
            """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body><p>普通文本。</p></body></html>
""",
            "m9-chapter-report",
        )

        client = ScriptedLLMPass3()
        result = _run_full_pipeline(
            release_id="m9-chapter-report",
            chapter_number=1,
            run_id="run-chapter-report",
            llm_client=client,
        )

        chapter_report = json.loads(Path(result["chapter_report"]).read_text(encoding="utf-8"))
        assert chapter_report["pass3_enabled"] is True
        assert "risk_classifications" in chapter_report
        assert len(chapter_report["risk_classifications"]) > 0

    def test_force_bypasses_pass3_cache(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        _extract_one_chapter(
            tmp_path,
            """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body><p>普通文本。</p></body></html>
""",
            "m9-force-pass3",
        )

        first_client = ScriptedLLMPass3()
        result = _run_full_pipeline(
            release_id="m9-force-pass3",
            chapter_number=1,
            run_id="run-force-pass3",
            llm_client=first_client,
        )
        assert result["pass3_artifact"] is not None
        assert first_client.pass3_calls == 1

        cached_client = ScriptedLLMPass3()
        from resemantica.settings import AppConfig, TranslationConfig
        pass3_config = AppConfig(translation=TranslationConfig(pass3_default=True))
        translate_chapter_pass3(
            release_id="m9-force-pass3",
            chapter_number=1,
            run_id="run-force-pass3",
            llm_client=cached_client,
            config=pass3_config,
        )
        assert cached_client.pass3_calls == 0

        forced_client = ScriptedLLMPass3()
        translate_chapter_pass3(
            release_id="m9-force-pass3",
            chapter_number=1,
            run_id="run-force-pass3",
            llm_client=forced_client,
            config=pass3_config,
            force=True,
        )
        assert forced_client.pass3_calls == 1

    def test_unreadable_pass3_checkpoint_regenerates_without_force(
        self,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        release_id = "m83-pass3-corrupt-cache"
        run_id = "run-pass3-corrupt-cache"
        _extract_one_chapter(
            tmp_path,
            """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body><p>你<b>好</b>吗？</p></body></html>
""",
            release_id,
        )
        from resemantica.settings import AppConfig, TranslationConfig

        config = AppConfig(translation=TranslationConfig(pass3_default=True))
        first_client = ScriptedLLMPass3()
        first = _run_full_pipeline(
            release_id=release_id,
            chapter_number=1,
            run_id=run_id,
            llm_client=first_client,
            config=config,
        )
        artifact_path = Path(first["pass3_artifact"])
        artifact_path.write_bytes(b"\x00" * 64)

        repair_client = ScriptedLLMPass3()
        repaired = translate_chapter_pass3(
            release_id=release_id,
            chapter_number=1,
            run_id=run_id,
            llm_client=repair_client,
            config=config,
        )

        assert repaired["status"] == "success"
        assert repair_client.pass3_calls == first_client.pass3_calls
        assert json.loads(artifact_path.read_text(encoding="utf-8"))["status"] == "success"

    def test_pass2_failure_still_reports(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        _extract_one_chapter(
            tmp_path,
            """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body><p>你<b>好</b>吗？</p></body></html>
""",
            "m9-fail-report",
        )

        class FailPass2:
            def generate_text(self, *, model_name: str, prompt: str) -> str:
                if "PASS1" in prompt:
                    return "You ⟦B_1⟧good⟦/B_1⟧?"
                return ""
        client = FailPass2()
        translate_chapter_pass1(
            release_id="m9-fail-report",
            chapter_number=1,
            run_id="run-fail-report",
            llm_client=client,
        )
        # With graceful fallback, Pass 2 JSON parse failure returns original draft
        result = translate_chapter_pass2(
            release_id="m9-fail-report",
            chapter_number=1,
            run_id="run-fail-report",
            llm_client=client,
        )
        assert result["status"] == "success"
