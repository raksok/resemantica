from __future__ import annotations

import importlib
import tomllib
from pathlib import Path

from resemantica import cli as cli_mod


def test_rsem_script_alias_targets_cli_main():
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    project = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]
    module_name, function_name = project["scripts"]["rsem"].split(":", maxsplit=1)
    entrypoint = getattr(importlib.import_module(module_name), function_name)

    assert project["scripts"]["rsem"] == "resemantica.cli:main"
    assert entrypoint is cli_mod.main


def test_parser_help_prefers_rsem_prog_name():
    parser = cli_mod._build_parser()

    assert parser.prog == "rsem"
