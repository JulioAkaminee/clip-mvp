"""Testes de CLI (SPEC §11)."""

from __future__ import annotations

import json
import time
from pathlib import Path

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


def _write_status(work_dir: Path, job_id: str, *, age_s: float, status: str = "running") -> None:
    job_dir = work_dir / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "status.json").write_text(
        json.dumps(
            {
                "job_id": job_id,
                "status": status,
                "stage": "render",
                "stage_label": "Renderizando cortes",
                "percent": 71.0,
                "eta_text": "~1.5 min restantes",
                "clips_done": 1,
                "clips_total": 3,
                "updated_at": time.time() - age_s,
                "error": None,
            }
        ),
        encoding="utf-8",
    )


class TestStatusIsHonestAboutDeadJobs:
    """A API já mostrava "interrompido"; o terminal mostrava `running` para sempre.

    Um job morto (kill, reboot, laptop fechado no meio do render) não reescreve
    mais o `status.json`, então o frescor do arquivo é o que separa "morreu" de
    "está vivo em outro processo".
    """

    def test_a_dead_job_is_reported_as_interrupted(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        monkeypatch.setenv("CLIP_WORK_DIR", str(tmp_path / "work"))
        _write_status(tmp_path / "work", "job_dead", age_s=900.0)

        result = runner.invoke(app, ["status", "job_dead"])

        assert result.exit_code == 0
        assert "interrompido" in result.output
        assert "resume" in result.output

    def test_a_job_alive_in_another_process_still_shows_its_eta(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        monkeypatch.setenv("CLIP_WORK_DIR", str(tmp_path / "work"))
        _write_status(tmp_path / "work", "job_live", age_s=2.0)

        result = runner.invoke(app, ["status", "job_live"])

        assert result.exit_code == 0
        assert "min restantes" in result.output
        assert "interrompido" not in result.output

    def test_the_job_list_marks_it_too(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        monkeypatch.setenv("CLIP_WORK_DIR", str(tmp_path / "work"))
        _write_status(tmp_path / "work", "job_dead", age_s=900.0)

        result = runner.invoke(app, ["status"])

        assert result.exit_code == 0
        assert "error" in result.output

    def test_a_corrupt_status_file_does_not_crash(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        monkeypatch.setenv("CLIP_WORK_DIR", str(tmp_path / "work"))
        job_dir = tmp_path / "work" / "job_bad"
        job_dir.mkdir(parents=True)
        (job_dir / "status.json").write_text("{ truncado", encoding="utf-8")

        result = runner.invoke(app, ["status", "job_bad"])

        assert result.exit_code == 1
        assert "ainda não registrou progresso" in result.output
