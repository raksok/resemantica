from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class PromptTemplate:
    name: str
    version: str
    template: str


def _prompts_root() -> Path:
    return Path(__file__).resolve().parent / "prompts"


def load_prompt(prompt_name: str) -> PromptTemplate:
    prompt_path = _prompts_root() / prompt_name
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_path}")

    content = prompt_path.read_text(encoding="utf-8")
    lines = content.splitlines()
    if not lines:
        raise ValueError(f"Prompt file is empty: {prompt_name}")

    header = lines[0].strip()
    prefix = "# version:"
    if not header.lower().startswith(prefix):
        raise ValueError(f"Prompt file missing version header: {prompt_name}")

    version = header[len(prefix) :].strip()
    if not version:
        raise ValueError(f"Prompt version is empty: {prompt_name}")

    template = "\n".join(lines[1:]).lstrip("\n")
    return PromptTemplate(name=prompt_name, version=version, template=template)


def render_named_sections(template: str, sections: dict[str, str]) -> str:
    return template.format(**sections)

