"""M14 Pilot: run 10 chapters through the full production pipeline."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path
from xml.etree import ElementTree as ET

from resemantica.epub.extractor import extract_epub
from resemantica.epub.rebuild import rebuild_epub
from resemantica.orchestration import run_stage
from resemantica.orchestration.models import STAGE_ORDER
from resemantica.settings import derive_paths, load_config
from resemantica.translation.pipeline import (
    translate_chapter_pass1,
    translate_chapter_pass2,
    translate_chapter_pass3,
)


_BLOCK_TAGS = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "div", "li", "td", "table"}


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag


def _is_leaf_block(element: ET.Element) -> bool:
    for child in list(element):
        if _local_name(child.tag).lower() in _BLOCK_TAGS:
            return False
    return True


def _get_ns(tag: str) -> str:
    if "}" in tag:
        return tag.split("}")[0][1:]
    return ""


def _discover_xhtml_map(unpacked_dir: Path) -> dict[int, str]:
    """Map chapter_number -> href (relative to unpacked_dir)."""
    import zipfile
    container = unpacked_dir / "META-INF" / "container.xml"
    tree = ET.parse(str(container))
    root = tree.getroot()
    rootfiles = [
        node for node in root.iter()
        if _local_name(node.tag) == "rootfile"
    ]
    if not rootfiles:
        raise ValueError("OPF rootfile not found")
    full_path = rootfiles[0].attrib.get("full-path")
    if not full_path:
        raise ValueError("rootfile missing full-path")
    opf_path = unpacked_dir / full_path

    opf_tree = ET.parse(str(opf_path))
    opf_root = opf_tree.getroot()
    manifest: dict[str, dict[str, str]] = {}
    spine_ids: list[str] = []
    for node in opf_root.iter():
        tag = _local_name(node.tag)
        if tag == "item":
            item_id = node.attrib.get("id")
            href = node.attrib.get("href")
            media_type = node.attrib.get("media-type", "")
            if item_id and href:
                manifest[item_id] = {"href": href, "media_type": media_type}
        elif tag == "itemref":
            idref = node.attrib.get("idref")
            if idref:
                spine_ids.append(idref)

    xhtml_mime = {"application/xhtml+xml", "application/x-dtbncx+xml"}
    opf_dir = opf_path.parent
    chapter_map: dict[int, str] = {}
    chapter_number = 0
    for item_id in spine_ids:
        item = manifest.get(item_id)
        if item is None:
            continue
        href = item["href"]
        mt = item["media_type"]
        suffix = Path(href).suffix.lower()
        if mt not in xhtml_mime and suffix not in {".xhtml", ".html", ".htm"}:
            continue
        chapter_number += 1
        chapter_map[chapter_number] = (opf_dir / href).resolve().relative_to(unpacked_dir).as_posix()
    return chapter_map


def _build_chapter_xhtml_map(
    unpacked_dir: Path,
    chapter_map: dict[int, str],
) -> dict[int, list[dict]]:
    """For each chapter, build a list of {block_id, source_text_zh, xhtml_idx} mapping blocks to XHTML element positions."""
    result: dict[int, list[dict]] = {}
    for ch_num, href in chapter_map.items():
        xhtml_path = unpacked_dir / href
        if not xhtml_path.exists():
            continue
        tree = ET.parse(str(xhtml_path))
        root = tree.getroot()
        all_els = list(root.iter())
        block_els = [
            el for el in all_els
            if _local_name(el.tag).lower() in _BLOCK_TAGS and _is_leaf_block(el)
        ]
        result[ch_num] = []
        for idx, el in enumerate(block_els):
            parts: list[str] = []
            if el.text:
                parts.append(el.text)
            for child in list(el):
                if child.tail:
                    parts.append(child.tail)
            result[ch_num].append({
                "block_id": f"ch{ch_num:03d}_blk{idx + 1:03d}",
                "source_text_zh": "".join(parts),
                "xhtml_idx": idx,
            })
    return result


def inject_translations(
    unpacked_dir: Path,
    chapter_map: dict[int, str],
    pass2_by_chapter: dict[int, list[dict]],
) -> list[str]:
    """Inject pass2 restored_text_en back into the unpacked XHTML files."""
    warnings: list[str] = []

    for ch_num, href in chapter_map.items():
        xhtml_path = (unpacked_dir / href).resolve()
        if not xhtml_path.exists():
            warnings.append(f"XHTML not found: {xhtml_path}")
            continue

        blocks = pass2_by_chapter.get(ch_num)
        if not blocks:
            continue

        tree = ET.parse(str(xhtml_path))
        root = tree.getroot()
        all_els = list(root.iter())
        block_els = [
            el for el in all_els
            if _local_name(el.tag).lower() in _BLOCK_TAGS and _is_leaf_block(el)
        ]

        if len(block_els) != len(blocks):
            warnings.append(
                f"Chapter {ch_num}: XHTML has {len(block_els)} blocks, translation has {len(blocks)}"
            )

        ns = _get_ns(block_els[0].tag) if block_els else ""

        for idx, (element, block) in enumerate(zip(block_els, blocks)):
            restored = block.get("restored_text_en", "")
            if not restored:
                continue
            try:
                if ns:
                    frag_xml = f"<_root xmlns=\"{ns}\">{restored}</_root>"
                else:
                    frag_xml = f"<_root>{restored}</_root>"
                frag_root = ET.fromstring(frag_xml)
            except ET.ParseError as exc:
                warnings.append(f"Ch{ch_num} block{idx}: XML parse error: {exc}")
                continue

            tag = element.tag
            attrib = element.attrib.copy()
            element.clear()
            element.tag = tag
            element.attrib.update(attrib)
            element.text = frag_root.text or ""
            for child in list(frag_root):
                element.append(child)

        tree.write(str(xhtml_path), xml_declaration=True, encoding="utf-8")

    return warnings


def _load_pass2_blocks(pass2_path: Path) -> list[dict]:
    if not pass2_path.exists():
        return []
    payload = json.loads(pass2_path.read_text(encoding="utf-8"))
    return list(payload.get("blocks", []))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="M14 Pilot: run full production pipeline")
    parser.add_argument("--release", required=True, help="Release identifier")
    parser.add_argument("--input", required=True, type=Path, help="Input EPUB path")
    parser.add_argument("--start", type=int, default=1, help="Starting chapter")
    parser.add_argument("--end", type=int, default=10, help="Ending chapter (inclusive)")
    parser.add_argument("--run", default="pilot-01", help="Run identifier")
    parser.add_argument("--config", type=Path, default=None, help="Path to resemantica.toml")
    parser.add_argument("--skip-preprocess", action="store_true", help="Skip preprocessing stages")
    parser.add_argument("--skip-translate", action="store_true", help="Skip translation")
    args = parser.parse_args(argv)

    config = load_config(args.config)
    paths = derive_paths(config, release_id=args.release)
    report: dict = {
        "pilot": {
            "release_id": args.release,
            "run_id": args.run,
            "input_epub": str(args.input),
            "chapter_range": {"start": args.start, "end": args.end},
        },
        "stages": {},
        "warnings": [],
        "errors": [],
        "summary": {},
    }

    overall_start = time.time()

    # 1. Extract EPUB
    print(f"\n{'='*60}")
    print(f"Step 1: Extract EPUB from {args.input}")
    print(f"{'='*60}")
    t0 = time.time()
    try:
        roundtrip = extract_epub(input_path=args.input, release_id=args.release, config=config)
        report["stages"]["extract"] = {
            "status": "success",
            "duration_s": round(time.time() - t0, 2),
            "release_root": str(roundtrip.release_root),
        }
        print(f"  Release root: {roundtrip.release_root}")
        print(f"  Chapters: {len(roundtrip.chapter_results)}")
    except Exception as exc:
        report["stages"]["extract"] = {"status": "failed", "error": str(exc)}
        print(f"  FAILED: {exc}")
        return 1

    # Discover XHTML mapping from unpacked dir
    unpacked_dir = paths.unpacked_dir
    chapter_map = _discover_xhtml_map(unpacked_dir)
    print(f"  Discovered {len(chapter_map)} XHTML chapters")

    # 2. Preprocessing stages
    if not args.skip_preprocess:
        preprocess_stages = [s for s in STAGE_ORDER if s.startswith("preprocess-") or s == "packets-build"]
        for stage_name in preprocess_stages:
            print(f"\n{'='*60}")
            print(f"Step 2: Stage: {stage_name}")
            print(f"{'='*60}")
            t0 = time.time()
            result = run_stage(args.release, args.run, stage_name)
            duration = round(time.time() - t0, 2)
            report["stages"][stage_name] = {
                "status": "success" if result.success else "failed",
                "duration_s": duration,
                "message": result.message,
            }
            if result.success:
                print(f"  OK ({duration}s)")
            else:
                print(f"  FAILED: {result.message}")
                report["errors"].append(f"{stage_name}: {result.message}")

    # 3. Translate chapters — 3-phase execution
    chapter_warnings: list[str] = []
    failed_chapters: list[int] = []
    pass2_by_chapter: dict[int, list[dict]] = {}

    if not args.skip_translate:
        print(f"\n{'='*60}")
        print(f"Phase 1: Pass 1 (translator model) for chapters {args.start}-{args.end}")
        print(f"{'='*60}")
        pass1_failures: list[int] = []
        for ch in range(args.start, args.end + 1):
            print(f"  Chapter {ch}...", end=" ")
            sys.stdout.flush()
            t0 = time.time()
            try:
                result = translate_chapter_pass1(
                    release_id=args.release,
                    chapter_number=ch,
                    run_id=args.run,
                    config=config,
                )
                dur = round(time.time() - t0, 2)
                print(f"{result['status']} ({dur}s)")
            except Exception as exc:
                dur = round(time.time() - t0, 2)
                print(f"FAILED ({dur}s): {exc}")
                pass1_failures.append(ch)

        print(f"\n{'='*60}")
        print(f"Phase 2: Pass 2 (analyst model) for chapters {args.start}-{args.end}")
        print(f"{'='*60}")
        pass2_failures: list[int] = []
        for ch in range(args.start, args.end + 1):
            if ch in pass1_failures:
                print(f"  Chapter {ch}: SKIPPED (pass1 failed)")
                failed_chapters.append(ch)
                continue
            print(f"  Chapter {ch}...", end=" ")
            sys.stdout.flush()
            t0 = time.time()
            try:
                result = translate_chapter_pass2(
                    release_id=args.release,
                    chapter_number=ch,
                    run_id=args.run,
                    config=config,
                )
                dur = round(time.time() - t0, 2)
                print(f"{result['status']} ({dur}s)")
                pass2_path = Path(result["pass2_artifact"])
                blocks = _load_pass2_blocks(pass2_path)
                if blocks:
                    pass2_by_chapter[ch] = blocks
            except Exception as exc:
                dur = round(time.time() - t0, 2)
                print(f"FAILED ({dur}s): {exc}")
                pass2_failures.append(ch)
                failed_chapters.append(ch)

        if config.translation.pass3_default:
            print(f"\n{'='*60}")
            print(f"Phase 3: Pass 3 (analyst model) for chapters {args.start}-{args.end}")
            print(f"{'='*60}")
            for ch in range(args.start, args.end + 1):
                if ch in pass1_failures:
                    continue
                print(f"  Chapter {ch}...", end=" ")
                sys.stdout.flush()
                t0 = time.time()
                try:
                    result = translate_chapter_pass3(
                        release_id=args.release,
                        chapter_number=ch,
                        run_id=args.run,
                        config=config,
                    )
                    dur = round(time.time() - t0, 2)
                    print(f"{result['status']} ({dur}s)")
                except Exception as exc:
                    dur = round(time.time() - t0, 2)
                    print(f"FAILED ({dur}s): {exc}")
        else:
            print(f"\n  Pass 3: disabled (config.translation.pass3_default = false)")

        total = args.end - args.start + 1
        succeeded = total - len(failed_chapters)
        report["stages"]["translate"] = {
            "chapters_requested": total,
            "chapters_succeeded": succeeded,
            "chapters_failed": len(failed_chapters),
            "failed_chapters": failed_chapters,
            "pass1_failures": pass1_failures,
            "pass2_failures": pass2_failures,
            "pass3_enabled": config.translation.pass3_default,
        }

    # 4. Inject translations into XHTML
    if pass2_by_chapter:
        print(f"\n{'='*60}")
        print("Step 4: Inject translations into XHTML files")
        print(f"{'='*60}")
        inj_warnings = inject_translations(unpacked_dir, chapter_map, pass2_by_chapter)
        for w in inj_warnings:
            print(f"  WARN: {w}")
        chapter_warnings.extend(inj_warnings)

    # 5. Rebuild EPUB
    print(f"\n{'='*60}")
    print("Step 5: Rebuild EPUB")
    print(f"{'='*60}")
    t0 = time.time()
    try:
        output_epub = rebuild_epub(unpacked_dir, paths.rebuilt_epub_path)
        dur = round(time.time() - t0, 2)
        print(f"  Rebuilt EPUB: {output_epub} ({dur}s)")
        report["stages"]["rebuild"] = {"status": "success", "duration_s": dur, "output": str(output_epub)}
    except Exception as exc:
        report["stages"]["rebuild"] = {"status": "failed", "error": str(exc)}
        print(f"  FAILED: {exc}")
        report["errors"].append(f"rebuild: {exc}")

    # 6. Summary
    overall_duration = round(time.time() - overall_start, 2)
    print(f"\n{'='*60}")
    print("Pilot Summary")
    print(f"{'='*60}")
    success = len(report["errors"]) == 0
    summary = {
        "overall_status": "success" if success else "failed",
        "overall_duration_s": overall_duration,
        "stages_executed": len(report["stages"]),
        "stages_failed": sum(1 for s in report["stages"].values() if s.get("status") == "failed"),
        "translate_failed_count": len(failed_chapters),
        "injection_warnings": len(chapter_warnings),
    }
    report["summary"] = summary

    print(f"  Status: {summary['overall_status']}")
    print(f"  Duration: {overall_duration}s")
    print(f"  Stages: {summary['stages_executed']} total, {summary['stages_failed']} failed")
    print(f"  Translate failures: {summary['translate_failed_count']}")
    print(f"  Injection warnings: {summary['injection_warnings']}")

    # Write report
    report_path = paths.release_root / "pilot-report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  Pilot report: {report_path}")

    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
