"""FastAPI local: contrato usado pela UI web."""

from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from ..config import (
    ALL_FORMATS,
    ALL_PLATFORMS,
    CAPTION_MODES,
    DEFAULT_MIN_SCORE,
    PAD_MAX_S,
    PAD_MIN_S,
    SAFE_AREA_BOTTOM,
    TARGET_RANGES,
    VERSION,
    VERTICAL_MAX_S,
    get_settings,
    tool_status,
)
from ..feedback import load_ratings, rate as rate_clip
from ..pipeline import JobOptions, JobReporter, dry_run
from .jobs import JobManager, clip_artifact_path
from .schemas import (
    ConfigOut,
    EstimateOut,
    HealthOut,
    JobListOut,
    JobOptionsIn,
    JobOut,
    RateIn,
    ResumeIn,
)

LOGGER = logging.getLogger("clip_mvp.api")
CHUNK = 1024 * 512
WEB_DIST_CANDIDATES = ("web/dist", "src/clip_mvp/web_dist")


def _web_dist() -> Path | None:
    root = get_settings().root
    for candidate in WEB_DIST_CANDIDATES:
        path = root / candidate
        if (path / "index.html").exists():
            return path
    return None


def _ranged_response(path: Path, request: Request, download: bool = False) -> Response:
    """Serve arquivo com suporte a Range (o player do navegador exige isso)."""
    if not path.is_file():
        raise HTTPException(status_code=404, detail="arquivo não encontrado")
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    headers = {"Accept-Ranges": "bytes", "Cache-Control": "no-cache"}
    if download:
        headers["Content-Disposition"] = f'attachment; filename="{path.name}"'

    size = path.stat().st_size
    range_header = request.headers.get("range")
    if not range_header:
        return FileResponse(path, media_type=media_type, headers=headers)

    try:
        units, _, raw = range_header.partition("=")
        if units.strip().lower() != "bytes":
            raise ValueError
        start_raw, _, end_raw = raw.partition("-")
        start = int(start_raw) if start_raw else 0
        end = int(end_raw) if end_raw else size - 1
    except ValueError:
        raise HTTPException(status_code=400, detail="Range inválido") from None

    start = max(0, min(start, size - 1))
    end = max(start, min(end, size - 1))
    length = end - start + 1

    def stream():
        with path.open("rb") as fh:
            fh.seek(start)
            remaining = length
            while remaining > 0:
                data = fh.read(min(CHUNK, remaining))
                if not data:
                    break
                remaining -= len(data)
                yield data

    headers.update(
        {
            "Content-Range": f"bytes {start}-{end}/{size}",
            "Content-Length": str(length),
        }
    )
    return StreamingResponse(stream(), status_code=206, media_type=media_type, headers=headers)


def create_app(manager: JobManager | None = None) -> FastAPI:
    app = FastAPI(
        title="clip-mvp",
        version=VERSION,
        description="API local do clip-mvp (cortes automáticos com IA via OpenRouter)",
    )
    app.state.manager = manager or JobManager()

    dev_origins = os.environ.get(
        "CLIP_MVP_CORS", "http://localhost:5173,http://127.0.0.1:5173"
    ).split(",")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in dev_origins if o.strip()],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("startup")
    async def _bind_loop() -> None:
        app.state.manager.broker.bind_loop(asyncio.get_running_loop())

    # --- meta ---------------------------------------------------------------
    @app.get("/api/health", response_model=HealthOut)
    def health() -> HealthOut:
        settings = get_settings(refresh=True)
        tools = tool_status()
        return HealthOut(
            ok=tools["ffmpeg"] and tools["ffprobe"],
            version=VERSION,
            ffmpeg=tools["ffmpeg"],
            ffprobe=tools["ffprobe"],
            yt_dlp=tools["yt_dlp"],
            mediapipe=tools["mediapipe"],
            openrouter_key=settings.has_api_key,
            demo_mode=not settings.ai_enabled,
            models={
                "stt": settings.stt_model,
                "candidates": settings.candidate_model,
                "score": settings.score_model,
                "meta": settings.meta_model,
            },
            work_dir=str(settings.work_dir),
            out_dir=str(settings.out_dir),
        )

    @app.get("/api/config", response_model=ConfigOut)
    def config() -> ConfigOut:
        ranges = []
        previous = 0.0
        for limit, lo, hi in TARGET_RANGES:
            ranges.append(
                {
                    "from_min": round(previous / 60),
                    "to_min": None if limit == float("inf") else round(limit / 60),
                    "min_clips": lo,
                    "max_clips": hi,
                }
            )
            previous = limit if limit != float("inf") else previous
        return ConfigOut(
            formats=list(ALL_FORMATS),
            platforms=list(ALL_PLATFORMS),
            caption_modes=list(CAPTION_MODES),
            default_min_score=DEFAULT_MIN_SCORE,
            vertical_max_s=VERTICAL_MAX_S,
            pad_ms=[int(PAD_MIN_S * 1000), int(PAD_MAX_S * 1000)],
            safe_area_bottom=SAFE_AREA_BOTTOM,
            target_ranges=ranges,
        )

    # --- jobs ---------------------------------------------------------------
    @app.post("/api/estimate", response_model=EstimateOut)
    async def estimate(payload: JobOptionsIn) -> EstimateOut:
        options = JobOptions.from_dict({**payload.model_dump(), "dry_run": True})
        reporter = JobReporter()
        try:
            result = await run_in_threadpool(dry_run, options, reporter, get_settings())
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("estimate falhou para %s", options.url, exc_info=exc)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        assert result.estimate is not None
        return EstimateOut(**result.estimate, source=result.source)

    @app.post("/api/jobs", response_model=JobOut, status_code=201)
    def create_job(payload: JobOptionsIn) -> JobOut:
        manager: JobManager = app.state.manager
        options = JobOptions.from_dict(payload.model_dump())
        record = manager.submit(options)
        return JobOut(**manager.snapshot(record))

    @app.get("/api/jobs", response_model=JobListOut)
    def list_jobs() -> JobListOut:
        manager: JobManager = app.state.manager
        manager.sync()
        return JobListOut(
            jobs=[JobOut(**manager.snapshot(r)) for r in manager.list_jobs()],
            running=manager.running_id,
            queued=manager.queued_ids(),
        )

    @app.get("/api/jobs/{job_id}", response_model=JobOut)
    def get_job(job_id: str) -> JobOut:
        manager: JobManager = app.state.manager
        record = manager.get(job_id)
        if record is None:
            raise HTTPException(status_code=404, detail="job não encontrado")
        return JobOut(**manager.snapshot(record))

    @app.post("/api/jobs/{job_id}/cancel", response_model=JobOut)
    def cancel_job(job_id: str) -> JobOut:
        manager: JobManager = app.state.manager
        record = manager.cancel(job_id)
        if record is None:
            raise HTTPException(status_code=404, detail="job não encontrado")
        return JobOut(**manager.snapshot(record))

    @app.post("/api/jobs/{job_id}/resume", response_model=JobOut)
    def resume_job(job_id: str, payload: ResumeIn) -> JobOut:
        manager: JobManager = app.state.manager
        if manager.get(job_id) is None:
            raise HTTPException(status_code=404, detail="job não encontrado")
        if payload.mode == "count" and not payload.count:
            raise HTTPException(status_code=422, detail="informe count para o modo count")
        record = manager.resume(job_id, payload.mode, payload.count, payload.min_score)
        return JobOut(**manager.snapshot(record))

    @app.delete("/api/jobs/{job_id}")
    def delete_job(job_id: str, files: bool = Query(False)) -> JSONResponse:
        manager: JobManager = app.state.manager
        if not manager.delete(job_id, remove_files=files):
            raise HTTPException(status_code=404, detail="job não encontrado")
        return JSONResponse({"deleted": job_id, "files_removed": files})

    @app.get("/api/jobs/{job_id}/events")
    async def job_events(job_id: str, request: Request) -> StreamingResponse:
        manager: JobManager = app.state.manager
        record = manager.get(job_id)
        if record is None:
            raise HTTPException(status_code=404, detail="job não encontrado")
        queue_ = manager.broker.subscribe(job_id)

        async def event_stream():
            snapshot = {
                "job_id": job_id,
                "type": "snapshot",
                "payload": manager.snapshot(record),
            }
            yield _sse(snapshot)
            try:
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        event = await asyncio.wait_for(queue_.get(), timeout=15.0)
                    except asyncio.TimeoutError:
                        yield ": keep-alive\n\n"
                        continue
                    yield _sse(event)
                    if event["type"] == "done":
                        break
            finally:
                manager.broker.unsubscribe(job_id, queue_)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # --- clips --------------------------------------------------------------
    @app.post("/api/jobs/{job_id}/clips/{slug}/rate")
    def rate(job_id: str, slug: str, payload: RateIn) -> JSONResponse:
        manager: JobManager = app.state.manager
        record = manager.get(job_id)
        if record is None:
            raise HTTPException(status_code=404, detail="job não encontrado")
        clip = next((c for c in record.clips if c.get("slug") == slug), None)
        if clip is None:
            raise HTTPException(status_code=404, detail="corte não encontrado")
        entry = rate_clip(
            job_id=job_id,
            clip_slug=slug,
            verdict=payload.verdict,
            score=int(clip.get("score") or 0),
            reason=clip.get("reason", ""),
            title=clip.get("title", ""),
            note=payload.note,
        )
        return JSONResponse(entry.to_dict())

    @app.get("/api/jobs/{job_id}/clips/{slug}/files/{name}")
    def clip_file(
        job_id: str, slug: str, name: str, request: Request, download: bool = Query(False)
    ) -> Response:
        try:
            path = clip_artifact_path(job_id, slug, name)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=404, detail="artefato não encontrado") from exc
        return _ranged_response(path, request, download=download)

    @app.get("/api/feedback")
    def feedback(limit: int = Query(50, ge=1, le=500)) -> JSONResponse:
        return JSONResponse({"ratings": [r.to_dict() for r in load_ratings(limit=limit)]})

    # --- UI estática --------------------------------------------------------
    dist = _web_dist()
    if dist is not None:
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/", include_in_schema=False)
        def index() -> FileResponse:
            return FileResponse(dist / "index.html")

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa(full_path: str) -> Response:
            if full_path.startswith("api/"):
                raise HTTPException(status_code=404, detail="rota não encontrada")
            candidate = (dist / full_path).resolve()
            if dist.resolve() in candidate.parents and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(dist / "index.html")

    else:

        @app.get("/", include_in_schema=False)
        def index_missing() -> HTMLResponse:
            return HTMLResponse(
                """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<title>clip-mvp</title><style>
body{background:#0b0d12;color:#e7e9ee;font:16px/1.6 -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
display:flex;min-height:100vh;align-items:center;justify-content:center;margin:0}
main{max-width:34rem;padding:2rem}code{background:#1a1f2b;padding:.15rem .4rem;border-radius:.35rem}
a{color:#8ab4ff}</style></head><body><main>
<h1>clip-mvp</h1>
<p>A API está no ar, mas a UI ainda não foi buildada.</p>
<p>Rode <code>cd web &amp;&amp; npm install &amp;&amp; npm run build</code> (ou
<code>npm run dev</code> para desenvolvimento em <code>:5173</code>).</p>
<p>Documentação da API: <a href="/docs">/docs</a></p>
</main></body></html>""",
                status_code=200,
            )

    return app


def _sse(event: dict) -> str:
    return f"event: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"


def get_app() -> FastAPI:
    """Entrada para `uvicorn clip_mvp.api.app:get_app --factory`."""
    return create_app()
