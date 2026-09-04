from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from resemantica.utils import _write_json


def test_write_json_atomically_replaces_existing_artifact(tmp_path: Path) -> None:
    path = tmp_path / "artifact.json"
    path.write_text('{"status": "old"}', encoding="utf-8")

    _write_json(path, {"status": "success", "text": "中文"})

    assert json.loads(path.read_text(encoding="utf-8")) == {
        "status": "success",
        "text": "中文",
    }
    assert list(tmp_path.glob(".artifact.json.*.tmp")) == []


def test_write_json_replace_failure_preserves_existing_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "artifact.json"
    original = b'{"status": "old"}'
    path.write_bytes(original)

    def fail_replace(source: str | bytes | os.PathLike[str] | os.PathLike[bytes], destination: object) -> None:
        raise OSError(f"replace failed for {source} -> {destination}")

    monkeypatch.setattr(os, "replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        _write_json(path, {"status": "new"})

    assert path.read_bytes() == original
    assert list(tmp_path.glob(".artifact.json.*.tmp")) == []


def test_write_json_sync_failure_preserves_existing_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "artifact.json"
    original = b'{"status": "old"}'
    path.write_bytes(original)

    def fail_fsync(file_descriptor: int) -> None:
        raise OSError(f"sync failed for {file_descriptor}")

    monkeypatch.setattr(os, "fsync", fail_fsync)

    with pytest.raises(OSError, match="sync failed"):
        _write_json(path, {"status": "new"})

    assert path.read_bytes() == original
    assert list(tmp_path.glob(".artifact.json.*.tmp")) == []


def test_write_json_serialization_failure_preserves_existing_artifact(tmp_path: Path) -> None:
    path = tmp_path / "artifact.json"
    original = b'{"status": "old"}'
    path.write_bytes(original)

    with pytest.raises(TypeError):
        _write_json(path, {"invalid": object()})

    assert path.read_bytes() == original
    assert list(tmp_path.glob(".artifact.json.*.tmp")) == []
