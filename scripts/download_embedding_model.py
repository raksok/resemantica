from __future__ import annotations

from pathlib import Path

from resemantica.embedding_models import resolve_embedding_model_path
from resemantica.settings import load_config


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    config = load_config(project_root / "resemantica.toml")
    model_path = resolve_embedding_model_path(config.models.embedding_name, project_root=project_root)
    print(model_path)


if __name__ == "__main__":
    main()
