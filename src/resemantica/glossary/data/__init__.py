from importlib import resources
from pathlib import Path


def load_data_file(filename: str) -> set[str]:
    """
    Load a text data file from the glossary/data package.
    Returns a set of stripped, non-empty lines.
    """
    try:
        # Python 3.9+ resources.files
        content = resources.files("resemantica.glossary.data").joinpath(filename).read_text(encoding="utf-8")
    except Exception:
        # Fallback to relative path if not installed as package
        path = Path(__file__).parent / filename
        content = path.read_text(encoding="utf-8")

    lines = content.splitlines()
    return {line.strip() for line in lines if line.strip() and not line.startswith("#")}
