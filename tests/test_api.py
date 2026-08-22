"""Contrato da API que a UI consome."""

import pytest
from fastapi.testclient import TestClient

from clip_mvp.api.app import create_app
from clip_mvp.api.jobs import JobManager, clip_artifact_path


@pytest.fixture
def client():
    with TestClient(create_app(JobManager())) as test_client:
        yield test_client


def test_health(client):
    body = client.get("/api/health").json()
    assert body["version"]
    assert body["demo_mode"] is True  # sem OPENROUTER_API_KEY nos testes
    assert set(body["models"]) == {"stt", "candidates", "score", "meta"}


def test_config_expoe_as_regras_do_produto(client):
    body = client.get("/api/config").json()
    assert body["vertical_max_s"] == 90
    assert body["pad_ms"] == [200, 400]
    assert body["safe_area_bottom"] == 0.20
    assert body["formats"] == [
        "vertical_facetrack",
        "vertical_center",
        "horizontal_16x9",
    ]
    assert len(body["target_ranges"]) == 4


def test_lista_vazia(client):
    body = client.get("/api/jobs").json()
    assert body == {"jobs": [], "running": None, "queued": []}


def test_url_obrigatoria(client):
    response = client.post("/api/jobs", json={"url": "   "})
    assert response.status_code == 422


def test_formatos_nao_podem_ser_vazios(client):
    response = client.post("/api/jobs", json={"url": "https://x.test/v", "formats": []})
    assert response.status_code == 422


def test_job_inexistente(client):
    assert client.get("/api/jobs/nope").status_code == 404
    assert client.post("/api/jobs/nope/cancel").status_code == 404
    assert client.post("/api/jobs/nope/resume", json={"mode": "more"}).status_code == 404
    assert client.get("/api/jobs/nope/clips/x/files/meta.json").status_code == 404


def test_resume_count_exige_numero(client):
    manager: JobManager = client.app.state.manager
    from clip_mvp.pipeline import JobOptions

    record = JobOptions(url="https://x.test/v")
    job = manager.submit(record)
    manager.cancel(job.id)
    response = client.post(f"/api/jobs/{job.id}/resume", json={"mode": "count"})
    assert response.status_code == 422


def test_artifact_path_bloqueia_traversal(isolated_home):
    with pytest.raises(ValueError):
        clip_artifact_path("job_x", "slug", "../../etc/passwd")


def test_estimate_com_arquivo_local(client, fixture_video):
    if fixture_video is None:
        pytest.skip("sem tests/fixtures/demo_480s.mp4")
    response = client.post("/api/estimate", json={"url": str(fixture_video)})
    assert response.status_code == 200
    body = response.json()
    assert body["duration_s"] > 0
    assert body["total_usd"] > 0
    assert body["candidates"] >= 6


def test_cancelamento_de_job_na_fila(client):
    response = client.post("/api/jobs", json={"url": "https://exemplo.test/video"})
    assert response.status_code == 201
    job_id = response.json()["id"]
    cancelled = client.post(f"/api/jobs/{job_id}/cancel").json()
    assert cancelled["status"] in {"canceled", "running", "error"}
    assert client.delete(f"/api/jobs/{job_id}?files=true").status_code == 200
