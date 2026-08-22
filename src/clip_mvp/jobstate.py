"""Estado persistido do job (`work/<job_id>/job.json`).

Compartilhado pela CLI e pela API: um job rodado no terminal aparece na UI web
e pode ser continuado com `resume` de lá, e vice-versa.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from .paths import job_dir, job_state_path
from .pipeline import STAGES, JobCanceled, JobOptions, JobReporter

MAX_LOG_ENTRIES = 400


def new_job_id() -> str:
    return f"job_{time.strftime('%Y%m%d-%H%M%S')}_{uuid.uuid4().hex[:6]}"


@dataclass
class Stage:
    key: str
    label: str
    status: str = "pending"
    progress: float = 0.0
    message: str = ""
    started_at: float | None = None
    finished_at: float | None = None

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "status": self.status,
            "progress": round(self.progress, 4),
            "message": self.message,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


@dataclass
class JobRecord:
    id: str
    options: JobOptions
    status: str = "queued"
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    source: dict = field(default_factory=dict)
    selection: dict | None = None
    estimate: dict | None = None
    clips: list[dict] = field(default_factory=list)
    error: str | None = None
    log: list[dict] = field(default_factory=list)
    resumed_from: str | None = None
    cancel_requested: bool = False
    stages: list[Stage] = field(
        default_factory=lambda: [Stage(key=k, label=label) for k, label in STAGES]
    )

    # --- mutação -------------------------------------------------------------
    def stage(self, key: str) -> Stage | None:
        for stage in self.stages:
            if stage.key == key:
                return stage
        return None

    def update_stage(
        self, key: str, status: str, progress: float | None, message: str
    ) -> Stage | None:
        stage = self.stage(key)
        if stage is None:
            return None
        if status == "running" and stage.started_at is None:
            stage.started_at = time.time()
        if status in {"done", "skipped", "error"}:
            stage.finished_at = time.time()
        stage.status = status
        if progress is not None:
            stage.progress = max(0.0, min(1.0, progress))
        if message:
            stage.message = message
        return stage

    def add_log(self, message: str, level: str = "info") -> dict:
        entry = {"t": time.time(), "level": level, "message": message}
        self.log.append(entry)
        del self.log[:-MAX_LOG_ENTRIES]
        return entry

    def set_clip(self, clip: dict) -> None:
        for i, existing in enumerate(self.clips):
            if existing.get("slug") == clip.get("slug"):
                self.clips[i] = clip
                return
        self.clips.append(clip)

    def reset_stages(self) -> None:
        for stage in self.stages:
            stage.status = "pending"
            stage.progress = 0.0
            stage.message = ""
            stage.started_at = None
            stage.finished_at = None

    # --- serialização --------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "url": self.options.url,
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "options": self.options.to_dict(),
            "source": self.source,
            "stages": [s.to_dict() for s in self.stages],
            "selection": self.selection,
            "estimate": self.estimate,
            "clips": self.clips,
            "error": self.error,
            "log": self.log[-MAX_LOG_ENTRIES:],
            "resumed_from": self.resumed_from,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "JobRecord":
        record = cls(
            id=data["id"],
            options=JobOptions.from_dict({**data.get("options", {}), "url": data.get("url", "")}),
            status=data.get("status", "done"),
            created_at=float(data.get("created_at") or time.time()),
            started_at=data.get("started_at"),
            finished_at=data.get("finished_at"),
            source=data.get("source") or {},
            selection=data.get("selection"),
            estimate=data.get("estimate"),
            clips=data.get("clips") or [],
            error=data.get("error"),
            log=data.get("log") or [],
            resumed_from=data.get("resumed_from"),
        )
        stages_data = {s.get("key"): s for s in data.get("stages", [])}
        for stage in record.stages:
            raw = stages_data.get(stage.key)
            if not raw:
                continue
            stage.status = raw.get("status", stage.status)
            stage.progress = float(raw.get("progress") or 0.0)
            stage.message = raw.get("message", "")
            stage.started_at = raw.get("started_at")
            stage.finished_at = raw.get("finished_at")
        return record

    def save(self) -> None:
        path = job_state_path(self.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    @classmethod
    def load(cls, job_id: str) -> "JobRecord | None":
        path = job_state_path(job_id)
        if not path.exists():
            return None
        try:
            return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, KeyError):
            return None


class StateReporter(JobReporter):
    """Reporter que mantém um `JobRecord` salvo em disco.

    `on_event(kind, payload)` permite plugar broadcast (SSE) por cima.
    """

    def __init__(
        self,
        record: JobRecord,
        on_event: Callable[[str, Any], None] | None = None,
        persist: bool = True,
    ):
        self.record = record
        self._on_event = on_event
        self._persist = persist

    def _emit(self, kind: str, payload: Any, persist: bool = True) -> None:
        if self._persist and persist:
            self.record.save()
        if self._on_event:
            self._on_event(kind, payload)

    # --- JobReporter ---------------------------------------------------------
    def stage(
        self,
        key: str,
        status: str = "running",
        progress: float | None = None,
        message: str = "",
    ) -> None:
        stage = self.record.update_stage(key, status, progress, message)
        if stage is None:
            return
        self._emit("stage", stage.to_dict())

    def log(self, message: str, level: str = "info") -> None:
        entry = self.record.add_log(message, level)
        self._emit("log", entry, persist=False)

    def source(self, info: dict) -> None:
        self.record.source = info
        self._emit("source", info)

    def estimate(self, estimate: dict) -> None:
        self.record.estimate = estimate
        self._emit("estimate", estimate)

    def selection(self, stats: dict) -> None:
        self.record.selection = stats
        self._emit("selection", stats)

    def clip(self, clip: dict) -> None:
        self.record.set_clip(clip)
        self._emit("clip", clip)

    def check_cancel(self) -> None:
        if self.record.cancel_requested:
            raise JobCanceled("cancelado pelo usuário")


def create_record(options: JobOptions, job_id: str | None = None) -> JobRecord:
    record = JobRecord(id=job_id or new_job_id(), options=options)
    job_dir(record.id).mkdir(parents=True, exist_ok=True)
    record.save()
    return record
