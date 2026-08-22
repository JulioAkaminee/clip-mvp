"""API HTTP de progresso: polling, SSE, retry e cancelamento."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from clip_mvp.config import Settings
from clip_mvp.progress import ClipProgress
from clip_mvp.server import create_app

WEB_SRC = Path(__file__).resolve().parents[1] / "web" / "src"


def _web_source() -> str:
    """Código-fonte da UI React concatenado (contrato UI ↔ API)."""
    return "\n".join(
        path.read_text("utf-8") for path in sorted(WEB_SRC.rglob("*.ts*"))
    )


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        openrouter_api_key="test-key",
        work_dir=tmp_path / "work",
        out_dir=tmp_path / "out",
    )


@pytest.fixture
def app(settings, monkeypatch):
    """App com o pipeline substituído por um job sintético controlável."""
    import clip_mvp.server as server_mod

    def fake_run_job(url, s, options, *, reporter=None, cancel_check=None, client=None):
        reporter.start_stage("download", units_total=1)
        reporter.finish_stage("download", "baixado")
        reporter.start_stage("transcribe", units_total=2)
        reporter.advance_units("transcribe", 1, "bloco 1/2")
        reporter.advance_units("transcribe", 2, "bloco 2/2")
        reporter.finish_stage("transcribe", "transcrito")
        reporter.register_clips([ClipProgress(slug="corte-um", score=88)])
        reporter.update_clip("corte-um", status="done", format_name="horizontal_16x9", format_status="done")
        for stage in ("candidates", "score", "select", "captions", "render", "meta"):
            reporter.skip_stage(stage, "teste")
        reporter.finish({"summary": {"selected": 1, "out_dirs": ["out/88_corte-um"], "notes": []}}, "ok")
        return None

    monkeypatch.setattr(server_mod, "run_job", fake_run_job)
    return create_app(settings)


@pytest.fixture
def client(app):
    return TestClient(app)


def _wait_done(client, job_id, tries=100):
    for _ in range(tries):
        payload = client.get(f"/api/jobs/{job_id}").json()
        if payload["status"] in {"done", "error", "canceled"}:
            return payload
    raise AssertionError("job não terminou a tempo")


class TestCreateJob:
    def test_creates_and_returns_job_id(self, client):
        response = client.post("/api/jobs", json={"url": "https://youtube.com/watch?v=x"})
        assert response.status_code == 200
        assert response.json()["job_id"]

    def test_rejects_empty_url(self, client):
        assert client.post("/api/jobs", json={"url": "   "}).status_code == 400

    def test_accepts_selection_options(self, client):
        response = client.post(
            "/api/jobs",
            json={"url": "https://youtube.com/watch?v=x", "more": True, "min_score": 70},
        )
        assert response.status_code == 200


class TestPolling:
    def test_status_payload_has_the_progress_contract(self, client):
        job_id = client.post("/api/jobs", json={"url": "https://x/1"}).json()["job_id"]
        payload = _wait_done(client, job_id)
        for key in (
            "stage",
            "percent",
            "eta_seconds",
            "eta_text",
            "message",
            "clips_done",
            "clips_total",
            "stages",
            "clips",
        ):
            assert key in payload

    def test_completed_job_reports_100_percent(self, client):
        job_id = client.post("/api/jobs", json={"url": "https://x/2"}).json()["job_id"]
        payload = _wait_done(client, job_id)
        assert payload["status"] == "done"
        assert payload["percent"] == pytest.approx(100.0, abs=0.01)
        assert payload["eta_seconds"] == 0

    def test_per_clip_status_is_exposed(self, client):
        job_id = client.post("/api/jobs", json={"url": "https://x/3"}).json()["job_id"]
        payload = _wait_done(client, job_id)
        assert payload["clips_total"] == 1
        assert payload["clips"][0]["slug"] == "corte-um"
        assert payload["clips"][0]["formats"]["horizontal_16x9"] == "done"

    def test_unknown_job_returns_404(self, client):
        assert client.get("/api/jobs/inexistente").status_code == 404

    def test_jobs_can_be_listed(self, client):
        client.post("/api/jobs", json={"url": "https://x/4"})
        jobs = client.get("/api/jobs").json()["jobs"]
        assert isinstance(jobs, list)


class TestSse:
    def test_event_stream_delivers_progress_payloads(self, client):
        job_id = client.post("/api/jobs", json={"url": "https://x/5"}).json()["job_id"]
        _wait_done(client, job_id)

        with client.stream("GET", f"/api/jobs/{job_id}/events") as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            body = "".join(response.iter_text())

        payloads = [
            json.loads(line[len("data: ") :])
            for line in body.splitlines()
            if line.startswith("data: ")
        ]
        assert payloads
        assert payloads[-1]["status"] == "done"
        assert "eta_seconds" in payloads[-1]

    def test_stream_of_unknown_job_is_404(self, client):
        with client.stream("GET", "/api/jobs/inexistente/events") as response:
            assert response.status_code == 404


class TestRetryAndCancel:
    def test_retry_of_unknown_job_is_404(self, client):
        assert client.post("/api/jobs/inexistente/retry").status_code == 404

    def test_cancel_of_unknown_job_is_404(self, client):
        assert client.post("/api/jobs/inexistente/cancel").status_code == 404


class TestUi:
    """A UI é o app React em `web/` (buildado em `web/dist`)."""

    def test_index_is_served(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert "clip-mvp" in response.text

    def test_unknown_api_route_is_not_swallowed_by_the_spa(self, client):
        assert client.get("/api/nao-existe").status_code == 404

    def test_ui_source_consumes_the_progress_contract(self):
        """A UI tem de ler os mesmos campos que a API promete."""
        source = _web_source()
        for field in (
            "eta_text",
            "eta_seconds",
            "clips_done",
            "clips_total",
            "stage_label",
            "percent",
            "vertical_skipped",
        ):
            assert field in source, f"a UI não consome '{field}' do payload de progresso"

    def test_ui_has_retry_affordance(self):
        source = _web_source()
        assert "retry" in source
        assert "Tentar de novo" in source

    def test_ui_falls_back_to_polling(self):
        """SSE pode morrer; a tela não pode congelar no último frame."""
        source = _web_source()
        assert "EventSource" in source
        assert "startPolling" in source


class TestDuplicateSubmission:
    """job_id é determinístico pela URL: reenviar não pode duplicar o job."""

    def test_same_url_while_running_attaches_to_the_existing_job(self, settings, monkeypatch):
        import threading

        import clip_mvp.server as server_mod

        release = threading.Event()
        started = threading.Event()
        runs: list[str] = []

        def slow_run_job(url, s, options, *, reporter=None, cancel_check=None, client=None):
            runs.append(url)
            reporter.start_stage("download", units_total=1)
            started.set()
            release.wait(timeout=5)
            reporter.finish_stage("download")
            reporter.finish({"summary": {"selected": 0, "out_dirs": [], "notes": []}}, "ok")

        monkeypatch.setattr(server_mod, "run_job", slow_run_job)
        client = TestClient(create_app(settings))

        first = client.post("/api/jobs", json={"url": "https://x/dup"}).json()["job_id"]
        assert started.wait(timeout=5)
        second = client.post("/api/jobs", json={"url": "https://x/dup"}).json()["job_id"]

        assert first == second
        assert len(runs) == 1, "o mesmo job não pode rodar duas vezes em paralelo"
        release.set()
