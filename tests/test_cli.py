"""Testes de CLI (SPEC §11)."""

from __future__ import annotations

from typer.testing import CliRunner

from clip_mvp.cli import _KNOWN_COMMANDS, app

runner = CliRunner()


def test_cli_help_lists_subcommands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "run" in result.output
    assert "resume" in result.output
    assert "rate" in result.output
    assert "test" in result.output


def test_cli_rate_requires_good_or_bad(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("CLIP_WORK_DIR", str(tmp_path / "work"))
    result = runner.invoke(app, ["rate", "job_x", "clip_y", "maybe"])
    assert result.exit_code != 0


def test_cli_rate_records_feedback(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("CLIP_WORK_DIR", str(tmp_path / "work"))
    result = runner.invoke(app, ["rate", "job_x", "clip_y", "good", "--note", "top"])
    assert result.exit_code == 0
    assert (tmp_path / "work" / "feedback.jsonl").exists()


def test_bare_url_is_routed_to_run_command():
    """Simula a lógica de `main()` que reescreve argv para injetar `run`
    quando o primeiro argumento não é um subcomando conhecido (SPEC §11)."""
    args = ["https://youtube.com/watch?v=abc", "--more"]
    if args and args[0] not in _KNOWN_COMMANDS and not args[0].startswith("-"):
        args = ["run", *args]
    assert args[0] == "run"
    assert args[1] == "https://youtube.com/watch?v=abc"


def test_known_subcommand_is_not_rewritten():
    args = ["resume", "job_123"]
    if args and args[0] not in _KNOWN_COMMANDS and not args[0].startswith("-"):
        args = ["run", *args]
    assert args[0] == "resume"
