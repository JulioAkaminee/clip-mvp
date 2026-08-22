"""Layout de arquivos por job/clip."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from .config import get_settings

ARTIFACTS = (
    "vertical_facetrack.mp4",
    "vertical_center.mp4",
    "horizontal_16x9.mp4",
    "captions.srt",
    "captions.ass",
    "meta.json",
    "poster.jpg",
)


def slugify(text: str, max_len: int = 48) -> str:
    normalized = unicodedata.normalize("NFKD", text or "")
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii").lower()
    ascii_text = re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")
    ascii_text = re.sub(r"-{2,}", "-", ascii_text)
    return (ascii_text[:max_len].strip("-")) or "clip"


def job_dir(job_id: str) -> Path:
    return get_settings().work_dir / job_id


def job_state_path(job_id: str) -> Path:
    return job_dir(job_id) / "job.json"


def job_events_path(job_id: str) -> Path:
    return job_dir(job_id) / "events.jsonl"


def job_out_dir(job_id: str) -> Path:
    return get_settings().out_dir / job_id


def clip_out_dir(job_id: str, score: int, slug: str) -> Path:
    return job_out_dir(job_id) / f"{score:02d}_{slug}"


def safe_child(base: Path, name: str) -> Path:
    """Resolve `name` dentro de `base`, barrando path traversal (usado pela API)."""
    candidate = (base / name).resolve()
    base_resolved = base.resolve()
    if base_resolved != candidate and base_resolved not in candidate.parents:
        raise ValueError(f"caminho fora do diretório permitido: {name}")
    return candidate
