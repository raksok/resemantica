from __future__ import annotations

import json
from pathlib import Path
import zipfile

from resemantica.epub.extractor import extract_epub
from resemantica.translation.pipeline import (
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
        self._first_pass1_done = False
        self.drop_placeholders = False

    def generate_text(self, *, model_name: str, prompt: str) -> str:  # noqa: ARG002
        if "PASS1" in prompt:
            self.pass1_calls += 1
            if self.fail_first_pass1 and not self._first_pass1_done:
                self._first_pass1_done = True
                return ""
            if self.drop_placeholders and "⟦B_1⟧" in prompt:
                return "You good?"
            if "⟦B_1⟧" in prompt:
                return "You ⟦B_1⟧good⟦/B_1⟧?"
            return "Segment draft."

        if "Correct the English" in prompt:
            self.pass2_calls += 1
            if "⟦B_1⟧" in prompt:
                return "You ⟦B_1⟧really good⟦/B_1⟧?"
            return "Segment corrected."

        return "Unexpected."


def _extract_one_chapter(tmp_path: Path, chapter_xhtml: str, release_id: str) -> None:
    input_epub = tmp_path / f"{release_id}.epub"
    _write_fixture_epub(input_epub, chapter_xhtml)
    result = extract_epub(input_path=input_epub, release_id=release_id)
    assert result.status == "success"


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

    r2 = translate_chapter_pass2(
        release_id="m2-failure",
        chapter_number=1,
        run_id="run-001",
        llm_client=client,
    )
    assert r2["status"] == "success"
    assert len(r2["blocks"]) == 0


def test_reactive_resegmentation_on_structural_failure(tmp_path: Path, monkeypatch) -> None:
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
