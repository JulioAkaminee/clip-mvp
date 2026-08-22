"""API HTTP + UI web com progresso ao vivo (SSE) e minutos restantes.

Endpoints de progresso (mesmo payload que a CLI consome — uma fonte de verdade):

- ``POST /api/jobs``             cria e dispara um job
- ``GET  /api/jobs``             lista jobs conhecidos
- ``GET  /api/jobs/{id}``        snapshot de progresso (polling)
- ``GET  /api/jobs/{id}/events`` stream SSE com o mesmo payload
- ``POST /api/jobs/{id}/retry``  retoma um job que falhou (usa o cache)
- ``POST /api/jobs/{id}/cancel`` cancela um job em andamento

Endpoints que a UI usa para mostrar o resultado:

- ``GET  /api/health``                            dependências locais e modelos
- ``GET  /api/config``                            regras do produto (90s, pad, faixas de N)
- ``GET  /api/jobs/{id}/clips``                   cortes com meta.json e artefatos
- ``GET  /api/jobs/{id}/clips/{slug}/files/{f}``  preview (Range) e download
- ``GET  /api/jobs/{id}/clips/{slug}/poster.jpg`` thumbnail (gerado sob demanda)
- ``POST /api/jobs/{id}/clips/{slug}/rate``       feedback good/bad (SPEC §14.7)
"""

from __future__ import annotations

import json
import mimetypes
import shutil
import threading
from pathlib import Path
from typing import Any, Iterator, Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from .candidates import auto_count_range, candidate_pool_size
from .config import Settings, get_settings
from .feedback import load_recent_feedback, rate_clip
from .pipeline import RunOptions, make_reporter, resume_job, run_job
from .progress import STAGE_LABELS, STAGE_ORDER, EventBroker, ProgressReporter
from .utils import make_job_id, read_json, run_ffmpeg

#: Build da UI React (``cd web && npm run build``).
WEB_DIST = Path(__file__).resolve().parents[2] / "web" / "dist"

#: Artefatos que a UI pode pedir por clipe.
CLIP_ARTIFACTS: tuple[str, ...] = (
    "vertical_facetrack.mp4",
    "vertical_center.mp4",
    "horizontal_16x9.mp4",
    "captions.srt",
    "captions_9x16.srt",
    "captions_16x9.ass",
    "captions_9x16.ass",
    "meta.json",
    "poster.jpg",
)

#: Ordem de preferência da fonte do thumbnail.
POSTER_SOURCES: tuple[str, ...] = (
    "horizontal_16x9.mp4",
    "vertical_center.mp4",
    "vertical_facetrack.mp4",
)

STREAM_CHUNK = 512 * 1024


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


class RateRequest(BaseModel):
    verdict: Literal["good", "bad"]
    note: str = ""


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

    def job_meta(self, job_id: str) -> dict[str, Any]:
        job_file = Path(self.settings.work_dir) / job_id / "job.json"
        if not job_file.is_file():
            return {}
        try:
            return read_json(job_file)
        except Exception:  # noqa: BLE001
            return {}

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
                        "clips_done": snapshot.get("clips_done"),
                        "clips_total": snapshot.get("clips_total"),
                        "updated_at": snapshot.get("updated_at"),
                        "source_minutes": snapshot.get("source_minutes"),
                        "running": self.is_running(path.name),
                    }
                )
            jobs.append(info)
        return jobs


# ---------------------------------------------------------------------------
# Leitura dos cortes já exportados
# ---------------------------------------------------------------------------


def _clip_dir(settings: Settings, slug: str, score: float | None = None) -> Path | None:
    """Localiza ``out/<score>_<slug>`` sem confiar no score (ele arredonda)."""
    if "/" in slug or "\\" in slug or slug.startswith("."):
        return None
    out_dir = Path(settings.out_dir)
    if score is not None:
        candidate = out_dir / f"{round(score)}_{slug}"
        if candidate.is_dir():
            return candidate
    matches = sorted(out_dir.glob(f"*_{slug}")) if out_dir.exists() else []
    for match in matches:
        if match.is_dir():
            return match
    return None


def _artifacts_in(clip_dir: Path) -> dict[str, str]:
    return {name: name for name in CLIP_ARTIFACTS if (clip_dir / name).is_file()}


def _selected_index(settings: Settings, job_id: str) -> list[dict[str, Any]]:
    path = Path(settings.work_dir) / job_id / "selected.json"
    if not path.is_file():
        return []
    try:
        data = read_json(path)
    except Exception:  # noqa: BLE001
        return []
    return data if isinstance(data, list) else []


def _feedback_by_slug(settings: Settings, job_id: str) -> dict[str, dict[str, Any]]:
    """Último veredito por slug (o mais recente vence)."""
    verdicts: dict[str, dict[str, Any]] = {}
    for record in load_recent_feedback(settings.work_dir, n=500):
        if record.get("job_id") != job_id:
            continue
        slug = record.get("slug")
        if slug:
            verdicts[slug] = record
    return verdicts


def collect_clips(settings: Settings, job_id: str, snapshot: dict[str, Any] | None) -> list[dict]:
    """Junta progresso por clipe + ``meta.json`` + artefatos em disco.

    Funciona durante o job (a partir do snapshot de progresso) e depois dele
    (a partir de ``work/<job_id>/selected.json``).
    """
    entries: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    for clip in (snapshot or {}).get("clips", []) or []:
        slug = clip.get("slug")
        if not slug:
            continue
        order.append(slug)
        entries[slug] = {
            "slug": slug,
            "score": clip.get("score"),
            "status": clip.get("status", "pending"),
            "formats": dict(clip.get("formats") or {}),
            "vertical_skipped": clip.get("vertical_skipped"),
            "message": clip.get("message", ""),
        }

    for item in _selected_index(settings, job_id):
        slug = item.get("slug")
        if not slug:
            continue
        entry = entries.setdefault(slug, {"slug": slug, "status": "done", "formats": {}})
        if slug not in order:
            order.append(slug)
        entry.setdefault("score", item.get("score"))
        entry["score"] = entry.get("score") or item.get("score")
        entry["reason"] = item.get("reason") or entry.get("reason", "")
        entry["vertical_skipped"] = entry.get("vertical_skipped") or item.get("vertical_skipped")
        if item.get("out_dir"):
            entry["out_dir"] = item["out_dir"]

    verdicts = _feedback_by_slug(settings, job_id)
    clips: list[dict[str, Any]] = []
    for slug in order:
        entry = entries[slug]
        clip_dir = _clip_dir(settings, slug, entry.get("score"))
        if clip_dir is None and entry.get("out_dir"):
            maybe = Path(entry["out_dir"])
            clip_dir = maybe if maybe.is_dir() else None
        meta: dict[str, Any] = {}
        artifacts: dict[str, str] = {}
        if clip_dir is not None:
            artifacts = _artifacts_in(clip_dir)
            meta_path = clip_dir / "meta.json"
            if meta_path.is_file():
                try:
                    meta = read_json(meta_path)
                except Exception:  # noqa: BLE001
                    meta = {}
            entry["out_dir"] = str(clip_dir)

        verdict = verdicts.get(slug) or {}
        clips.append(
            {
                **entry,
                "title": meta.get("youtube", {}).get("shorts_title")
                or meta.get("youtube", {}).get("long_title")
                or slug.replace("-", " "),
                "score": entry.get("score") or meta.get("score"),
                "reason": entry.get("reason") or meta.get("reason", ""),
                "context_complete": meta.get("context_complete"),
                "windows": meta.get("windows", {}),
                "breakdown": meta.get("breakdown", {}),
                "speaker_matching": meta.get("speaker_matching", {}),
                "boundaries": meta.get("boundaries", {}),
                "youtube": meta.get("youtube", {}),
                "tiktok": meta.get("tiktok", {}),
                "artifacts": artifacts,
                "rating": verdict.get("verdict"),
                "rating_note": verdict.get("note"),
            }
        )
    return clips


def _ensure_poster(clip_dir: Path) -> Path | None:
    """Thumbnail do card, extraído do primeiro export disponível."""
    poster = clip_dir / "poster.jpg"
    if poster.is_file():
        return poster
    for name in POSTER_SOURCES:
        source = clip_dir / name
        if not source.is_file():
            continue
        try:
            run_ffmpeg(
                [
                    "-ss",
                    "1",
                    "-i",
                    str(source),
                    "-frames:v",
                    "1",
                    "-vf",
                    "scale=640:-2",
                    "-q:v",
                    "4",
                    str(poster),
                ]
            )
        except Exception:  # noqa: BLE001 - thumbnail é enfeite, não pode quebrar a UI
            return None
        return poster if poster.is_file() else None
    return None


def _ranged_file_response(path: Path, request: Request, *, download: bool = False) -> Response:
    """Serve o arquivo com suporte a ``Range`` (o player do navegador exige)."""
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    headers = {"Accept-Ranges": "bytes", "Cache-Control": "no-cache"}
    if download:
        headers["Content-Disposition"] = f'attachment; filename="{path.name}"'

    range_header = request.headers.get("range")
    if not range_header:
        return FileResponse(path, media_type=media_type, headers=headers)

    size = path.stat().st_size
    try:
        units, _, raw = range_header.partition("=")
        if units.strip().lower() != "bytes":
            raise ValueError(range_header)
        start_raw, _, end_raw = raw.partition("-")
        start = int(start_raw) if start_raw else 0
        end = int(end_raw) if end_raw else size - 1
    except ValueError:
        raise HTTPException(status_code=416, detail="Range inválido") from None

    start = max(0, min(start, size - 1))
    end = max(start, min(end, size - 1))
    length = end - start + 1

    def stream() -> Iterator[bytes]:
        with path.open("rb") as fh:
            fh.seek(start)
            remaining = length
            while remaining > 0:
                chunk = fh.read(min(STREAM_CHUNK, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    headers.update(
        {"Content-Range": f"bytes {start}-{end}/{size}", "Content-Length": str(length)}
    )
    return StreamingResponse(stream(), status_code=206, media_type=media_type, headers=headers)


_NO_BUILD_PAGE = """<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><title>clip-mvp</title><style>
body{background:#070910;color:#d3d9e6;font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
display:flex;min-height:100vh;align-items:center;justify-content:center;margin:0}
main{max-width:34rem;padding:2rem}code{background:#151a27;padding:.15rem .4rem;border-radius:.35rem}
a{color:#8ea6ff}h1{letter-spacing:-.02em}</style></head><body><main>
<h1>clip-mvp</h1>
<p>A API está no ar, mas a interface ainda não foi buildada.</p>
<p>Rode <code>cd web &amp;&amp; npm install &amp;&amp; npm run build</code> e recarregue esta página,
ou use <code>npm run dev</code> para desenvolver em <code>:5173</code> com hot reload.</p>
<p>Progresso por linha de comando: <code>clip status &lt;job_id&gt; --watch</code>.
Documentação da API: <a href="/docs">/docs</a>.</p>
</main></body></html>"""


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    runner = JobRunner(settings)
    app = FastAPI(title="clip-mvp", version="0.1.0")
    app.state.runner = runner
    app.state.settings = settings

    def _require_snapshot(job_id: str) -> dict[str, Any]:
        snapshot = runner.snapshot(job_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="job não encontrado")
        return snapshot

    def _require_clip_dir(job_id: str, slug: str) -> Path:
        snapshot = runner.snapshot(job_id)
        score = None
        for clip in (snapshot or {}).get("clips", []) or []:
            if clip.get("slug") == slug:
                score = clip.get("score")
                break
        clip_dir = _clip_dir(settings, slug, score)
        if clip_dir is None:
            raise HTTPException(status_code=404, detail="corte não encontrado")
        return clip_dir

    # -- progresso (contrato compartilhado com a CLI) ----------------------
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
        snapshot = _require_snapshot(job_id)
        meta = runner.job_meta(job_id)
        return {**snapshot, "source_url": meta.get("source_url", ""), "running": runner.is_running(job_id)}

    @app.get("/api/jobs/{job_id}/events")
    def job_events(job_id: str) -> StreamingResponse:
        broker = runner.broker(job_id)
        if broker is None:
            # Job já terminado (ou de outra execução): manda o último estado
            # conhecido e encerra, em vez de deixar o cliente pendurado.
            snapshot = _require_snapshot(job_id)

            def once() -> Iterator[str]:
                yield f"data: {json.dumps(snapshot, ensure_ascii=False)}\n\n"

            return StreamingResponse(once(), media_type="text/event-stream")

        def stream() -> Iterator[str]:
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
    def retry_job(job_id: str, payload: JobRequest | None = None) -> dict[str, Any]:
        if runner.is_running(job_id):
            raise HTTPException(status_code=409, detail="job ainda está rodando")
        job_file = Path(settings.work_dir) / job_id / "job.json"
        if not job_file.is_file():
            raise HTTPException(status_code=404, detail="job não encontrado")
        source_url = read_json(job_file).get("source_url", "")
        options = payload.to_options() if payload is not None else RunOptions()
        runner.start(source_url, options, job_id=job_id)
        return {"job_id": job_id, "retried": True}

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel_job(job_id: str) -> dict[str, Any]:
        if not runner.cancel(job_id):
            raise HTTPException(status_code=404, detail="job não está em execução")
        return {"job_id": job_id, "canceled": True}

    # -- ambiente e regras do produto -------------------------------------
    @app.get("/api/health")
    def health() -> dict[str, Any]:
        try:
            import mediapipe  # noqa: F401

            mediapipe_ok = True
        except Exception:  # noqa: BLE001
            mediapipe_ok = False
        try:
            import yt_dlp  # noqa: F401

            ytdlp_ok = True
        except Exception:  # noqa: BLE001
            ytdlp_ok = bool(shutil.which("yt-dlp"))
        ffmpeg_ok = bool(shutil.which("ffmpeg"))
        return {
            "ok": ffmpeg_ok and bool(shutil.which("ffprobe")),
            "ffmpeg": ffmpeg_ok,
            "ffprobe": bool(shutil.which("ffprobe")),
            "yt_dlp": ytdlp_ok,
            "mediapipe": mediapipe_ok,
            "openrouter_key": bool(settings.openrouter_api_key),
            "ui_built": (WEB_DIST / "index.html").is_file(),
            "models": {
                "stt": settings.stt_model,
                "candidates": settings.candidate_model,
                "score": settings.score_model,
                "meta": settings.meta_model,
            },
            "work_dir": str(settings.work_dir),
            "out_dir": str(settings.out_dir),
        }

    @app.get("/api/config")
    def config() -> dict[str, Any]:
        ranges = []
        for lo_min, hi_min in ((0, 10), (10, 30), (30, 90), (90, None)):
            probe = ((hi_min or 120) * 60) - 1 if hi_min else 200 * 60
            lo, hi = auto_count_range(probe)
            ranges.append(
                {"from_min": lo_min, "to_min": hi_min, "min_clips": lo, "max_clips": hi}
            )
        return {
            "formats": ["face", "9x16", "16x9"],
            "format_labels": {
                "face": "9:16 face tracking",
                "9x16": "9:16 center",
                "16x9": "16:9",
            },
            "platforms": ["yt", "tiktok"],
            "caption_modes": ["burn", "sidecar", "both"],
            "default_min_score": settings.min_score_default,
            "vertical_max_s": settings.vertical_max_s,
            "pad_ms": [settings.pad_ms_min, settings.pad_ms_max],
            "stages": [{"name": name, "label": STAGE_LABELS[name]} for name in STAGE_ORDER],
            "target_ranges": ranges,
            "candidate_pool_example": candidate_pool_size(6),
        }

    # -- cortes ------------------------------------------------------------
    @app.get("/api/jobs/{job_id}/clips")
    def job_clips(job_id: str) -> dict[str, Any]:
        snapshot = _require_snapshot(job_id)
        return {"clips": collect_clips(settings, job_id, snapshot)}

    @app.get("/api/jobs/{job_id}/clips/{slug}/poster.jpg")
    def clip_poster(job_id: str, slug: str, request: Request) -> Response:
        clip_dir = _require_clip_dir(job_id, slug)
        poster = _ensure_poster(clip_dir)
        if poster is None:
            raise HTTPException(status_code=404, detail="sem thumbnail ainda")
        return _ranged_file_response(poster, request)

    @app.get("/api/jobs/{job_id}/clips/{slug}/files/{name}")
    def clip_file(
        job_id: str, slug: str, name: str, request: Request, download: bool = Query(False)
    ) -> Response:
        if name not in CLIP_ARTIFACTS:
            raise HTTPException(status_code=404, detail="artefato desconhecido")
        clip_dir = _require_clip_dir(job_id, slug)
        path = clip_dir / name
        if not path.is_file():
            raise HTTPException(status_code=404, detail="artefato não encontrado")
        return _ranged_file_response(path, request, download=download)

    @app.post("/api/jobs/{job_id}/clips/{slug}/rate")
    def rate(job_id: str, slug: str, payload: RateRequest) -> dict[str, Any]:
        if _clip_dir(settings, slug) is None:
            raise HTTPException(status_code=404, detail="corte não encontrado")
        return rate_clip(
            settings.work_dir, job_id, slug, payload.verdict, note=payload.note
        )

    # -- UI ----------------------------------------------------------------
    if (WEB_DIST / "assets").is_dir():
        from fastapi.staticfiles import StaticFiles

        app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @app.get("/")
    def index() -> Response:
        index_html = WEB_DIST / "index.html"
        if index_html.is_file():
            return FileResponse(index_html, media_type="text/html")
        return HTMLResponse(_NO_BUILD_PAGE)

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> Response:
        """Rotas do front caem no index; /api desconhecido continua 404."""
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="rota não encontrada")
        candidate = (WEB_DIST / full_path).resolve()
        if WEB_DIST.is_dir() and WEB_DIST.resolve() in candidate.parents and candidate.is_file():
            return FileResponse(candidate)
        return index()

    return app
