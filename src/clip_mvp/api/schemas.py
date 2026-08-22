"""Contratos da API (pydantic) — a UI depende só destes formatos."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from ..config import ALL_FORMATS, ALL_PLATFORMS, CAPTION_MODES, DEFAULT_MIN_SCORE

FormatName = Literal["vertical_facetrack", "vertical_center", "horizontal_16x9"]
CaptionMode = Literal["burn", "sidecar", "both"]
Platform = Literal["yt", "tiktok"]
Mode = Literal["auto", "more", "count"]


class JobOptionsIn(BaseModel):
    url: str = Field(..., description="URL do vídeo (YouTube/Twitch/...) ou caminho local")
    mode: Mode = "auto"
    count: int | None = Field(None, ge=1, le=30, description="Força até N cortes (--count)")
    min_score: int = Field(DEFAULT_MIN_SCORE, ge=0, le=100)
    max_score_only: int | None = Field(None, ge=0, le=100)
    formats: list[FormatName] = Field(default_factory=lambda: list(ALL_FORMATS))
    captions: CaptionMode = "both"
    platforms: list[Platform] = Field(default_factory=lambda: list(ALL_PLATFORMS))
    dry_run: bool = False
    budget_usd: float | None = Field(None, ge=0)
    demo: bool | None = None

    @field_validator("url")
    @classmethod
    def _url_not_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("informe a URL do vídeo")
        return value

    @field_validator("formats")
    @classmethod
    def _formats_not_empty(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("escolha pelo menos um formato")
        return value

    @field_validator("captions")
    @classmethod
    def _captions_valid(cls, value: str) -> str:
        if value not in CAPTION_MODES:
            raise ValueError(f"captions deve ser um de {CAPTION_MODES}")
        return value


class ResumeIn(BaseModel):
    mode: Mode = "more"
    count: int | None = Field(None, ge=1, le=30)
    min_score: int | None = Field(None, ge=0, le=100)


class RateIn(BaseModel):
    verdict: Literal["good", "bad"]
    note: str = ""


class StageOut(BaseModel):
    key: str
    label: str
    status: Literal["pending", "running", "done", "skipped", "error"]
    progress: float = 0.0
    message: str = ""
    started_at: float | None = None
    finished_at: float | None = None


class LogEntryOut(BaseModel):
    t: float
    level: str
    message: str


class ClipOut(BaseModel):
    slug: str
    title: str
    score: int
    breakdown: dict[str, int] = Field(default_factory=dict)
    reason: str = ""
    context_complete: bool = True
    boundary_method: str = "word"
    windows: dict[str, Any] = Field(default_factory=dict)
    vertical_skipped: str | None = None
    face_track: str | None = None
    artifacts: dict[str, str] = Field(default_factory=dict)
    transcript_text: str = ""
    meta: dict[str, Any] | None = None
    rating: str | None = None
    rating_note: str | None = None


class JobOut(BaseModel):
    id: str
    url: str
    status: Literal["queued", "running", "done", "error", "canceled"]
    created_at: float
    started_at: float | None = None
    finished_at: float | None = None
    options: dict[str, Any]
    source: dict[str, Any] = Field(default_factory=dict)
    stages: list[StageOut] = Field(default_factory=list)
    selection: dict[str, Any] | None = None
    estimate: dict[str, Any] | None = None
    clips: list[ClipOut] = Field(default_factory=list)
    error: str | None = None
    log: list[LogEntryOut] = Field(default_factory=list)
    resumed_from: str | None = None


class JobListOut(BaseModel):
    jobs: list[JobOut]
    running: str | None = None
    queued: list[str] = Field(default_factory=list)


class HealthOut(BaseModel):
    ok: bool
    version: str
    ffmpeg: bool
    ffprobe: bool
    yt_dlp: bool
    mediapipe: bool
    openrouter_key: bool
    demo_mode: bool
    models: dict[str, str]
    work_dir: str
    out_dir: str


class ConfigOut(BaseModel):
    formats: list[str]
    platforms: list[str]
    caption_modes: list[str]
    default_min_score: int
    vertical_max_s: float
    pad_ms: list[int]
    safe_area_bottom: float
    target_ranges: list[dict[str, Any]]


class EstimateOut(BaseModel):
    duration_s: float
    candidates: int
    selected: int
    lines: list[dict[str, Any]]
    total_usd: float
    within_budget: bool
    budget_usd: float | None = None
    note: str = ""
    source: dict[str, Any] = Field(default_factory=dict)
