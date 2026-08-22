"""Estados degradados da API: job abandonado, URL duplicada, histórico grande.

A promessa do painel é que a tela nunca fica girando para sempre. Isso vale
também quando ninguém falhou: o processo pode ter sido morto, o servidor
reiniciado ou o laptop fechado no meio do render.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from clip_mvp.config import Settings
from clip_mvp.server import STALE_JOB_AFTER_S, create_app, mark_stale_if_dead


def _snapshot(**overrides) -> dict:
    payload = {
        "schema_version": 1,
        "job_id": "job_abc",
        "status": "running",
        "stage": "render",
        "stage_label": "Renderizando cortes",
        "stage_percent": 40.0,
        "percent": 71.0,
        "eta_seconds": 96,
        "eta_text": "~1.5 min restantes",
        "message": "Renderizando… 2/5 arquivos",
        "clips_done": 1,
        "clips_total": 3,
        "clips": [],
        "stages": [],
        "elapsed_seconds": 300.0,
        "updated_at": time.time(),
        "error": None,
    }
    payload.update(overrides)
    return payload


class TestStaleDetection:
    def test_a_dead_job_becomes_a_retriable_error(self):
        now = time.time()
        payload = mark_stale_if_dead(
            _snapshot(updated_at=now - 600.0), running=False, now=now
        )
        assert payload["status"] == "error"
        assert payload["stale"] is True
        assert payload["error"]["retriable"] is True
        assert payload["error"]["type"] == "JobInterrupted"
        # nada de ETA fantasma herdado do último frame
        assert payload["eta_seconds"] is None

    def test_the_hint_points_at_the_cache(self):
        now = time.time()
        payload = mark_stale_if_dead(
            _snapshot(updated_at=now - 600.0), running=False, now=now
        )
        assert "work/" in payload["error"]["hint"]

    def test_a_job_alive_in_another_process_is_left_alone(self):
        """A CLI escreve status.json a cada batimento; frescor é o discriminante.

        `clip serve` não tem thread para um job iniciado na CLI, então "não está
        rodando aqui" não pode significar "morreu".
        """
        now = time.time()
        payload = mark_stale_if_dead(_snapshot(updated_at=now - 3.0), running=False, now=now)
        assert payload["status"] == "running"
        assert payload["stale"] is False

    def test_a_job_running_in_this_process_is_never_stale(self):
        now = time.time()
        payload = mark_stale_if_dead(
            _snapshot(updated_at=now - 10_000.0), running=True, now=now
        )
        assert payload["status"] == "running"

    def test_a_finished_job_is_not_touched(self):
        now = time.time()
        payload = mark_stale_if_dead(
            _snapshot(status="done", updated_at=now - 10_000.0), running=False, now=now
        )
        assert payload["status"] == "done"
        assert payload["stale"] is False

    @pytest.mark.parametrize("age,expected", [(1.0, "running"), (STALE_JOB_AFTER_S + 5, "error")])
    def test_the_threshold_is_respected(self, age, expected):
        now = time.time()
        payload = mark_stale_if_dead(_snapshot(updated_at=now - age), running=False, now=now)
        assert payload["status"] == expected

    def test_a_snapshot_without_a_timestamp_is_not_guessed_about(self):
        now = time.time()
        payload = mark_stale_if_dead(_snapshot(updated_at=None), running=False, now=now)
        assert payload["status"] == "running"


@pytest.fixture()
def app_client(tmp_path: Path):
    settings = Settings(
        openrouter_api_key="test-key",
        work_dir=tmp_path / "work",
        out_dir=tmp_path / "out",
    )
    return TestClient(create_app(settings)), settings


class TestStaleOverHttp:
    def test_the_endpoint_surfaces_the_interrupted_state(self, app_client):
        client, settings = app_client
        job_dir = settings.work_dir / "job_dead"
        job_dir.mkdir(parents=True)
        (job_dir / "job.json").write_text(
            json.dumps({"source_url": "https://example.com/v", "job_id": "job_dead"}), "utf-8"
        )
        (job_dir / "status.json").write_text(
            json.dumps(_snapshot(job_id="job_dead", updated_at=time.time() - 900.0)), "utf-8"
        )

        payload = client.get("/api/jobs/job_dead").json()
        assert payload["status"] == "error"
        assert payload["stale"] is True
        assert payload["error"]["retriable"] is True

    def test_the_job_list_flags_it_too(self, app_client):
        client, settings = app_client
        job_dir = settings.work_dir / "job_dead"
        job_dir.mkdir(parents=True)
        (job_dir / "status.json").write_text(
            json.dumps(_snapshot(job_id="job_dead", updated_at=time.time() - 900.0)), "utf-8"
        )
        jobs = client.get("/api/jobs").json()["jobs"]
        entry = next(job for job in jobs if job["job_id"] == "job_dead")
        assert entry["status"] == "error"
        assert entry["stale"] is True

    def test_an_interrupted_job_can_be_retried(self, app_client):
        """O botão precisa funcionar: 409 só vale para job de fato em execução."""
        client, settings = app_client
        job_dir = settings.work_dir / "job_dead"
        job_dir.mkdir(parents=True)
        (job_dir / "job.json").write_text(
            json.dumps({"source_url": "https://example.com/v", "job_id": "job_dead"}), "utf-8"
        )
        (job_dir / "status.json").write_text(
            json.dumps(_snapshot(job_id="job_dead", updated_at=time.time() - 900.0)), "utf-8"
        )
        response = client.post("/api/jobs/job_dead/retry", json={"url": ""})
        assert response.status_code == 200
        assert response.json()["retried"] is True


class TestDuplicateUrl:
    def test_resubmitting_a_url_reports_that_it_attached_to_the_same_job(self, app_client):
        """O job_id vem da URL, então o mesmo link nunca cria um segundo job.

        Sem esse sinal o formulário parecia não ter respondido.
        """
        client, _ = app_client
        first = client.post("/api/jobs", json={"url": "https://example.com/watch?v=abc"}).json()
        assert first["already_running"] is False

        second = client.post("/api/jobs", json={"url": "https://example.com/watch?v=abc"}).json()
        assert second["job_id"] == first["job_id"]
        # A thread pode já ter falhado (sem rede nos testes); o contrato aqui é
        # que o campo existe e o job_id é estável para a mesma URL.
        assert "already_running" in second

    def test_an_empty_url_is_rejected(self, app_client):
        client, _ = app_client
        assert client.post("/api/jobs", json={"url": "   "}).status_code == 400


class TestHistoryTail:
    def test_a_huge_event_log_is_read_from_the_end(self, app_client):
        client, settings = app_client
        job_dir = settings.work_dir / "job_big"
        job_dir.mkdir(parents=True)
        (job_dir / "status.json").write_text(json.dumps(_snapshot(job_id="job_big")), "utf-8")

        with (job_dir / "events.jsonl").open("w", encoding="utf-8") as fh:
            for i in range(40_000):
                fh.write(
                    json.dumps(
                        {
                            "job_id": "job_big",
                            "stage": "render",
                            "message": f"linha {i}",
                            "updated_at": 1000.0 + i,
                        }
                    )
                    + "\n"
                )

        events = client.get("/api/jobs/job_big/history").json()["events"]
        assert len(events) <= 300
        # a última mensagem escrita tem de estar lá: o corte é no começo
        assert events[-1]["message"] == "linha 39999"
