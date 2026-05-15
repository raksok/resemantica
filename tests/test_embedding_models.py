from __future__ import annotations

from pathlib import Path

from resemantica.embedding_models import (
    CANONICAL_EMBEDDING_MODEL,
    normalize_embedding_model_name,
    resolve_embedding_model_path,
)


def test_legacy_embedding_model_name_normalizes_to_canonical() -> None:
    assert normalize_embedding_model_name("bge-M3") == CANONICAL_EMBEDDING_MODEL


def test_canonical_embedding_model_resolves_under_project_embedding_dir(tmp_path: Path) -> None:
    cached_model = tmp_path / "embedding" / "BAAI" / "bge-m3"
    cached_model.mkdir(parents=True)

    resolved = resolve_embedding_model_path(CANONICAL_EMBEDDING_MODEL, project_root=tmp_path)

    assert resolved == cached_model.resolve()


def test_existing_local_embedding_model_path_is_reused_without_download(tmp_path: Path) -> None:
    local_model = tmp_path / "local-model"
    local_model.mkdir()

    def fail_download(repo_id: str, destination: Path) -> Path:
        raise AssertionError(f"unexpected download for {repo_id} into {destination}")

    resolved = resolve_embedding_model_path(str(local_model), project_root=tmp_path, downloader=fail_download)

    assert resolved == local_model.resolve()


def test_missing_canonical_embedding_model_downloads_to_project_embedding_dir(tmp_path: Path) -> None:
    calls: list[tuple[str, Path]] = []

    def record_download(repo_id: str, destination: Path) -> Path:
        calls.append((repo_id, destination))
        destination.mkdir(parents=True)
        return destination

    resolved = resolve_embedding_model_path(
        CANONICAL_EMBEDDING_MODEL,
        project_root=tmp_path,
        downloader=record_download,
    )

    expected = tmp_path / "embedding" / "BAAI" / "bge-m3"
    assert resolved == expected.resolve()
    assert calls == [(CANONICAL_EMBEDDING_MODEL, expected)]
