"""Endpoints que a UI usa para mostrar o resultado do job.

Cobrem a camada que junta o progresso por clipe com o `meta.json` em `out/`:
listagem de cortes, preview/download dos artefatos (com `Range`), thumbnail e
feedback good/bad.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from clip_mvp.config import Settings
from clip_mvp.progress import ClipProgress
from clip_mvp.server import collect_clips, create_app

SLUG = "pergunta-que-fecha-o-contexto"
SCORE = 87


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        openrouter_api_key="test-key",
        work_dir=tmp_path / "work",
        out_dir=tmp_path / "out",
    )


@pytest.fixture
def exported_clip(settings):
    """Simula o que o pipeline deixa em disco para um corte pronto."""
    clip_dir = settings.out_dir / f"{SCORE}_{SLUG}"
    clip_dir.mkdir(parents=True)
    (clip_dir / "horizontal_16x9.mp4").write_bytes(b"fake-mp4-bytes-for-range-tests")
    (clip_dir / "vertical_center.mp4").write_bytes(b"fake-vertical")
    (clip_dir / "captions.srt").write_text("1\n00:00:00,000 --> 00:00:02,000\nolá\n", "utf-8")
    meta = {
        "source_url": "https://youtube.com/watch?v=x",
        "context_complete": True,
        "windows": {
            "horizontal_16x9": {"start": 10.0, "end": 100.0, "duration_s": 90.0},
            "vertical_9x16": {"start": 20.0, "end": 80.0, "duration_s": 60.0},
        },
        "vertical_skipped": None,
        "score": SCORE,
        "breakdown": {"hook": 22, "emocao": 21, "citavel": 23, "arco": 21},
        "reason": "Pergunta e resposta completas",
        "speaker_matching": {"method": "diarization"},
        "youtube": {"shorts_title": "Título do Shorts", "hashtags": ["#Shorts"]},
        "tiktok": {"caption": "caption tiktok", "hashtags": ["#fyp"]},
    }
    (clip_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), "utf-8")
    return clip_dir


@pytest.fixture
def app(settings, monkeypatch):
    import clip_mvp.server as server_mod

    def fake_run_job(url, s, options, *, reporter=None, cancel_check=None, client=None):
        reporter.register_clips([ClipProgress(slug=SLUG, score=SCORE)])
        reporter.update_clip(
            SLUG, status="done", format_name="horizontal_16x9", format_status="done"
        )
        for stage in (
            "download",
            "transcribe",
            "candidates",
            "score",
            "select",
            "captions",
            "render",
            "meta",
        ):
            reporter.skip_stage(stage, "teste")
        reporter.finish({"summary": {"selected": 1, "out_dirs": [], "notes": []}}, "ok")

    monkeypatch.setattr(server_mod, "run_job", fake_run_job)
    return create_app(settings)


@pytest.fixture
def client(app):
    return TestClient(app)


def _finished_job(client) -> str:
    job_id = client.post("/api/jobs", json={"url": "https://youtube.com/watch?v=x"}).json()[
        "job_id"
    ]
    for _ in range(100):
        if client.get(f"/api/jobs/{job_id}").json()["status"] in {"done", "error", "canceled"}:
            return job_id
    raise AssertionError("job não terminou a tempo")


class TestHealthAndConfig:
    def test_health_reports_local_dependencies(self, client):
        body = client.get("/api/health").json()
        for key in ("ffmpeg", "ffprobe", "yt_dlp", "mediapipe", "openrouter_key", "models"):
            assert key in body
        assert body["openrouter_key"] is True

    def test_config_exposes_the_product_rules(self, client):
        body = client.get("/api/config").json()
        assert body["vertical_max_s"] == 90.0
        assert body["pad_ms"] == [200, 400]
        assert body["formats"] == ["face", "9x16", "16x9"]
        assert [stage["name"] for stage in body["stages"]][0] == "download"
        assert len(body["target_ranges"]) == 4


class TestHistory:
    """Abrir um job terminado tem de mostrar o caminho, não só o último frame."""

    def test_history_comes_from_the_persisted_events(self, client):
        job_id = _finished_job(client)
        events = client.get(f"/api/jobs/{job_id}/history").json()["events"]
        assert events
        assert {"t", "stage", "message"} <= set(events[0])
        assert events[-1]["message"] == "ok"

    def test_history_drops_repeated_messages(self, client):
        job_id = _finished_job(client)
        events = client.get(f"/api/jobs/{job_id}/history").json()["events"]
        messages = [event["message"] for event in events]
        assert all(a != b for a, b in zip(messages, messages[1:]))

    def test_history_of_unknown_job_is_404(self, client):
        assert client.get("/api/jobs/nope/history").status_code == 404


class TestClipListing:
    def test_lists_clips_with_meta_and_artifacts(self, client, exported_clip):
        job_id = _finished_job(client)
        clips = client.get(f"/api/jobs/{job_id}/clips").json()["clips"]
        assert len(clips) == 1
        clip = clips[0]
        assert clip["slug"] == SLUG
        assert clip["score"] == SCORE
        assert clip["title"] == "Título do Shorts"
        assert clip["windows"]["vertical_9x16"]["duration_s"] == 60.0
        assert clip["breakdown"]["hook"] == 22
        assert clip["youtube"]["hashtags"] == ["#Shorts"]
        assert clip["tiktok"]["caption"] == "caption tiktok"
        assert clip["formats"]["horizontal_16x9"] == "done"
        assert "horizontal_16x9.mp4" in clip["artifacts"]
        assert "captions.srt" in clip["artifacts"]
        assert clip["rating"] is None

    def test_clip_without_export_yet_still_appears(self, client):
        """Durante o render o card já existe, só sem artefatos."""
        job_id = _finished_job(client)
        clips = client.get(f"/api/jobs/{job_id}/clips").json()["clips"]
        assert clips[0]["artifacts"] == {}

    def test_unknown_job_returns_404(self, client):
        assert client.get("/api/jobs/nope/clips").status_code == 404

    def test_collect_clips_survives_missing_snapshot(self, settings, exported_clip):
        assert collect_clips(settings, "job_x", None) == []


class TestArtifacts:
    def test_serves_the_file(self, client, exported_clip):
        job_id = _finished_job(client)
        response = client.get(f"/api/jobs/{job_id}/clips/{SLUG}/files/horizontal_16x9.mp4")
        assert response.status_code == 200
        assert response.headers["accept-ranges"] == "bytes"

    def test_supports_range_requests(self, client, exported_clip):
        """O player do navegador só faz seek com 206 Partial Content."""
        job_id = _finished_job(client)
        response = client.get(
            f"/api/jobs/{job_id}/clips/{SLUG}/files/horizontal_16x9.mp4",
            headers={"Range": "bytes=0-9"},
        )
        assert response.status_code == 206
        assert response.headers["content-length"] == "10"
        assert response.headers["content-range"].startswith("bytes 0-9/")

    def test_download_sets_attachment(self, client, exported_clip):
        job_id = _finished_job(client)
        response = client.get(
            f"/api/jobs/{job_id}/clips/{SLUG}/files/captions.srt?download=true"
        )
        assert "attachment" in response.headers["content-disposition"]

    def test_rejects_unknown_artifact_names(self, client, exported_clip):
        job_id = _finished_job(client)
        assert (
            client.get(f"/api/jobs/{job_id}/clips/{SLUG}/files/segredo.env").status_code == 404
        )

    def test_rejects_path_traversal(self, client, exported_clip):
        job_id = _finished_job(client)
        response = client.get(f"/api/jobs/{job_id}/clips/{SLUG}/files/..%2F..%2Fmeta.json")
        assert response.status_code == 404


class TestRating:
    def test_records_feedback_for_the_clip(self, client, settings, exported_clip):
        job_id = _finished_job(client)
        response = client.post(
            f"/api/jobs/{job_id}/clips/{SLUG}/rate",
            json={"verdict": "good", "note": "abriu no lugar certo"},
        )
        assert response.status_code == 200
        assert response.json()["verdict"] == "good"

        lines = (settings.work_dir / "feedback.jsonl").read_text("utf-8").strip().splitlines()
        assert len(lines) == 1
        assert json.loads(lines[0])["note"] == "abriu no lugar certo"

    def test_rating_shows_up_in_the_clip_listing(self, client, exported_clip):
        job_id = _finished_job(client)
        client.post(f"/api/jobs/{job_id}/clips/{SLUG}/rate", json={"verdict": "bad"})
        clips = client.get(f"/api/jobs/{job_id}/clips").json()["clips"]
        assert clips[0]["rating"] == "bad"

    def test_rejects_invalid_verdict(self, client, exported_clip):
        job_id = _finished_job(client)
        response = client.post(
            f"/api/jobs/{job_id}/clips/{SLUG}/rate", json={"verdict": "otimo"}
        )
        assert response.status_code == 422

    def test_unknown_clip_returns_404(self, client):
        job_id = _finished_job(client)
        response = client.post(
            f"/api/jobs/{job_id}/clips/nao-existe/rate", json={"verdict": "good"}
        )
        assert response.status_code == 404
