from __future__ import annotations

from resemantica import cli as cli_mod
from resemantica.cli import _build_parser, _parse_and_resolve


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
            "extract", "ext",
            "translate", "tra",
            "preprocess", "pre",
            "packets", "pac",
            "rebuild", "reb",
            "run",
            "tui",
        }
        assert commands == expected, f"Missing: {expected - commands}, Extra: {commands - expected}"

    def test_extract_alias(self):
        args = _parse_and_resolve(["ext", "--input", "test.epub", "--release", "r1"])
        assert args.command == "extract"

    def test_translate_alias(self):
        args = _parse_and_resolve(["tra", "--release", "r1", "--run", "r1", "--chapter", "3"])
        assert args.command == "translate"
        assert args.chapter == 3

    def test_preprocess_alias(self):
        args = _parse_and_resolve(["pre", "glossary-discover", "--release", "r1"])
        assert args.command == "preprocess"
        assert args.preprocess_command == "glossary-discover"

    def test_packets_alias(self):
        args = _parse_and_resolve(["pac", "build", "--release", "r1", "--chapter", "5"])
        assert args.command == "packets"
        assert args.packets_command == "build"

    def test_rebuild_alias(self):
        args = _parse_and_resolve(["reb", "--release", "r1"])
        assert args.command == "rebuild"

    def test_glossary_discover_alias(self):
        args = _parse_and_resolve(["pre", "gls-discover", "--release", "r1"])
        assert args.command == "preprocess"
        assert args.preprocess_command == "glossary-discover"

    def test_glossary_translate_alias(self):
        args = _parse_and_resolve(["pre", "gls-translate", "--release", "r1"])
        assert args.preprocess_command == "glossary-translate"

    def test_glossary_review_alias(self):
        args = _parse_and_resolve(["pre", "gls-review", "--release", "r1"])
        assert args.preprocess_command == "glossary-review"

    def test_glossary_promote_alias(self):
        args = _parse_and_resolve(["pre", "gls-promote", "--release", "r1"])
        assert args.preprocess_command == "glossary-promote"

    def test_summaries_alias(self):
        args = _parse_and_resolve(["pre", "sum", "--release", "r1"])
        assert args.preprocess_command == "summaries"

    def test_idiom_review_alias(self):
        args = _parse_and_resolve(["pre", "idi-review", "--release", "r1"])
        assert args.preprocess_command == "idiom-review"

    def test_idiom_promote_alias(self):
        args = _parse_and_resolve(["pre", "idi-promote", "--release", "r1"])
        assert args.preprocess_command == "idiom-promote"

    def test_production_alias(self):
        args = _parse_and_resolve(["run", "prod", "--release", "r1"])
        assert args.run_command == "production"

    def test_cleanup_plan_alias(self):
        args = _parse_and_resolve(["run", "cln-plan", "--release", "r1"])
        assert args.run_command == "cleanup-plan"

    def test_cleanup_apply_alias(self):
        args = _parse_and_resolve(["run", "cln-apply", "--release", "r1", "--force"])
        assert args.run_command == "cleanup-apply"
        assert args.force is True

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
        args = parser.parse_args(
            ["tui", "--release", "r1", "--run", "test-run", "--start", "2", "--end", "5"]
        )
        assert args.command == "tui"
        assert args.release == "r1"
        assert args.run == "test-run"
        assert args.start == 2
        assert args.end == 5

    def test_tui_launches_without_bounds_flags(self, monkeypatch):
        captured = {}

        def fake_run(self):
            captured["release_id"] = self.release_id
            captured["run_id"] = self.run_id
            captured["chapter_start"] = self.session.chapter_start
            captured["chapter_end"] = self.session.chapter_end

        monkeypatch.setattr("resemantica.tui.app.ResemanticaApp.run", fake_run)

        result = cli_mod.main(["tui"])

        assert result == 0
        assert captured == {
            "release_id": None,
            "run_id": None,
            "chapter_start": None,
            "chapter_end": None,
        }

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

    def test_main_wires_verbose_to_cli_progress(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        captured = {}

        class FakeSubscriber:
            def __init__(self, *, verbosity=0, **kwargs):
                captured["verbosity"] = verbosity

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return None

        class FakeResult:
            success = True
            stopped = False
            message = "ok"

        monkeypatch.setattr(cli_mod, "CliProgressSubscriber", FakeSubscriber)
        monkeypatch.setattr(cli_mod, "configure_logging", lambda **kwargs: None)
        monkeypatch.setattr(
            "resemantica.orchestration.runner.OrchestrationRunner.run_stage",
            lambda self, *args, **kwargs: FakeResult(),
        )

        result = cli_mod.main(
            ["translate-range", "--release", "r1", "--run", "run-1", "--start", "1", "--end", "1", "-vvv"]
        )

        assert result == 0
        assert captured["verbosity"] == 3

    # --- Short flag tests ---

    def test_extract_short_flags(self):
        args = _parse_and_resolve(["ext", "-i", "book.epub", "-r", "r1"])
        assert args.input.name == "book.epub"
        assert args.release == "r1"

    def test_translate_short_flags(self):
        args = _parse_and_resolve(["tra", "-r", "r1", "-R", "run-1", "-C", "3"])
        assert args.command == "translate"
        assert args.release == "r1"
        assert args.run == "run-1"
        assert args.chapter == 3

    def test_glossary_discover_short_flags(self):
        args = _parse_and_resolve(["pre", "gls-discover", "-r", "r1", "-p", "0.5"])
        assert args.pruning_threshold == 0.5

    def test_glossary_promote_short_flags(self):
        args = _parse_and_resolve(["pre", "gls-promote", "-r", "r1", "-F", "review.json"])
        assert args.review_file.name == "review.json"

    def test_production_short_flags(self):
        args = _parse_and_resolve(["run", "prod", "-r", "r1", "-n"])
        assert args.dry_run is True

    def test_run_resume_short_flags(self):
        args = _parse_and_resolve(["run", "resume", "-r", "r1", "-t", "translate-chapter"])
        assert args.from_stage == "translate-chapter"

    def test_cleanup_plan_short_flags(self):
        args = _parse_and_resolve(["run", "cln-plan", "-r", "r1", "-S", "translation"])
        assert args.scope == "translation"

    def test_cleanup_apply_short_flags(self):
        args = _parse_and_resolve(["run", "cln-apply", "-r", "r1", "-S", "all", "-f"])
        assert args.scope == "all"
        assert args.force is True

    def test_chapter_scope_short_flags(self):
        args = _parse_and_resolve(["tra", "-r", "r1", "-R", "r1", "-s", "1", "-e", "10"])
        assert args.start == 1
        assert args.end == 10

    def test_batched_model_order_short_flag(self):
        args = _parse_and_resolve(["tra", "-r", "r1", "-R", "r1", "-C", "3", "-b"])
        assert args.batched_model_order is True

    def test_tui_short_flags(self):
        args = _parse_and_resolve(["tui", "-r", "r1", "-R", "run-1", "-s", "2", "-e", "5"])
        assert args.release == "r1"
        assert args.run == "run-1"
        assert args.start == 2
        assert args.end == 5
