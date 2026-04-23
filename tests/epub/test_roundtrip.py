from __future__ import annotations

import json
from pathlib import Path
import zipfile

from resemantica.epub.extractor import extract_epub


def _write_fixture_epub(epub_path: Path, chapters: list[str]) -> None:
    workspace = epub_path.parent / "fixture_book"
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

    manifest_items = []
    spine_items = []
    for idx, chapter_content in enumerate(chapters, start=1):
        chapter_name = f"chapter{idx}.xhtml"
        (oebps / chapter_name).write_text(chapter_content, encoding="utf-8")
        manifest_items.append(
            f'<item id="chap{idx}" href="{chapter_name}" media-type="application/xhtml+xml"/>'
        )
        spine_items.append(f'<itemref idref="chap{idx}"/>')

    (oebps / "content.opf").write_text(
        f"""<?xml version="1.0" encoding="UTF-8"?>
<package version="3.0" xmlns="http://www.idpf.org/2007/opf">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Fixture</dc:title>
    <dc:language>zh-CN</dc:language>
    <dc:identifier>fixture-book</dc:identifier>
  </metadata>
  <manifest>
    {' '.join(manifest_items)}
  </manifest>
  <spine>
    {' '.join(spine_items)}
  </spine>
</package>
""",
        encoding="utf-8",
    )

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


def _read_zip_file(zip_path: Path, member: str) -> bytes:
    with zipfile.ZipFile(zip_path, "r") as archive:
        return archive.read(member)


def test_epub_roundtrip_writes_artifacts_and_rebuilds(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    input_epub = tmp_path / "input.epub"
    _write_fixture_epub(
        input_epub,
        chapters=[
            """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body><p>第一段。</p><p>第二段。</p></body></html>""",
            """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body><h1>标题</h1><p>内容。</p></body></html>""",
        ],
    )

    result = extract_epub(input_path=input_epub, release_id="m1-fixture")

    assert result.status == "success"
    assert result.rebuilt_epub_path.exists()
    assert result.validation_report_path.exists()
    assert (result.release_root / "extracted" / "chapters" / "chapter-1.json").exists()
    assert (result.release_root / "extracted" / "placeholders" / "chapter-1.json").exists()

    original_ch1 = _read_zip_file(input_epub, "OEBPS/chapter1.xhtml")
    rebuilt_ch1 = _read_zip_file(result.rebuilt_epub_path, "OEBPS/chapter1.xhtml")
    assert original_ch1 == rebuilt_ch1


def test_malformed_xhtml_generates_readable_report(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    input_epub = tmp_path / "broken.epub"
    _write_fixture_epub(
        input_epub,
        chapters=[
            """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body><p>未闭合段落</body></html>""",
        ],
    )

    result = extract_epub(input_path=input_epub, release_id="m1-broken")
    report = json.loads(result.validation_report_path.read_text(encoding="utf-8"))

    assert result.status == "failed"
    assert report["status"] == "failed"
    assert any("Malformed XHTML" in error for error in report["errors"])


def test_block_ordering_is_stable_across_reruns(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    input_epub = tmp_path / "stable.epub"
    _write_fixture_epub(
        input_epub,
        chapters=[
            """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body>
<p>甲。</p><p>乙。</p><p>丙。</p>
</body></html>""",
        ],
    )

    run_a = extract_epub(input_path=input_epub, release_id="run-a")
    run_b = extract_epub(input_path=input_epub, release_id="run-b")

    chapter_a = json.loads(
        (run_a.release_root / "extracted" / "chapters" / "chapter-1.json").read_text(encoding="utf-8")
    )
    chapter_b = json.loads(
        (run_b.release_root / "extracted" / "chapters" / "chapter-1.json").read_text(encoding="utf-8")
    )

    ordering_a = [(record["block_id"], record["block_order"]) for record in chapter_a["records"]]
    ordering_b = [(record["block_id"], record["block_order"]) for record in chapter_b["records"]]
    assert ordering_a == ordering_b


def test_long_block_is_split_with_segment_ids(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    input_epub = tmp_path / "segmented.epub"
    long_sentence = "这是一个很长的句子。" * 220
    _write_fixture_epub(
        input_epub,
        chapters=[
            f"""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body><p>{long_sentence}</p></body></html>""",
        ],
    )

    result = extract_epub(input_path=input_epub, release_id="run-segments")
    chapter = json.loads(
        (result.release_root / "extracted" / "chapters" / "chapter-1.json").read_text(encoding="utf-8")
    )
    records = chapter["records"]

    assert len(records) >= 2
    assert records[0]["block_id"].startswith("ch001_blk001_seg")
    assert records[0]["parent_block_id"] == "ch001_blk001"
    assert records[0]["segment_order"] == 1
