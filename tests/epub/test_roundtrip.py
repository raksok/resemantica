from __future__ import annotations

import json
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from resemantica.db.sqlite import ensure_schema, open_connection
from resemantica.db.summary_repo import save_summary_draft
from resemantica.epub.extractor import extract_epub
from resemantica.epub.rebuild import rebuild_chapter_xhtml, rebuild_translated_epub
from resemantica.settings import derive_paths, load_config


def _write_fixture_epub(
    epub_path: Path,
    chapters: list[str],
    *,
    extra_files: dict[str, str] | None = None,
) -> None:
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
    for relative_path, content in (extra_files or {}).items():
        output_path = workspace / relative_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content, encoding="utf-8")

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


def _first_text_by_local_name(xml_text: str, local_name: str) -> str | None:
    root = ET.fromstring(xml_text.encode("utf-8"))
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] == local_name:
            return "".join(element.itertext())
    return None


def _mark_non_story(release_id: str, chapter_number: int = 1) -> None:
    paths = derive_paths(load_config(), release_id=release_id)
    chapter_payload = json.loads(
        (paths.extracted_chapters_dir / f"chapter-{chapter_number}.json").read_text(encoding="utf-8")
    )
    conn = open_connection(paths.db_path)
    ensure_schema(conn, "summaries")
    try:
        save_summary_draft(
            conn,
            release_id=release_id,
            chapter_number=chapter_number,
            summary_type="chapter_summary_zh_structured",
            content={"is_story_chapter": False, "events": []},
            chapter_source_hash=str(chapter_payload["chapter_source_hash"]),
            model_name="test",
            prompt_version="v1",
            run_id="summaries",
            validation_status="non_story_chapter",
            is_story_chapter=0,
        )
    finally:
        conn.close()


def _write_pass2_translation(
    release_id: str,
    run_id: str,
    *,
    chapter_number: int = 1,
    text: str = "Translated non-story.",
) -> None:
    paths = derive_paths(load_config(), release_id=release_id)
    chapter_payload = json.loads(
        (paths.extracted_chapters_dir / f"chapter-{chapter_number}.json").read_text(encoding="utf-8")
    )
    record = chapter_payload["records"][0]
    translation_dir = paths.release_root / "runs" / run_id / "translation" / f"chapter-{chapter_number}"
    translation_dir.mkdir(parents=True, exist_ok=True)
    (translation_dir / "pass2.json").write_text(
        json.dumps(
            {
                "blocks": [
                    {
                        "block_id": record["block_id"],
                        "parent_block_id": record["parent_block_id"],
                        "restored_text_en": text,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


def _write_pass2_translation_blocks(
    release_id: str,
    run_id: str,
    *,
    chapter_number: int,
    texts: list[str],
) -> None:
    paths = derive_paths(load_config(), release_id=release_id)
    chapter_payload = json.loads(
        (paths.extracted_chapters_dir / f"chapter-{chapter_number}.json").read_text(encoding="utf-8")
    )
    records = chapter_payload["records"]
    assert len(records) == len(texts)

    translation_dir = paths.release_root / "runs" / run_id / "translation" / f"chapter-{chapter_number}"
    translation_dir.mkdir(parents=True, exist_ok=True)
    (translation_dir / "pass2.json").write_text(
        json.dumps(
            {
                "blocks": [
                    {
                        "block_id": record["block_id"],
                        "parent_block_id": record["parent_block_id"],
                        "restored_text_en": text,
                    }
                    for record, text in zip(records, texts)
                ]
            }
        ),
        encoding="utf-8",
    )


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

    paths = derive_paths(load_config(), release_id="m1-fixture")
    conn = open_connection(paths.db_path)
    try:
        chapter_count = conn.execute(
            "SELECT COUNT(*) AS count FROM extracted_chapters WHERE release_id = ?",
            ("m1-fixture",),
        ).fetchone()["count"]
        block_count = conn.execute(
            "SELECT COUNT(*) AS count FROM extracted_blocks WHERE release_id = ?",
            ("m1-fixture",),
        ).fetchone()["count"]
    finally:
        conn.close()
    assert chapter_count == 2
    assert block_count >= 3


def test_rebuild_translated_epub_rebuilds_non_story_chapter_with_pass2(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    input_epub = tmp_path / "non-story-translated.epub"
    _write_fixture_epub(
        input_epub,
        chapters=[
            """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body><p>目录。</p></body></html>""",
        ],
    )
    extract_epub(input_path=input_epub, release_id="non-story-translated")
    _mark_non_story("non-story-translated")
    _write_pass2_translation(
        "non-story-translated",
        "production",
        text="Translated table of contents.",
    )

    result = rebuild_translated_epub(
        release_id="non-story-translated",
        run_id="production",
        config=load_config(),
    )

    assert result.status == "success"
    assert result.chapter_results[0].status == "success"
    chapter_artifact = (
        derive_paths(load_config(), release_id="non-story-translated").release_root
        / "runs"
        / "production"
        / "reconstruction"
        / "chapters"
        / "chapter-1.xhtml"
    )
    assert "Translated table of contents." in chapter_artifact.read_text(encoding="utf-8")
    rebuilt_chapter = _read_zip_file(result.output_path, "OEBPS/chapter1.xhtml").decode("utf-8")
    assert "Translated table of contents." in rebuilt_chapter
    assert "目录。" not in rebuilt_chapter


def test_rebuild_translated_epub_skips_non_story_chapter_without_translation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    input_epub = tmp_path / "non-story-untranslated.epub"
    _write_fixture_epub(
        input_epub,
        chapters=[
            """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body><p>版权页。</p></body></html>""",
        ],
    )
    extract_epub(input_path=input_epub, release_id="non-story-untranslated")
    _mark_non_story("non-story-untranslated")

    result = rebuild_translated_epub(
        release_id="non-story-untranslated",
        run_id="production",
        config=load_config(),
    )

    assert result.status == "success"
    assert result.chapter_results[0].status == "skipped"
    chapter_artifact = (
        derive_paths(load_config(), release_id="non-story-untranslated").release_root
        / "runs"
        / "production"
        / "reconstruction"
        / "chapters"
        / "chapter-1.xhtml"
    )
    assert not chapter_artifact.exists()
    rebuilt_chapter = _read_zip_file(result.output_path, "OEBPS/chapter1.xhtml").decode("utf-8")
    assert "版权页。" in rebuilt_chapter


def test_rebuild_translated_epub_updates_ncx_from_translated_heading(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    input_epub = tmp_path / "toc-ncx.epub"
    _write_fixture_epub(
        input_epub,
        chapters=[
            """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>第1章 旧标题</title></head>
<body><h1>第1章 旧标题</h1><p>正文。</p></body>
</html>""",
        ],
        extra_files={
            "OEBPS/toc.ncx": """<?xml version="1.0" encoding="UTF-8"?>
<ncx version="2005-1" xmlns="http://www.daisy.org/z3986/2005/ncx/">
  <navMap>
    <navPoint id="front" playOrder="1">
      <navLabel><text>封面</text></navLabel>
      <content src="cover.xhtml"/>
    </navPoint>
    <navPoint id="ch1" playOrder="2">
      <navLabel><text>第1章 旧标题</text></navLabel>
      <content src="chapter1.xhtml#start"/>
    </navPoint>
  </navMap>
</ncx>""",
        },
    )
    extract_epub(input_path=input_epub, release_id="toc-ncx")
    _write_pass2_translation_blocks(
        "toc-ncx",
        "production",
        chapter_number=1,
        texts=["Chapter 1: New Title", "Translated body."],
    )

    result = rebuild_translated_epub(
        release_id="toc-ncx",
        run_id="production",
        config=load_config(),
    )

    assert result.status == "success"
    assert result.chapter_results[0].translated_title == "Chapter 1: New Title"
    rebuilt_chapter = _read_zip_file(result.output_path, "OEBPS/chapter1.xhtml").decode("utf-8")
    rebuilt_ncx = _read_zip_file(result.output_path, "OEBPS/toc.ncx").decode("utf-8")
    assert _first_text_by_local_name(rebuilt_chapter, "title") == "Chapter 1: New Title"
    assert "Chapter 1: New Title" in rebuilt_ncx
    assert "第1章 旧标题" not in rebuilt_ncx
    assert "封面" in rebuilt_ncx


def test_rebuild_translated_epub_updates_nav_xhtml_from_translated_heading(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    input_epub = tmp_path / "nav-xhtml.epub"
    _write_fixture_epub(
        input_epub,
        chapters=[
            """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<head></head>
<body><h2>旧标题</h2><p>正文。</p></body>
</html>""",
        ],
        extra_files={
            "OEBPS/nav.xhtml": """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<body>
  <nav epub:type="toc">
    <ol>
      <li><a href="chapter1.xhtml">旧标题</a></li>
      <li><a href="missing.xhtml">未翻译前言</a></li>
    </ol>
  </nav>
</body>
</html>""",
        },
    )
    extract_epub(input_path=input_epub, release_id="nav-xhtml")
    _write_pass2_translation_blocks(
        "nav-xhtml",
        "production",
        chapter_number=1,
        texts=["Translated Nav Title", "Translated body."],
    )

    result = rebuild_translated_epub(
        release_id="nav-xhtml",
        run_id="production",
        config=load_config(),
    )

    assert result.status == "success"
    rebuilt_chapter = _read_zip_file(result.output_path, "OEBPS/chapter1.xhtml").decode("utf-8")
    rebuilt_nav = _read_zip_file(result.output_path, "OEBPS/nav.xhtml").decode("utf-8")
    assert _first_text_by_local_name(rebuilt_chapter, "title") == "Translated Nav Title"
    assert "Translated Nav Title" in rebuilt_nav
    assert "旧标题" not in rebuilt_nav
    assert "未翻译前言" in rebuilt_nav


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


def test_rebuild_chapter_xhtml_preserves_tags_and_attributes() -> None:
    source_xhtml = (
        '<html xmlns="http://www.w3.org/1999/xhtml"><body>'
        '<p class="lead">原文。</p>'
        "</body></html>"
    )
    records = [
        {
            "chapter_number": 1,
            "source_document_path": "OEBPS/chapter1.xhtml",
            "block_id": "ch001_blk001",
            "parent_block_id": "ch001_blk001",
            "block_order": 1,
            "segment_order": None,
        }
    ]
    result = rebuild_chapter_xhtml(
        source_xhtml,
        records,
        [{"block_id": "ch001_blk001", "parent_block_id": "ch001_blk001", "restored_text_en": "Translated."}],
        {},
    )

    assert result.status == "success"
    assert 'class="lead"' in result.xhtml
    assert "Translated." in result.xhtml


def test_rebuild_chapter_xhtml_updates_title_from_heading_plain_text() -> None:
    source_xhtml = (
        '<html xmlns="http://www.w3.org/1999/xhtml">'
        "<head><title>旧标题</title></head>"
        "<body><h1>旧标题</h1><p>正文。</p></body>"
        "</html>"
    )
    records = [
        {
            "chapter_number": 1,
            "source_document_path": "OEBPS/chapter1.xhtml",
            "block_id": "ch001_blk001",
            "parent_block_id": "ch001_blk001",
            "block_order": 1,
            "segment_order": None,
        },
        {
            "chapter_number": 1,
            "source_document_path": "OEBPS/chapter1.xhtml",
            "block_id": "ch001_blk002",
            "parent_block_id": "ch001_blk002",
            "block_order": 2,
            "segment_order": None,
        },
    ]

    result = rebuild_chapter_xhtml(
        source_xhtml,
        records,
        [
            {
                "block_id": "ch001_blk001",
                "parent_block_id": "ch001_blk001",
                "restored_text_en": "Translated <i>Dream</i> Title",
            },
            {
                "block_id": "ch001_blk002",
                "parent_block_id": "ch001_blk002",
                "restored_text_en": "Translated body.",
            },
        ],
        {},
    )

    assert result.status == "success"
    assert result.translated_title == "Translated Dream Title"
    assert _first_text_by_local_name(result.xhtml, "title") == "Translated Dream Title"
    assert "Translated <" not in _first_text_by_local_name(result.xhtml, "title")


def test_rebuild_chapter_xhtml_prefers_pass3_final_output() -> None:
    source_xhtml = '<html xmlns="http://www.w3.org/1999/xhtml"><body><p>原文。</p></body></html>'
    records = [
        {
            "chapter_number": 1,
            "source_document_path": "OEBPS/chapter1.xhtml",
            "block_id": "ch001_blk001",
            "parent_block_id": "ch001_blk001",
            "block_order": 1,
            "segment_order": None,
        }
    ]
    result = rebuild_chapter_xhtml(
        source_xhtml,
        records,
        [
            {
                "block_id": "ch001_blk001",
                "parent_block_id": "ch001_blk001",
                "restored_text_en": "Pass 2.",
                "final_output": "Pass 3.",
            }
        ],
        {},
    )

    assert "Pass 3." in result.xhtml
    assert "Pass 2." not in result.xhtml


def test_rebuild_chapter_xhtml_restores_placeholders_before_insertion() -> None:
    source_xhtml = '<html xmlns="http://www.w3.org/1999/xhtml"><body><p>你<b>好</b>。</p></body></html>'
    records = [
        {
            "chapter_number": 1,
            "source_document_path": "OEBPS/chapter1.xhtml",
            "block_id": "ch001_blk001",
            "parent_block_id": "ch001_blk001",
            "block_order": 1,
            "segment_order": None,
        }
    ]
    placeholder_map = {
        "blocks": {
            "ch001_blk001": [
                {
                    "placeholder": "⟦B_1⟧",
                    "element": "b",
                    "attributes": {},
                    "original_xhtml": "<b>",
                    "parent_placeholder": None,
                    "depth": 0,
                    "closing_order": ["⟦B_1⟧"],
                }
            ]
        }
    }
    result = rebuild_chapter_xhtml(
        source_xhtml,
        records,
        [
            {
                "block_id": "ch001_blk001",
                "parent_block_id": "ch001_blk001",
                "final_output": "Hello ⟦B_1⟧world⟦/B_1⟧.",
            }
        ],
        placeholder_map,
    )

    assert result.status == "success"
    assert "⟦B_1⟧" not in result.xhtml
    assert "<b>world</b>" in result.xhtml


def test_rebuild_chapter_xhtml_reassembles_segments() -> None:
    source_xhtml = '<html xmlns="http://www.w3.org/1999/xhtml"><body><p>很长。</p></body></html>'
    records = [
        {
            "chapter_number": 1,
            "source_document_path": "OEBPS/chapter1.xhtml",
            "block_id": "ch001_blk001_seg01",
            "parent_block_id": "ch001_blk001",
            "block_order": 1,
            "segment_order": 1,
        },
        {
            "chapter_number": 1,
            "source_document_path": "OEBPS/chapter1.xhtml",
            "block_id": "ch001_blk001_seg02",
            "parent_block_id": "ch001_blk001",
            "block_order": 1,
            "segment_order": 2,
        },
    ]
    result = rebuild_chapter_xhtml(
        source_xhtml,
        records,
        [
            {
                "block_id": "ch001_blk001_seg02", "parent_block_id": "ch001_blk001",
                "segment_order": 2, "restored_text_en": " two.",
            },
            {
                "block_id": "ch001_blk001_seg01", "parent_block_id": "ch001_blk001",
                "segment_order": 1, "restored_text_en": "Part",
            },
        ],
        {},
    )

    assert "Part two." in result.xhtml
