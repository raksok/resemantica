from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class CompletenessAudit:
    errors: tuple[str, ...]

    @property
    def success(self) -> bool:
        return not self.errors


def audit_final_blocks(
    chapter_records: object,
    translated_blocks: object,
) -> CompletenessAudit:
    errors: list[str] = []
    if not isinstance(chapter_records, list) or not isinstance(translated_blocks, list):
        return CompletenessAudit(("records or translated blocks are malformed",))

    expected: Counter[str] = Counter()
    for index, record in enumerate(chapter_records):
        if not isinstance(record, dict):
            errors.append(f"malformed extracted record at index {index}")
            continue
        parent_id = str(record.get("parent_block_id") or record.get("block_id") or "")
        if not parent_id:
            errors.append(f"extracted record at index {index} has no block mapping")
            continue
        expected[parent_id] += 1

    actual: Counter[str] = Counter()
    for index, block in enumerate(translated_blocks):
        if not isinstance(block, dict):
            errors.append(f"malformed translated block at index {index}")
            continue
        parent_id = str(block.get("parent_block_id") or block.get("block_id") or "")
        if not parent_id:
            errors.append(f"translated block at index {index} has no block mapping")
            continue
        output = block.get("final_output")
        if output is None:
            output = block.get("restored_text_en")
        if output is None:
            output = block.get("output_text_en")
        if not isinstance(output, str) or not output.strip():
            errors.append(f"translated block {parent_id} has empty final output")
        actual[parent_id] += 1

    missing = expected - actual
    extra = actual - expected
    if missing:
        errors.append(f"missing block mappings: {dict(sorted(missing.items()))}")
    if extra:
        errors.append(f"extra block mappings: {dict(sorted(extra.items()))}")
    return CompletenessAudit(tuple(errors))


def audit_chapter_translation(chapter_path: Path, translation_dir: Path) -> CompletenessAudit:
    try:
        chapter_payload = json.loads(chapter_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return CompletenessAudit((f"invalid extracted chapter artifact: {exc}",))

    pass3_path = translation_dir / "pass3.json"
    pass2_path = translation_dir / "pass2.json"
    artifact_path = pass3_path if pass3_path.exists() else pass2_path
    if not artifact_path.exists():
        return CompletenessAudit(("missing pass2/pass3 translated artifact",))
    try:
        payload: dict[str, Any] = json.loads(artifact_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return CompletenessAudit((f"invalid {artifact_path.name} artifact: {exc}",))
    return audit_final_blocks(chapter_payload.get("records"), payload.get("blocks"))
