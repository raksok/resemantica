from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path

LLM_CACHE_SCHEMA_VERSION = "1.0"


@dataclass(slots=True)
class LLMCacheIdentity:
    release_id: str
    chapter_number: int
    source_hash: str
    stage_name: str
    chunk_index: int
    model_name: str
    prompt_version: str
    prompt_hash: str
    schema_version: str = LLM_CACHE_SCHEMA_VERSION


def hash_prompt(prompt: str) -> str:
    return sha256(prompt.encode("utf-8")).hexdigest()


def _identity_hash(identity: LLMCacheIdentity) -> str:
    payload = json.dumps(asdict(identity), sort_keys=True, ensure_ascii=False)
    return sha256(payload.encode("utf-8")).hexdigest()


def cache_path(cache_root: Path, identity: LLMCacheIdentity) -> Path:
    filename = f"chapter-{identity.chapter_number}-chunk-{identity.chunk_index}-{_identity_hash(identity)[:24]}.json"
    return cache_root / identity.stage_name / filename


def load_cached_text(cache_root: Path, identity: LLMCacheIdentity) -> str | None:
    path = cache_path(cache_root, identity)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("identity") != asdict(identity):
        return None
    raw_output = payload.get("raw_output")
    return raw_output if isinstance(raw_output, str) else None


def save_cached_text(cache_root: Path, identity: LLMCacheIdentity, raw_output: str) -> Path:
    path = cache_path(cache_root, identity)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "identity": asdict(identity),
                "raw_output": raw_output,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return path
