from __future__ import annotations

from resemantica import cli as cli_mod
from resemantica.cli import _build_parser


class TestCliDispatch:
    def _get_subcommands(self, parser) -> set[str]:
        subcommands = set()
        for action in parser._actions:
            if hasattr(action, "choices") and action.choices:
                subcommands.update(action.choices.keys())
        return subcommands

    def test_top_level_commands_exist(self):
        parser = _build_parser()
        commands = self._get_subcommands(parser)
        expected = {
            "epub-roundtrip",
            "translate-chapter",
            "preprocess",
            "packets",
            "rebuild-epub",
            "translate-range",
            "run-production",
            "run",
            "tui",
        }
        assert commands == expected, f"Missing: {expected - commands}, Extra: {commands - expected}"

    def test_preprocess_subcommands(self):
        parser = _build_parser()
        args = parser.parse_args(["preprocess", "glossary-discover", "--release", "r1"])
        assert args.command == "preprocess"
        assert args.preprocess_command == "glossary-discover"

    def test_preprocess_translate(self):
        parser = _build_parser()
        args = parser.parse_args(["preprocess", "glossary-translate", "--release", "r1"])
        assert args.preprocess_command == "glossary-translate"

    def test_preprocess_promote(self):
        parser = _build_parser()
        args = parser.parse_args(["preprocess", "glossary-promote", "--release", "r1"])
        assert args.preprocess_command == "glossary-promote"

    def test_preprocess_summaries(self):
        parser = _build_parser()
        args = parser.parse_args(["preprocess", "summaries", "--release", "r1", "-vv"])
        assert args.preprocess_command == "summaries"
        assert args.verbose == 2

    def test_preprocess_idioms(self):
        parser = _build_parser()
        args = parser.parse_args(["preprocess", "idioms", "--release", "r1"])
        assert args.preprocess_command == "idioms"

    def test_preprocess_graph(self):
        parser = _build_parser()
        args = parser.parse_args(["preprocess", "graph", "--release", "r1"])
        assert args.preprocess_command == "graph"

    def test_packets_build(self):
        parser = _build_parser()
        args = parser.parse_args(["packets", "build", "--release", "r1", "--chapter", "5"])
        assert args.command == "packets"
        assert args.packets_command == "build"
        assert args.chapter == 5

    def test_run_production(self):
        parser = _build_parser()
        args = parser.parse_args(["run", "production", "--release", "r1"])
        assert args.run_command == "production"

    def test_top_level_run_production(self):
        parser = _build_parser()
        args = parser.parse_args(
            ["run-production", "--release", "r1", "--dry-run", "--start", "2", "--end", "4"]
        )
        assert args.command == "run-production"
        assert args.dry_run is True
        assert args.start == 2
        assert args.end == 4

    def test_run_resume(self):
        parser = _build_parser()
        args = parser.parse_args(["run", "resume", "--release", "r1", "--from-stage", "translate-chapter"])
        assert args.run_command == "resume"
        assert args.from_stage == "translate-chapter"

    def test_run_cleanup_plan(self):
        parser = _build_parser()
        args = parser.parse_args([
            "run", "cleanup-plan", "--release", "r1",
            "--scope", "translation"
        ])
        assert args.run_command == "cleanup-plan"
        assert args.scope == "translation"

    def test_run_cleanup_apply(self):
        parser = _build_parser()
        args = parser.parse_args([
            "run", "cleanup-apply", "--release", "r1",
            "--scope", "all", "--force"
        ])
        assert args.run_command == "cleanup-apply"
        assert args.scope == "all"
        assert args.force is True

    def test_epub_roundtrip(self):
        parser = _build_parser()
        args = parser.parse_args([
            "epub-roundtrip", "--input", "test.epub", "--release", "r1"
        ])
        assert args.command == "epub-roundtrip"
        assert args.input.name == "test.epub"

    def test_translate_chapter(self):
        parser = _build_parser()
        args = parser.parse_args([
            "translate-chapter", "--release", "r1", "--chapter", "3", "--run", "test-run"
        ])
        assert args.command == "translate-chapter"
        assert args.chapter == 3

    def test_rebuild_epub(self):
        parser = _build_parser()
        args = parser.parse_args(["rebuild-epub", "--release", "r1", "--run-id", "run-1"])
        assert args.command == "rebuild-epub"
        assert args.run_id == "run-1"

    def test_translate_range(self):
        parser = _build_parser()
        args = parser.parse_args([
            "translate-range", "--release", "r1", "--run", "test-run",
            "--start", "1", "--end", "10", "-v"
        ])
        assert args.command == "translate-range"
        assert args.start == 1
        assert args.end == 10
        assert args.verbose == 1

    def test_tui(self):
        parser = _build_parser()
        args = parser.parse_args(["tui", "--release", "r1", "--run", "test-run"])
        assert args.command == "tui"
        assert args.release == "r1"
        assert args.run == "test-run"

    def test_no_verbose_defaults_to_zero(self):
        parser = _build_parser()
        args = parser.parse_args(["packets", "build", "--release", "r1"])
        assert args.verbose == 0

    def test_main_wires_verbose_to_logging_config(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        calls = []

        def fake_configure_logging(**kwargs):
            calls.append(kwargs)

        monkeypatch.setattr(cli_mod, "configure_logging", fake_configure_logging)

        result = cli_mod.main(["run", "production", "--release", "r1", "--dry-run", "-vv"])

        assert result == 0
        assert calls[0]["verbosity"] == 2
        assert calls[0]["run_id"] == "production"
        assert "preprocess-glossary" in capsys.readouterr().out
