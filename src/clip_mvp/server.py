"""API HTTP + UI web com progresso ao vivo (SSE) e minutos restantes.

Endpoints:

- ``POST /api/jobs``             cria e dispara um job
- ``GET  /api/jobs``             lista jobs conhecidos
- ``GET  /api/jobs/{id}``        snapshot de progresso (polling)
- ``GET  /api/jobs/{id}/events`` stream SSE com o mesmo payload
- ``POST /api/jobs/{id}/retry``  retoma um job que falhou (usa o cache)
- ``POST /api/jobs/{id}/cancel`` cancela um job em andamento

O payload é exatamente o mesmo que a CLI consome — uma fonte de verdade só.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field

from .config import Settings, get_settings
from .pipeline import RunOptions, make_reporter, resume_job, run_job
from .progress import EventBroker, ProgressReporter
from .utils import make_job_id, read_json

WEB_DIR = Path(__file__).parent / "web"


class JobRequest(BaseModel):
    url: str
    more: bool = False
    count: int | None = None
    min_score: float | None = None
    max_score_only: float | None = None
    formats: list[str] = Field(default_factory=lambda: ["face", "9x16", "16x9"])
    captions: str = "both"
    platforms: list[str] = Field(default_factory=lambda: ["yt", "tiktok"])
    dry_run: bool = False
    budget: float | None = None

    def to_options(self) -> RunOptions:
        return RunOptions(
            more=self.more,
            count=self.count,
            min_score=self.min_score,
            max_score_only=self.max_score_only,
            formats=list(self.formats),
            captions=self.captions,
            platforms=list(self.platforms),
            dry_run=self.dry_run,
            budget=self.budget,
        )


class JobRunner:
    """Roda jobs em threads e mantém um broker de eventos por job."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._brokers: dict[str, EventBroker] = {}
        self._reporters: dict[str, ProgressReporter] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._cancels: dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    def start(self, url: str, options: RunOptions, *, job_id: str | None = None) -> str:
        resuming = job_id is not None
        job_id = job_id or make_job_id(url)

        # job_id é determinístico pela URL: reenviar o mesmo link enquanto o job
        # roda faria duas threads escreverem o mesmo status.json e a mesma pasta
        # out/. Nesse caso o certo é acompanhar o job que já existe.
        if self.is_running(job_id):
            return job_id

        broker = EventBroker()
        reporter = make_reporter(self.settings, job_id, sinks=[broker.publish])
        cancel = threading.Event()

        with self._lock:
            self._brokers[job_id] = broker
            self._reporters[job_id] = reporter
            self._cancels[job_id] = cancel

        def target() -> None:
            try:
                if resuming:
                    resume_job(
                        job_id,
                        self.settings,
                        options,
                        reporter=reporter,
                        cancel_check=cancel.is_set,
                    )
                else:
                    run_job(
                        url,
                        self.settings,
                        options,
                        reporter=reporter,
                        cancel_check=cancel.is_set,
                    )
            except Exception:  # noqa: BLE001 - o reporter já registrou o erro
                pass

        thread = threading.Thread(target=target, name=f"clip-job-{job_id}", daemon=True)
        with self._lock:
            self._threads[job_id] = thread
        thread.start()
        return job_id

    def snapshot(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            reporter = self._reporters.get(job_id)
        if reporter is not None:
            return reporter.snapshot()
        path = Path(self.settings.work_dir) / job_id / "status.json"
        if path.is_file():
            try:
                return json.loads(path.read_text("utf-8"))
            except (json.JSONDecodeError, OSError):
                return None
        return None

    def broker(self, job_id: str) -> EventBroker | None:
        with self._lock:
            return self._brokers.get(job_id)

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            event = self._cancels.get(job_id)
        if event is None:
            return False
        event.set()
        return True

    def is_running(self, job_id: str) -> bool:
        with self._lock:
            thread = self._threads.get(job_id)
        return bool(thread and thread.is_alive())

    def list_jobs(self) -> list[dict[str, Any]]:
        work_dir = Path(self.settings.work_dir)
        if not work_dir.exists():
            return []
        jobs: list[dict[str, Any]] = []
        for path in sorted(work_dir.iterdir(), reverse=True):
            if not path.is_dir():
                continue
            info: dict[str, Any] = {"job_id": path.name}
            job_file = path / "job.json"
            if job_file.is_file():
                try:
                    info.update(read_json(job_file))
                except Exception:  # noqa: BLE001
                    pass
            snapshot = self.snapshot(path.name)
            if snapshot:
                info.update(
                    {
                        "status": snapshot.get("status"),
                        "percent": snapshot.get("percent"),
                        "stage": snapshot.get("stage"),
                        "stage_label": snapshot.get("stage_label"),
                        "eta_seconds": snapshot.get("eta_seconds"),
                        "eta_text": snapshot.get("eta_text"),
                    }
                )
            jobs.append(info)
        return jobs


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    runner = JobRunner(settings)
    app = FastAPI(title="clip-mvp", version="0.1.0")
    app.state.runner = runner
    app.state.settings = settings

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return (WEB_DIR / "index.html").read_text("utf-8")

    @app.post("/api/jobs")
    def create_job(payload: JobRequest) -> dict[str, Any]:
        if not payload.url.strip():
            raise HTTPException(status_code=400, detail="url é obrigatória")
        job_id = runner.start(payload.url.strip(), payload.to_options())
        return {"job_id": job_id}

    @app.get("/api/jobs")
    def list_jobs() -> dict[str, Any]:
        return {"jobs": runner.list_jobs()[:50]}

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, Any]:
        snapshot = runner.snapshot(job_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="job não encontrado")
        return snapshot

    @app.get("/api/jobs/{job_id}/events")
    def job_events(job_id: str) -> StreamingResponse:
        broker = runner.broker(job_id)
        if broker is None:
            # Job já terminado (ou de outra execução): manda o último estado
            # conhecido e encerra, em vez de deixar o cliente pendurado.
            snapshot = runner.snapshot(job_id)
            if snapshot is None:
                raise HTTPException(status_code=404, detail="job não encontrado")

            def once():
                yield f"data: {json.dumps(snapshot, ensure_ascii=False)}\n\n"

            return StreamingResponse(once(), media_type="text/event-stream")

        def stream():
            for payload in broker.stream():
                if payload.get("type") == "heartbeat":
                    yield ": keep-alive\n\n"
                    continue
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/jobs/{job_id}/retry")
    def retry_job(job_id: str) -> dict[str, Any]:
        if runner.is_running(job_id):
            raise HTTPException(status_code=409, detail="job ainda está rodando")
        job_file = Path(settings.work_dir) / job_id / "job.json"
        if not job_file.is_file():
            raise HTTPException(status_code=404, detail="job não encontrado")
        source_url = read_json(job_file).get("source_url", "")
        runner.start(source_url, RunOptions(), job_id=job_id)
        return {"job_id": job_id, "retried": True}

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel_job(job_id: str) -> dict[str, Any]:
        if not runner.cancel(job_id):
            raise HTTPException(status_code=404, detail="job não está em execução")
        return {"job_id": job_id, "canceled": True}

    return app
