"""Fila de jobs da API: um job por vez, estado persistido e eventos para SSE."""

from __future__ import annotations

import asyncio
import json
import queue
import shutil
import threading
import time
import traceback
from pathlib import Path
from typing import Any

from ..config import get_settings
from ..feedback import ratings_for_job
from ..jobstate import JobRecord, StateReporter, new_job_id
from ..paths import job_dir, job_events_path, job_out_dir
from ..pipeline import JobCanceled, JobOptions, run_job


class EventBroker:
    """Fan-out thread-safe de eventos do worker para os clientes SSE."""

    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue]] = {}
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self, job_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        with self._lock:
            self._subscribers.setdefault(job_id, set()).add(q)
        return q

    def unsubscribe(self, job_id: str, q: asyncio.Queue) -> None:
        with self._lock:
            subs = self._subscribers.get(job_id)
            if subs:
                subs.discard(q)
                if not subs:
                    self._subscribers.pop(job_id, None)

    def publish(self, job_id: str, event: dict) -> None:
        with self._lock:
            targets = list(self._subscribers.get(job_id, ()))
        if not targets or self._loop is None:
            return
        for q in targets:
            try:
                self._loop.call_soon_threadsafe(q.put_nowait, event)
            except RuntimeError:  # loop já fechado
                continue


class JobManager:
    """Fila sequencial (alvo: MacBook i5/16GB — um render por vez)."""

    def __init__(self) -> None:
        self.broker = EventBroker()
        self._records: dict[str, JobRecord] = {}
        self._queue: "queue.Queue[str]" = queue.Queue()
        self._lock = threading.RLock()
        self._worker: threading.Thread | None = None
        self._running_id: str | None = None
        self.load_from_disk()

    # --- persistência --------------------------------------------------------
    STALE_AFTER_S = 180.0
    """job.json parado por muito tempo com status ativo = processo morreu."""

    def load_from_disk(self) -> None:
        settings = get_settings()
        if not settings.work_dir.exists():
            return
        for state_file in sorted(settings.work_dir.glob("*/job.json")):
            try:
                data = json.loads(state_file.read_text(encoding="utf-8"))
                record = JobRecord.from_dict(data)
            except Exception:
                continue
            self._mark_stale(record, state_file)
            with self._lock:
                self._records[record.id] = record

    def _mark_stale(self, record: JobRecord, state_file: Path | None = None) -> None:
        """Jobs ativos de processos mortos (CLI fechada, restart) viram erro."""
        if record.status not in {"running", "queued"} or record.id == self._running_id:
            return
        path = state_file or (job_dir(record.id) / "job.json")
        try:
            idle = time.time() - path.stat().st_mtime
        except OSError:
            idle = self.STALE_AFTER_S + 1
        if idle > self.STALE_AFTER_S:
            record.status = "error"
            record.error = record.error or "job interrompido (processo encerrado)"

    def sync(self) -> None:
        """Reflete jobs criados/atualizados fora deste processo (ex.: CLI)."""
        settings = get_settings()
        if not settings.work_dir.exists():
            return
        for state_file in sorted(settings.work_dir.glob("*/job.json")):
            job_id = state_file.parent.name
            if job_id == self._running_id:
                continue
            with self._lock:
                known = self._records.get(job_id)
            if known is not None and known.status in {"queued"} and job_id in self.queued_ids():
                continue
            loaded = JobRecord.load(job_id)
            if loaded is None:
                continue
            self._mark_stale(loaded, state_file)
            with self._lock:
                self._records[job_id] = loaded

    def _append_event_log(self, job_id: str, event: dict) -> None:
        try:
            path = job_events_path(job_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def _publish(self, job_id: str, kind: str, payload: Any) -> None:
        event = {"job_id": job_id, "type": kind, "t": time.time(), "payload": payload}
        self._append_event_log(job_id, event)
        self.broker.publish(job_id, event)

    # --- leitura -------------------------------------------------------------
    def list_jobs(self) -> list[JobRecord]:
        with self._lock:
            records = list(self._records.values())
        records.sort(key=lambda r: r.created_at, reverse=True)
        return records

    def get(self, job_id: str) -> JobRecord | None:
        with self._lock:
            record = self._records.get(job_id)
        if record is not None and (job_id == self._running_id or job_id in self.queued_ids()):
            return record
        loaded = JobRecord.load(job_id)
        if loaded is None:
            return record
        self._mark_stale(loaded)
        with self._lock:
            self._records[job_id] = loaded
        return loaded

    def snapshot(self, record: JobRecord) -> dict:
        """Estado do job com as notas do usuário anexadas aos clips."""
        data = record.to_dict()
        ratings = ratings_for_job(record.id)
        for clip in data.get("clips", []):
            rating = ratings.get(clip.get("slug"))
            clip["rating"] = rating.verdict if rating else None
            clip["rating_note"] = rating.note if rating else None
        return data

    @property
    def running_id(self) -> str | None:
        return self._running_id

    def queued_ids(self) -> list[str]:
        with self._lock:
            return [r.id for r in self._records.values() if r.status == "queued"]

    # --- escrita -------------------------------------------------------------
    def submit(self, options: JobOptions, job_id: str | None = None) -> JobRecord:
        record = JobRecord(id=job_id or new_job_id(), options=options)
        with self._lock:
            self._records[record.id] = record
        job_dir(record.id).mkdir(parents=True, exist_ok=True)
        record.save()
        self._publish(record.id, "status", {"status": record.status})
        self._queue.put(record.id)
        self._ensure_worker()
        return record

    def resume(
        self,
        job_id: str,
        mode: str = "more",
        count: int | None = None,
        min_score: int | None = None,
    ) -> JobRecord:
        """Re-roda aproveitando `work/<job_id>/` (sem baixar de novo)."""
        record = self.get(job_id)
        if record is None:
            raise KeyError(job_id)
        record.options = JobOptions.from_dict(
            {
                **record.options.to_dict(),
                "mode": mode,
                "count": count,
                "dry_run": False,
                **({"min_score": min_score} if min_score is not None else {}),
            }
        )
        record.status = "queued"
        record.error = None
        record.finished_at = None
        record.clips = []
        record.selection = None
        record.resumed_from = job_id
        record.reset_stages()
        record.add_log(
            f"resume: modo {mode}"
            + (f" com count={count}" if count else "")
            + " reaproveitando transcrição e scores em cache"
        )
        record.save()
        self._publish(record.id, "status", {"status": record.status})
        self._queue.put(record.id)
        self._ensure_worker()
        return record

    def cancel(self, job_id: str) -> JobRecord | None:
        record = self.get(job_id)
        if record is None:
            return None
        if record.status in {"done", "error", "canceled"}:
            return record
        record.cancel_requested = True
        if record.status == "queued":
            record.status = "canceled"
            record.finished_at = time.time()
            record.save()
            self._publish(record.id, "status", {"status": record.status})
        return record

    def delete(self, job_id: str, remove_files: bool = False) -> bool:
        record = self.get(job_id)
        if record is None:
            return False
        if record.status in {"running", "queued"}:
            self.cancel(job_id)
        with self._lock:
            self._records.pop(job_id, None)
        shutil.rmtree(job_dir(job_id), ignore_errors=True)
        if remove_files:
            shutil.rmtree(job_out_dir(job_id), ignore_errors=True)
        return True

    # --- worker --------------------------------------------------------------
    def _ensure_worker(self) -> None:
        with self._lock:
            if self._worker and self._worker.is_alive():
                return
            self._worker = threading.Thread(
                target=self._work_loop, name="clip-mvp-worker", daemon=True
            )
            self._worker.start()

    def _work_loop(self) -> None:
        while True:
            try:
                job_id = self._queue.get(timeout=30)
            except queue.Empty:
                return
            record = self.get(job_id)
            if record is None or record.status != "queued":
                continue
            self._run(record)

    def _run(self, record: JobRecord) -> None:
        self._running_id = record.id
        record.status = "running"
        record.started_at = time.time()
        record.cancel_requested = False
        record.save()
        self._publish(record.id, "status", {"status": record.status})
        reporter = StateReporter(
            record, on_event=lambda kind, payload: self._publish(record.id, kind, payload)
        )
        try:
            result = run_job(record.id, record.options, reporter)
            record.clips = result.clips or record.clips
            record.selection = result.selection or record.selection
            record.estimate = result.estimate or record.estimate
            record.source = result.source or record.source
            record.status = "done"
        except JobCanceled:
            record.status = "canceled"
            reporter.log("job cancelado", "warn")
            for stage in record.stages:
                if stage.status == "running":
                    stage.status = "error"
                    stage.message = "cancelado"
        except Exception as exc:  # noqa: BLE001 - erro do job vira estado, não crash
            record.status = "error"
            record.error = str(exc) or exc.__class__.__name__
            reporter.log(f"erro: {record.error}", "error")
            reporter.log(traceback.format_exc(limit=3), "debug")
            for stage in record.stages:
                if stage.status == "running":
                    stage.status = "error"
                    stage.message = record.error[:200]
        finally:
            record.finished_at = time.time()
            self._running_id = None
            record.save()
            self._publish(record.id, "status", {"status": record.status, "error": record.error})
            self._publish(record.id, "done", self.snapshot(record))


def clip_artifact_path(job_id: str, slug: str, name: str) -> Path:
    """Caminho absoluto de um artefato, preso ao diretório de saída do job."""
    if "/" in name or "\\" in name or name.startswith("."):
        raise ValueError(name)
    base = job_out_dir(job_id).resolve()
    for clip_dir in sorted(base.glob(f"*_{slug}")):
        candidate = (clip_dir / name).resolve()
        if base in candidate.parents and candidate.is_file():
            return candidate
    raise FileNotFoundError(f"{slug}/{name}")
