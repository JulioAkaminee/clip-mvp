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

Configuração da OpenRouter feita pela própria interface:

- ``GET  /api/settings``          chave (mascarada) + modelo de cada papel de IA
- ``PUT  /api/settings``          grava chave e/ou modelos no arquivo de settings
- ``POST /api/settings/test``     testa a conexão com a OpenRouter
- ``GET  /api/settings/models``   catálogo da OpenRouter para escolher o modelo
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
import time
from pathlib import Path
from typing import Any, Callable, Iterator, Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from .candidates import auto_count_range, candidate_pool_size
from .config import Settings, env_settings
from .feedback import load_recent_feedback, rate_clip
from .openrouter import OpenRouterError, fetch_models, verify_key
from .pipeline import RunOptions, make_reporter, resume_job, run_job
from .progress import STAGE_LABELS, STAGE_ORDER, EventBroker, ProgressReporter
from .settings_store import (
    MODEL_ROLES,
    ROLE_BY_KEY,
    SettingsValidationError,
    apply_stored,
    describe,
    load_stored,
    mask_key,
    save_stored,
    validate_api_key,
    validate_model_id,
)
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

#: Um job vivo reescreve ``status.json`` a cada batimento (2s por padrão),
#: inclusive quando roda na CLI em outro processo. Passado este tempo sem
#: nenhuma escrita e sem thread viva aqui, o job morreu: `kill`, reboot, ou o
#: laptop fechou no meio do render. Sem isso a UI herdava um "rodando" eterno,
#: com ETA congelado e nenhum botão para sair do lugar.
STALE_JOB_AFTER_S = 45.0

_ACTIVE = {"queued", "running"}


def mark_stale_if_dead(
    snapshot: dict[str, Any], *, running: bool, now: float, after_s: float = STALE_JOB_AFTER_S
) -> dict[str, Any]:
    """Converte um job abandonado em estado de erro retriável.

    O objetivo é honestidade: "interrompido" com um botão de retomar é
    informação; um spinner que gira para sempre não é.
    """
    snapshot.setdefault("stale", False)
    if running or snapshot.get("status") not in _ACTIVE:
        return snapshot

    updated_at = snapshot.get("updated_at")
    if not isinstance(updated_at, (int, float)) or (now - updated_at) <= after_s:
        return snapshot

    stage = snapshot.get("stage") or "queued"
    idle_min = max(1, int((now - updated_at) // 60))
    snapshot["status"] = "error"
    snapshot["stale"] = True
    snapshot["eta_seconds"] = None
    snapshot["eta_text"] = "interrompido"
    snapshot["message"] = f"Job interrompido em {snapshot.get('stage_label', stage)}"
    snapshot["error"] = {
        "stage": stage,
        "stage_label": snapshot.get("stage_label", stage),
        "type": "JobInterrupted",
        "message": (
            f"O job parou de responder há ~{idle_min} min (processo encerrado, "
            "reinício do servidor ou máquina suspensa)."
        ),
        "retriable": True,
        "hint": "Clique em Tentar de novo: o cache em work/ é reaproveitado, sem re-baixar nem re-transcrever.",
    }
    return snapshot


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


class SettingsUpdate(BaseModel):
    """Corpo do ``PUT /api/settings``.

    Campos ausentes não mudam nada: a UI pode salvar só os modelos sem reenviar a
    chave (que ela nunca recebe de volta em texto claro).
    """

    #: Chave nova. ``None`` ou vazio = mantém a que já está gravada.
    api_key: str | None = None
    #: Apaga a chave do arquivo de settings (volta a valer o `.env`, se houver).
    clear_api_key: bool = False
    #: ``{"score": "google/gemini-2.5-pro"}``. Valor vazio volta ao default do `.env`.
    models: dict[str, str] | None = None


class ConnectionTest(BaseModel):
    #: Chave a testar antes de salvar. Vazio = testa a que já está configurada.
    api_key: str | None = None


class JobRunner:
    """Roda jobs em threads e mantém um broker de eventos por job."""

    def __init__(
        self, settings: Settings, *, resolve: Callable[[], Settings] | None = None
    ) -> None:
        self.settings = settings
        #: Resolve a configuração no momento de disparar o job, para que uma chave
        #: ou modelo salvos na UI valham no próximo job sem reiniciar o servidor.
        self._resolve = resolve or (lambda: settings)
        self._brokers: dict[str, EventBroker] = {}
        self._reporters: dict[str, ProgressReporter] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._cancels: dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    def start(self, url: str, options: RunOptions, *, job_id: str | None = None) -> tuple[str, bool]:
        """Dispara o job e devolve ``(job_id, é_um_job_que_já_estava_rodando)``."""
        resuming = job_id is not None
        job_id = job_id or make_job_id(url)

        # job_id é determinístico pela URL: reenviar o mesmo link enquanto o job
        # roda faria duas threads escreverem o mesmo status.json e a mesma pasta
        # out/. Nesse caso o certo é acompanhar o job que já existe.
        if self.is_running(job_id):
            return job_id, True

        broker = EventBroker()
        reporter = make_reporter(self.settings, job_id, sinks=[broker.publish])
        cancel = threading.Event()
        job_settings = self._resolve()

        with self._lock:
            self._brokers[job_id] = broker
            self._reporters[job_id] = reporter
            self._cancels[job_id] = cancel

        def target() -> None:
            try:
                if resuming:
                    resume_job(
                        job_id,
                        job_settings,
                        options,
                        reporter=reporter,
                        cancel_check=cancel.is_set,
                    )
                else:
                    run_job(
                        url,
                        job_settings,
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
        return job_id, False

    def snapshot(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            reporter = self._reporters.get(job_id)
        if reporter is not None:
            payload = reporter.snapshot()
        else:
            path = Path(self.settings.work_dir) / job_id / "status.json"
            if not path.is_file():
                return None
            try:
                payload = json.loads(path.read_text("utf-8"))
            except (json.JSONDecodeError, OSError):
                return None
        return mark_stale_if_dead(
            payload, running=self.is_running(job_id), now=time.time()
        )

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
                        "stale": snapshot.get("stale", False),
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


#: Quanto do fim de ``events.jsonl`` o histórico lê. A UI só mostra as últimas
#: centenas de linhas, então carregar o arquivo inteiro na memória para depois
#: fatiar é trabalho jogado fora — e um job de podcast longo com retries gera
#: um arquivo grande.
HISTORY_TAIL_BYTES = 512 * 1024


def _tail_lines(path: Path, *, max_bytes: int = HISTORY_TAIL_BYTES) -> list[str]:
    """Últimas linhas completas do arquivo, sem ler o que vem antes."""
    try:
        size = path.stat().st_size
        with path.open("rb") as fh:
            if size > max_bytes:
                fh.seek(size - max_bytes)
                fh.readline()  # descarta a linha partida no meio
            raw = fh.read()
    except OSError:
        return []
    return raw.decode("utf-8", errors="replace").splitlines()


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


#: Quanto tempo o catálogo da OpenRouter (~centenas de modelos) fica em cache.
#: Ele muda em dias, não em segundos, e a tela de Configurações pede a lista a
#: cada abertura. `refresh=true` força a releitura.
MODELS_CACHE_TTL_S = 30 * 60


def _models_cache_path(settings: Settings) -> Path:
    return Path(settings.work_dir) / "openrouter_models.json"


def read_models_cache(settings: Settings, *, ttl_s: float = MODELS_CACHE_TTL_S) -> list[dict] | None:
    """Catálogo em cache, ou ``None`` se não houver ou estiver velho.

    O catálogo é o mesmo para qualquer chave (é o cardápio da OpenRouter, não algo
    da conta), então o cache não precisa ser por chave.
    """
    path = _models_cache_path(settings)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text("utf-8"))
        fetched_at = float(payload["fetched_at"])
        models = payload["models"]
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(models, list) or (time.time() - fetched_at) > ttl_s:
        return None
    return models


def write_models_cache(settings: Settings, models: list[dict]) -> None:
    path = _models_cache_path(settings)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"fetched_at": time.time(), "models": models}, ensure_ascii=False),
            "utf-8",
        )
    except OSError:  # noqa: BLE001 - cache é conveniência, não pode quebrar a tela
        pass


def filter_models(models: list[dict], *, requires: tuple[str, ...] = (), query: str = "") -> list[dict]:
    """Filtra o catálogo por modalidade de entrada e por texto digitado.

    `text` é implícito (todo modelo de chat aceita texto); o que importa filtrar é
    `image` (papel de score) e `audio` (STT/diarização).
    """
    needed = {item for item in requires if item != "text"}
    needle = query.strip().lower()
    result = []
    for model in models:
        modalities = set(model.get("input_modalities") or [])
        if needed and not needed <= modalities:
            continue
        if needle and needle not in f"{model.get('id', '')} {model.get('name', '')}".lower():
            continue
        result.append(model)
    return result


def create_app(settings: Settings | None = None, *, settings_path: Path | None = None) -> FastAPI:
    """Monta a API.

    `settings` é a camada de ambiente (`.env`); o que a UI gravou em
    `settings_path` entra por cima a cada requisição/job, então salvar a chave na
    tela não exige reiniciar o `clip serve`.
    """
    settings = settings if settings is not None else env_settings()

    def resolve_settings() -> Settings:
        return apply_stored(settings, load_stored(settings_path))

    runner = JobRunner(settings, resolve=resolve_settings)
    app = FastAPI(title="clip-mvp", version="0.1.0")
    app.state.runner = runner
    app.state.settings = settings
    app.state.settings_path = settings_path
    app.state.resolve_settings = resolve_settings

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
        job_id, already_running = runner.start(payload.url.strip(), payload.to_options())
        return {
            "job_id": job_id,
            # O job_id vem da URL: reenviar o mesmo link não cria um segundo job.
            # A UI precisa dizer isso, senão parece que o formulário não respondeu.
            "already_running": already_running,
        }

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

    @app.get("/api/jobs/{job_id}/history")
    def job_history(job_id: str, limit: int = Query(300, ge=1, le=5000)) -> dict[str, Any]:
        """Histórico de mensagens do job (o `events.jsonl` que o reporter grava).

        É o que permite abrir um job já terminado e ainda ver o caminho que ele
        percorreu, em vez de só o último frame.
        """
        path = Path(settings.work_dir) / job_id / "events.jsonl"
        if not path.is_file():
            _require_snapshot(job_id)  # 404 se o job não existe mesmo
            return {"events": []}
        events: list[dict[str, Any]] = []
        last_message = ""
        for line in _tail_lines(path):
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            message = (event.get("message") or "").strip()
            if not message or message == last_message:
                continue
            last_message = message
            events.append(
                {
                    "t": event.get("updated_at"),
                    "stage": event.get("stage", ""),
                    "message": message,
                }
            )
        return {"events": events[-limit:]}

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

    # -- configuração da OpenRouter (chave + modelo por papel) -------------
    @app.get("/api/settings")
    def get_settings_route() -> dict[str, Any]:
        """Estado da configuração. A chave sai **mascarada**, nunca completa."""
        return describe(
            resolve_settings(), load_stored(settings_path), env=settings, path=settings_path
        )

    @app.put("/api/settings")
    def update_settings(payload: SettingsUpdate) -> dict[str, Any]:
        stored = load_stored(settings_path)
        try:
            if payload.clear_api_key:
                stored.openrouter_api_key = ""
            elif payload.api_key and payload.api_key.strip():
                stored.openrouter_api_key = validate_api_key(payload.api_key)

            for role_key, raw_value in (payload.models or {}).items():
                role = ROLE_BY_KEY.get(role_key)
                if role is None:
                    known = ", ".join(item.key for item in MODEL_ROLES)
                    raise SettingsValidationError(
                        f"Papel de IA desconhecido: `{role_key}`. Use um destes: {known}."
                    )
                if not (raw_value or "").strip():
                    # Vazio é "voltar ao default do projeto", não "modelo em branco".
                    stored.models.pop(role_key, None)
                else:
                    stored.models[role_key] = validate_model_id(raw_value, role=role)
        except SettingsValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None

        save_stored(stored, settings_path)
        return describe(resolve_settings(), stored, env=settings, path=settings_path)

    @app.post("/api/settings/test")
    def test_connection(payload: ConnectionTest | None = None) -> dict[str, Any]:
        """Testa a chave contra a OpenRouter antes de confiar nela num job."""
        candidate = (payload.api_key or "").strip() if payload else ""
        if candidate:
            try:
                key = validate_api_key(candidate)
            except SettingsValidationError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from None
        else:
            key = resolve_settings().openrouter_api_key
        if not key:
            raise HTTPException(
                status_code=400,
                detail="Nenhuma chave configurada: cole a chave da OpenRouter antes de testar.",
            )
        try:
            result = verify_key(key, base_url=resolve_settings().openrouter_base_url)
        except OpenRouterError as exc:
            # Chave errada não é erro do servidor: a tela mostra o motivo inline.
            return {"ok": False, "message": str(exc)}
        label = result.get("label")
        return {
            **result,
            "message": (
                f"Conexão OK — chave “{label}” aceita pela OpenRouter."
                if label
                else "Conexão OK — chave aceita pela OpenRouter."
            ),
        }

    @app.get("/api/settings/models")
    def list_openrouter_models(
        role: str | None = Query(None, description="Filtra pelo que o papel exige (ex. score→vision)"),
        q: str = Query("", max_length=120, description="Busca por id ou nome"),
        limit: int = Query(400, ge=1, le=5000),
        refresh: bool = Query(False, description="Ignora o cache e relê o catálogo"),
    ) -> dict[str, Any]:
        """Catálogo da OpenRouter (`GET /models`) para o seletor de modelos.

        Qualquer id é aceito no campo de texto da UI; esta lista existe para
        procurar sem sair da tela, não para limitar a escolha.
        """
        resolved = resolve_settings()
        if not resolved.openrouter_api_key:
            raise HTTPException(
                status_code=400,
                detail="Configure a chave da OpenRouter para listar os modelos disponíveis.",
            )
        if role is not None and role not in ROLE_BY_KEY:
            raise HTTPException(status_code=400, detail=f"Papel de IA desconhecido: `{role}`.")

        models = None if refresh else read_models_cache(resolved)
        cached = models is not None
        if models is None:
            try:
                models = fetch_models(
                    resolved.openrouter_api_key, base_url=resolved.openrouter_base_url
                )
            except OpenRouterError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from None
            write_models_cache(resolved, models)

        requires = ROLE_BY_KEY[role].requires if role else ()
        matching = filter_models(models, requires=requires, query=q)
        return {
            "models": matching[:limit],
            "total": len(models),
            "matching": len(matching),
            "cached": cached,
        }

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
        # Chave e modelos vêm da configuração resolvida (`.env` + o que a UI
        # salvou), então a tela mostra o que o próximo job vai realmente usar.
        resolved = resolve_settings()
        stored = load_stored(settings_path)
        return {
            "ok": ffmpeg_ok and bool(shutil.which("ffprobe")),
            "ffmpeg": ffmpeg_ok,
            "ffprobe": bool(shutil.which("ffprobe")),
            "yt_dlp": ytdlp_ok,
            "mediapipe": mediapipe_ok,
            "openrouter_key": bool(resolved.openrouter_api_key),
            "openrouter_key_masked": mask_key(resolved.openrouter_api_key),
            "openrouter_key_source": (
                "ui" if stored.openrouter_api_key else ("env" if resolved.openrouter_api_key else None)
            ),
            "ui_built": (WEB_DIST / "index.html").is_file(),
            "models": {
                "stt": resolved.stt_model,
                "candidates": resolved.candidate_model,
                "score": resolved.score_model,
                "meta": resolved.meta_model,
                "diarization": resolved.model_for_diarization(),
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
