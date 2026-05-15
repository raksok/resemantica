from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

CANONICAL_EMBEDDING_MODEL = "BAAI/bge-m3"
EMBEDDING_CACHE_DIR = "embedding"

_LEGACY_MODEL_NAMES = {
    "bge-M3": CANONICAL_EMBEDDING_MODEL,
}


def normalize_embedding_model_name(model_name: str) -> str:
    stripped = model_name.strip()
    return _LEGACY_MODEL_NAMES.get(stripped, stripped)


def download_embedding_snapshot(repo_id: str, destination: Path) -> Path:
    from huggingface_hub import snapshot_download

    destination.parent.mkdir(parents=True, exist_ok=True)
    snapshot_download(repo_id=repo_id, local_dir=str(destination))
    return destination


def resolve_embedding_model_path(
    model_name: str,
    *,
    project_root: Path | None = None,
    downloader: Callable[[str, Path], Path] = download_embedding_snapshot,
) -> Path | str:
    normalized = normalize_embedding_model_name(model_name)
    existing_path = Path(normalized).expanduser()
    if existing_path.exists():
        return existing_path.resolve()

    if not _is_huggingface_repo_id(normalized):
        return normalized

    root = (project_root or Path.cwd()).resolve()
    local_path = root / EMBEDDING_CACHE_DIR / Path(*normalized.split("/"))
    if local_path.exists():
        return local_path.resolve()

    return downloader(normalized, local_path).resolve()


def _is_huggingface_repo_id(model_name: str) -> bool:
    if "\\" in model_name:
        return False
    if model_name.startswith((".", "~", "/")):
        return False
    parts = model_name.split("/")
    return len(parts) == 2 and all(part.strip() for part in parts)
