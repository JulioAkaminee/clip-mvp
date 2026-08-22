"""Progresso e ETA de ponta a ponta, com o pipeline real rodando.

Os testes de `test_progress.py` cobrem o modelo isolado; aqui a garantia é que
o pipeline de verdade emite os estágios na ordem certa, com percentual
monotônico, ETA sempre presente e status por clipe até o fim.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from clip_mvp import pipeline as pipeline_mod
from clip_mvp.config import Settings
from clip_mvp.download import DownloadResult
from clip_mvp.progress import STAGE_ORDER, ProgressReporter

from test_pipeline import FakeOpenRouterClient  # noqa: E402  (fixtures compartilhadas)


@pytest.fixture
def fake_client(whisper_verbose_json_raw):
    candidates_payload = {
        "candidates": [
            {
                "title": "Momento com contexto fechado",
                "text_excerpt": "Cê já tentou aquele treino novo? Sim, mas doeu tanto...",
                "window_9x16": {"start": 0.05, "end": 9.85},
                "window_16x9": {"start": 0.05, "end": 9.85},
                "context_complete": True,
                "llm_notes": "",
            }
        ]
    }
    score_payload = {
        "total": 87,
        "breakdown": {"hook": 22, "emocao": 21, "citavel": 23, "arco": 21},
        "context_complete": True,
        "reason": "pergunta + resposta completa",
    }
    meta_payload = {
        "youtube": {
            "shorts_title": "Título Shorts",
            "description": "descrição",
            "tags": ["treino"],
            "hashtags": ["#Shorts"],
        },
        "tiktok": {"caption": "legenda", "hashtags": ["#fyp", "#treino", "#br", "#viral"]},
    }
    return FakeOpenRouterClient(
        whisper_verbose_json_raw, candidates_payload, score_payload, meta_payload
    )


def _patch_download(monkeypatch, sample_video_path: Path):
    def fake_download_source(url, job_dir, *, height=720, on_progress=None):
        job_dir = Path(job_dir)
        job_dir.mkdir(parents=True, exist_ok=True)
        dest = job_dir / "source.mp4"
        shutil.copyfile(sample_video_path, dest)
        if on_progress:
            for fraction in (0.25, 0.5, 0.75, 1.0):
                on_progress(fraction, f"Baixando vídeo… {fraction * 100:.0f}%")
        return DownloadResult(
            video_path=dest,
            info_path=job_dir / "source.info.json",
            title="Fixture BR",
            duration_s=12.0,
            source_url=url,
        )

    monkeypatch.setattr(pipeline_mod, "download_source", fake_download_source)
    monkeypatch.setattr(pipeline_mod, "probe_metadata", lambda url: {"duration": 12.0})


@pytest.fixture
def run(tmp_path, monkeypatch, sample_video_path, fake_client):
    """Roda o pipeline capturando todos os eventos de progresso."""
    _patch_download(monkeypatch, sample_video_path)
    settings = Settings(
        openrouter_api_key="test-key",
        work_dir=tmp_path / "work",
        out_dir=tmp_path / "out",
        min_duration_full_arc_s=0.0,
    )
    events: list[dict] = []
    job_id = "job-progresso"
    reporter = pipeline_mod.make_reporter(settings, job_id, sinks=[events.append])
    summary = pipeline_mod.run_job(
        "https://youtube.com/watch?v=fixture",
        settings,
        pipeline_mod.RunOptions(),
        client=fake_client,
        reporter=reporter,
    )
    return {
        "summary": summary,
        "events": events,
        "snapshot": reporter.snapshot(),
        "settings": settings,
        "job_id": job_id,
    }


class TestStageSequence:
    def test_all_stages_reach_a_terminal_state(self, run):
        for stage in run["snapshot"]["stages"]:
            assert stage["status"] in {"done", "skipped"}, stage

    def test_stages_are_reported_in_pipeline_order(self, run):
        seen: list[str] = []
        for event in run["events"]:
            stage = event["stage"]
            if stage in {"queued", "done"}:
                continue
            if not seen or seen[-1] != stage:
                seen.append(stage)
        assert seen == sorted(seen, key=STAGE_ORDER.index)

    def test_every_pipeline_stage_is_represented(self, run):
        reported = {s["name"] for s in run["snapshot"]["stages"]}
        assert reported == set(STAGE_ORDER)

    def test_download_reports_intermediate_progress(self, run):
        fractions = [
            e["stage_percent"] for e in run["events"] if e["stage"] == "download"
        ]
        assert len([f for f in fractions if 0 < f < 100]) >= 2

    def test_stage_labels_are_ptbr(self, run):
        labels = {s["label"] for s in run["snapshot"]["stages"]}
        assert "Baixando vídeo" in labels
        assert "Renderizando cortes" in labels


class TestPercentAndEta:
    def test_percent_is_monotonic(self, run):
        percents = [e["percent"] for e in run["events"]]
        assert percents == sorted(percents)

    def test_percent_reaches_100(self, run):
        assert run["snapshot"]["percent"] == pytest.approx(100.0, abs=0.01)

    def test_eta_is_present_on_every_running_event(self, run):
        running = [e for e in run["events"] if e["status"] == "running"]
        assert running
        assert all(e["eta_seconds"] is not None for e in running)

    def test_eta_text_is_ptbr_and_mentions_minutes_or_seconds(self, run):
        running = [e for e in run["events"] if e["status"] == "running"]
        assert all("restantes" in e["eta_text"] or "finalizando" in e["eta_text"] for e in running)

    def test_eta_trends_down(self, run):
        etas = [e["eta_seconds"] for e in run["events"] if e["status"] == "running"]
        assert etas[-1] <= etas[0]

    def test_eta_is_zero_at_the_end(self, run):
        assert run["snapshot"]["eta_seconds"] == 0
        assert run["snapshot"]["status"] == "done"


class TestClipProgress:
    def test_clip_counters_complete(self, run):
        snapshot = run["snapshot"]
        assert snapshot["clips_total"] == run["summary"].selected
        assert snapshot["clips_done"] == snapshot["clips_total"]

    def test_each_format_is_reported(self, run):
        clip = run["snapshot"]["clips"][0]
        assert clip["formats"]
        assert set(clip["formats"]) <= {
            "vertical_facetrack",
            "vertical_center",
            "horizontal_16x9",
        }
        assert all(state == "done" for state in clip["formats"].values())

    def test_clip_carries_its_score(self, run):
        assert run["snapshot"]["clips"][0]["score"] is not None


class TestPersistence:
    def test_status_json_is_written_for_polling(self, run):
        path = run["settings"].work_dir / run["job_id"] / "status.json"
        status = json.loads(path.read_text("utf-8"))
        assert status["status"] == "done"
        assert status["percent"] == pytest.approx(100.0, abs=0.01)

    def test_events_jsonl_is_appended(self, run):
        path = run["settings"].work_dir / run["job_id"] / "events.jsonl"
        lines = path.read_text("utf-8").strip().splitlines()
        assert len(lines) > 5
        assert all("eta_seconds" in json.loads(line) for line in lines)

    def test_result_payload_carries_the_summary(self, run):
        result = run["snapshot"]["result"]
        assert result["summary"]["selected"] == run["summary"].selected
        assert result["summary"]["out_dirs"]


class TestPerClipFormatStatus:
    def test_planned_formats_appear_before_the_render_starts(self, run):
        """O card precisa saber quantos arquivos o corte vai ter, desde o começo.

        Antes o chip de cada formato só nascia quando aquele ffmpeg começava, e o
        card parecia exportar menos coisa do que o vizinho até o fim do render.
        """
        pending_seen = [
            event
            for event in run["events"]
            if any(
                status == "pending"
                for clip in event["clips"]
                for status in clip["formats"].values()
            )
        ]
        assert pending_seen, "nenhum formato foi anunciado como pendente"

    def test_every_planned_format_ends_in_a_terminal_state(self, run):
        for clip in run["snapshot"]["clips"]:
            assert clip["formats"], "corte terminou sem nenhum formato registrado"
            for name, status in clip["formats"].items():
                assert status in {"done", "error"}, f"{name} ficou em {status}"

    def test_the_render_counter_matches_the_files_produced(self, run):
        """A contagem de unidades do render tem de fechar com o total planejado."""
        render = next(s for s in run["snapshot"]["stages"] if s["name"] == "render")
        assert render["units_done"] == render["units_total"]
        assert render["percent"] == 100.0


class TestFailureState:
    def test_failure_is_reported_and_never_leaves_ui_spinning(
        self, tmp_path, monkeypatch, sample_video_path, fake_client
    ):
        _patch_download(monkeypatch, sample_video_path)
        settings = Settings(
            openrouter_api_key="test-key",
            work_dir=tmp_path / "work",
            out_dir=tmp_path / "out",
        )

        def boom(*args, **kwargs):
            raise RuntimeError("429 rate limit da OpenRouter")

        monkeypatch.setattr(pipeline_mod, "score_candidates", boom)
        reporter = pipeline_mod.make_reporter(settings, "job-erro")

        with pytest.raises(RuntimeError):
            pipeline_mod.run_job(
                "https://youtube.com/watch?v=fixture",
                settings,
                pipeline_mod.RunOptions(),
                client=fake_client,
                reporter=reporter,
            )

        snapshot = reporter.snapshot()
        assert snapshot["status"] == "error"
        assert snapshot["error"]["stage"] == "score"
        assert snapshot["error"]["retriable"] is True
        assert "resume" in snapshot["error"]["hint"]
        assert snapshot["eta_seconds"] is None

    def test_cancel_stops_the_job(self, tmp_path, monkeypatch, sample_video_path, fake_client):
        _patch_download(monkeypatch, sample_video_path)
        settings = Settings(
            openrouter_api_key="test-key",
            work_dir=tmp_path / "work",
            out_dir=tmp_path / "out",
        )
        reporter = pipeline_mod.make_reporter(settings, "job-cancelado")

        with pytest.raises(pipeline_mod.JobCanceled):
            pipeline_mod.run_job(
                "https://youtube.com/watch?v=fixture",
                settings,
                pipeline_mod.RunOptions(),
                client=fake_client,
                reporter=reporter,
                cancel_check=lambda: True,
            )
        assert reporter.snapshot()["status"] == "canceled"


class TestDryRunProgress:
    def test_dry_run_completes_without_leaving_stages_pending(
        self, tmp_path, monkeypatch, sample_video_path, fake_client
    ):
        _patch_download(monkeypatch, sample_video_path)
        settings = Settings(
            openrouter_api_key="test-key",
            work_dir=tmp_path / "work",
            out_dir=tmp_path / "out",
        )
        reporter = pipeline_mod.make_reporter(settings, "job-dry")
        pipeline_mod.run_job(
            "https://youtube.com/watch?v=fixture",
            settings,
            pipeline_mod.RunOptions(dry_run=True),
            client=fake_client,
            reporter=reporter,
        )
        snapshot = reporter.snapshot()
        assert snapshot["status"] == "done"
        assert snapshot["percent"] == pytest.approx(100.0, abs=0.01)
        assert all(s["status"] in {"done", "skipped"} for s in snapshot["stages"])


class TestResumeProgress:
    def test_resume_marks_cached_stages_as_skipped(
        self, tmp_path, monkeypatch, sample_video_path, fake_client
    ):
        _patch_download(monkeypatch, sample_video_path)
        settings = Settings(
            openrouter_api_key="test-key",
            work_dir=tmp_path / "work",
            out_dir=tmp_path / "out",
            min_duration_full_arc_s=0.0,
        )
        first = pipeline_mod.run_job(
            "https://youtube.com/watch?v=fixture",
            settings,
            pipeline_mod.RunOptions(),
            client=fake_client,
        )

        reporter = pipeline_mod.make_reporter(settings, first.job_id)
        pipeline_mod.resume_job(
            first.job_id,
            settings,
            pipeline_mod.RunOptions(min_score=0),
            client=fake_client,
            reporter=reporter,
        )
        stages = {s["name"]: s["status"] for s in reporter.snapshot()["stages"]}
        assert stages["download"] == "skipped"
        assert stages["transcribe"] == "skipped"
        assert stages["candidates"] == "skipped"
        assert reporter.snapshot()["percent"] == pytest.approx(100.0, abs=0.01)
