from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from resemantica.tracking.models import Event

ObservabilitySource = Literal["live", "persisted", "log"]
ObservabilityVerbosity = Literal["normal", "verbose", "debug"]
ObservabilitySourceFilter = Literal["all", "live", "persisted", "logs"]
ObservabilitySeverityFilter = Literal["all", "warnings/errors", "errors"]


@dataclass(frozen=True)
class ObservabilityCounters:
    warnings: int = 0
    failures: int = 0
    skips: int = 0
    retries: int = 0
    artifacts: int = 0


@dataclass(frozen=True)
class ObservabilityRecord:
    source: ObservabilitySource
    timestamp: str
    severity: str
    stage_name: str | None
    event_type: str | None
    logger_name: str | None
    message: str
    chapter_number: int | None
    block_id: str | None
    metadata: dict[str, object]


@dataclass(frozen=True)
class ObservabilitySnapshot:
    counters: ObservabilityCounters
    latest_failure: ObservabilityRecord | None
    live_records: list[ObservabilityRecord]
    persisted_records: list[ObservabilityRecord]
    log_records: list[ObservabilityRecord]


def event_to_record(event: Event, *, source: ObservabilitySource) -> ObservabilityRecord:
    return ObservabilityRecord(
        source=source,
        timestamp=event.event_time,
        severity=(event.severity or "info").lower(),
        stage_name=event.stage_name or None,
        event_type=event.event_type or None,
        logger_name=None,
        message=event.message or "",
        chapter_number=event.chapter_number,
        block_id=event.block_id,
        metadata=dict(event.payload or {}),
    )


def parse_loguru_jsonl_line(line: str) -> ObservabilityRecord | None:
    stripped = line.strip()
    if not stripped:
        return None
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None

    record = payload.get("record")
    if not isinstance(record, dict):
        return None

    timestamp = _log_timestamp(record.get("time"))
    level = _log_level_name(record.get("level"))
    message = _as_str(payload.get("text")) or _as_str(record.get("message")) or ""
    extra = record.get("extra")
    extra_dict = extra if isinstance(extra, dict) else {}
    chapter_number = _coerce_int(extra_dict.get("chapter_number"))
    stage_name = _as_str(extra_dict.get("stage_name"))
    block_id = _as_str(extra_dict.get("block_id"))
    event_type = _as_str(extra_dict.get("event_type"))

    metadata: dict[str, object] = {}
    if extra_dict:
        metadata["extra"] = dict(extra_dict)
    file_info = record.get("file")
    if isinstance(file_info, dict):
        file_name = _as_str(file_info.get("name"))
        if file_name:
            metadata["file"] = file_name
    function_name = _as_str(record.get("function"))
    if function_name:
        metadata["function"] = function_name
    line_number = record.get("line")
    if isinstance(line_number, int):
        metadata["line"] = line_number

    return ObservabilityRecord(
        source="log",
        timestamp=timestamp,
        severity=level.lower(),
        stage_name=stage_name,
        event_type=event_type,
        logger_name=_as_str(record.get("name")),
        message=message,
        chapter_number=chapter_number,
        block_id=block_id,
        metadata=metadata,
    )


def load_log_records(path: Path, *, limit: int = 100) -> list[ObservabilityRecord]:
    if not path.exists():
        return []

    lines: deque[str] = deque(maxlen=max(1, limit))
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            lines.append(line)

    records = [record for line in lines if (record := parse_loguru_jsonl_line(line)) is not None]
    records.sort(key=_sort_key, reverse=True)
    return records


def dedupe_event_records(records: list[ObservabilityRecord]) -> list[ObservabilityRecord]:
    deduped: list[ObservabilityRecord] = []
    seen: set[tuple[str, str | None, str | None, int | None, str | None, str]] = set()
    for record in records:
        key = (
            record.timestamp,
            record.event_type,
            record.stage_name,
            record.chapter_number,
            record.block_id,
            record.message,
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(record)
    deduped.sort(key=_sort_key, reverse=True)
    return deduped


def build_counters(records: list[ObservabilityRecord]) -> ObservabilityCounters:
    warning_count = 0
    failure_count = 0
    skip_count = 0
    retry_count = 0
    artifact_count = 0
    for record in records:
        signal_text = _signal_text(record)
        event_name = (record.event_type or "").lower()
        severity = record.severity.lower()

        if (
            severity == "warning"
            or event_name in {"validation_failed", "risk_detected"}
            or event_name.endswith(".validation_failed")
        ):
            warning_count += 1
        if severity == "error" or "fail" in signal_text:
            failure_count += 1
        if event_name.endswith("_skipped") or event_name.endswith(".chapter_skipped"):
            skip_count += 1
        if event_name.endswith("_retry") or event_name.endswith(".retry") or "retry" in signal_text:
            retry_count += 1
        if event_name == "artifact_written" or event_name.endswith(".artifact_written"):
            artifact_count += 1

    return ObservabilityCounters(
        warnings=warning_count,
        failures=failure_count,
        skips=skip_count,
        retries=retry_count,
        artifacts=artifact_count,
    )


def select_latest_failure(records: list[ObservabilityRecord]) -> ObservabilityRecord | None:
    failures = [
        record
        for record in records
        if record.severity.lower() == "error" or "fail" in _signal_text(record)
    ]
    if not failures:
        return None
    return max(failures, key=_sort_key)


def apply_record_filters(
    records: list[ObservabilityRecord],
    *,
    verbosity: ObservabilityVerbosity,
    severity_filter: ObservabilitySeverityFilter,
    stage_filter: str | None = None,
    chapter_filter: int | None = None,
) -> list[ObservabilityRecord]:
    filtered: list[ObservabilityRecord] = []
    for record in records:
        severity = record.severity.lower()
        if verbosity == "normal" and severity not in {"warning", "error"}:
            continue
        if verbosity == "verbose" and severity == "debug":
            continue
        if severity_filter == "warnings/errors" and severity not in {"warning", "error"}:
            continue
        if severity_filter == "errors" and severity != "error":
            continue
        if stage_filter and record.stage_name != stage_filter:
            continue
        if chapter_filter is not None and record.chapter_number != chapter_filter:
            continue
        filtered.append(record)
    return filtered


def build_snapshot(
    *,
    live_events: list[Event],
    persisted_events: list[Event],
    log_records: list[ObservabilityRecord],
) -> ObservabilitySnapshot:
    live_records = [event_to_record(event, source="live") for event in live_events]
    persisted_records = [event_to_record(event, source="persisted") for event in persisted_events]
    deduped_event_records = dedupe_event_records([*live_records, *persisted_records])
    combined_records = [*deduped_event_records, *log_records]
    combined_records.sort(key=_sort_key, reverse=True)
    return ObservabilitySnapshot(
        counters=build_counters(combined_records),
        latest_failure=select_latest_failure(combined_records),
        live_records=sorted(live_records, key=_sort_key, reverse=True),
        persisted_records=sorted(persisted_records, key=_sort_key, reverse=True),
        log_records=sorted(log_records, key=_sort_key, reverse=True),
    )


def available_stage_filters(snapshot: ObservabilitySnapshot) -> list[str]:
    values = {
        record.stage_name
        for record in [
            *snapshot.live_records,
            *snapshot.persisted_records,
            *snapshot.log_records,
        ]
        if record.stage_name
    }
    return sorted(values)


def available_chapter_filters(snapshot: ObservabilitySnapshot) -> list[int]:
    values = {
        record.chapter_number
        for record in [
            *snapshot.live_records,
            *snapshot.persisted_records,
            *snapshot.log_records,
        ]
        if record.chapter_number is not None
    }
    return sorted(values)


def format_record(record: ObservabilityRecord, *, verbosity: ObservabilityVerbosity) -> str:
    source_label = {
        "live": "LIVE",
        "persisted": "DB",
        "log": "LOG",
    }[record.source]
    detail_name = record.event_type or record.logger_name or "-"
    parts = [record.timestamp, source_label, record.severity.upper(), detail_name]
    if record.stage_name:
        parts.append(f"stage={record.stage_name}")
    if record.chapter_number is not None:
        parts.append(f"ch={record.chapter_number}")
    if record.block_id:
        parts.append(f"block={record.block_id}")
    line = " | ".join(parts) + f" | {record.message}"

    if verbosity != "debug" or not record.metadata:
        return line
    return f"{line}\n    meta: {_metadata_snippet(record.metadata)}"


def _sort_key(record: ObservabilityRecord) -> tuple[float, str]:
    parsed = _parse_timestamp(record.timestamp)
    return ((parsed.timestamp() if parsed is not None else 0.0), record.message)


def _parse_timestamp(value: str) -> datetime | None:
    if not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _log_timestamp(raw: object) -> str:
    if isinstance(raw, dict):
        repr_value = _as_str(raw.get("repr"))
        if repr_value:
            parsed = _parse_timestamp(repr_value)
            if parsed is not None:
                return parsed.isoformat()
        timestamp_value = raw.get("timestamp")
        if isinstance(timestamp_value, (int, float)):
            return datetime.fromtimestamp(timestamp_value, tz=timezone.utc).isoformat()
    if isinstance(raw, (int, float)):
        return datetime.fromtimestamp(raw, tz=timezone.utc).isoformat()
    if isinstance(raw, str):
        parsed = _parse_timestamp(raw)
        if parsed is not None:
            return parsed.isoformat()
    return ""


def _log_level_name(raw: object) -> str:
    if isinstance(raw, dict):
        name = _as_str(raw.get("name"))
        if name:
            return name
    return "INFO"


def _coerce_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _as_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _signal_text(record: ObservabilityRecord) -> str:
    parts = [
        record.event_type or "",
        record.logger_name or "",
        record.message or "",
    ]
    return " ".join(parts).lower()


def _metadata_snippet(metadata: dict[str, object], *, max_chars: int = 180) -> str:
    rendered = json.dumps(metadata, ensure_ascii=True, sort_keys=True, default=str)
    if len(rendered) <= max_chars:
        return rendered
    return rendered[: max_chars - 3] + "..."
