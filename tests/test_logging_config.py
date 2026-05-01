from __future__ import annotations

import json
from pathlib import Path

from loguru import logger

from resemantica.logging_config import configure_logging


def test_configure_logging_verbosity_zero_shows_warning_only(tmp_path: Path, capsys) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()

    configure_logging(verbosity=0, artifacts_dir=artifacts, run_id="verbosity-zero")
    logger.info("hidden info")
    logger.warning("visible warning")

    captured = capsys.readouterr().err
    assert "visible warning" in captured
    assert "hidden info" not in captured


def test_configure_logging_verbosity_one_shows_info(tmp_path: Path, capsys) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()

    configure_logging(verbosity=1, artifacts_dir=artifacts, run_id="verbosity-one")
    logger.info("visible info")
    logger.debug("hidden debug")

    captured = capsys.readouterr().err
    assert "visible info" in captured
    assert "hidden debug" not in captured


def test_configure_logging_verbosity_two_shows_info_not_debug(tmp_path: Path, capsys) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()

    configure_logging(verbosity=2, artifacts_dir=artifacts, run_id="verbosity-two")
    logger.info("visible info")
    logger.debug("hidden debug")

    captured = capsys.readouterr().err
    assert "visible info" in captured
    assert "hidden debug" not in captured


def test_configure_logging_verbosity_three_shows_debug(tmp_path: Path, capsys) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()

    configure_logging(verbosity=3, artifacts_dir=artifacts, run_id="verbosity-three")
    logger.debug("visible debug")

    captured = capsys.readouterr().err
    assert "visible debug" in captured


def test_configure_logging_writes_json_lines(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()

    configure_logging(verbosity=0, artifacts_dir=artifacts, run_id="json-run")
    logger.debug("json debug")

    log_path = artifacts / "logs" / "json-run.jsonl"
    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert lines
    payload = json.loads(lines[-1])
    assert payload["record"]["message"] == "json debug"


def test_configure_logging_skips_json_handler_when_artifacts_dir_missing(tmp_path: Path) -> None:
    artifacts = tmp_path / "missing"

    configure_logging(verbosity=2, artifacts_dir=artifacts, run_id="missing-run")
    logger.debug("console only")

    assert not artifacts.exists()
