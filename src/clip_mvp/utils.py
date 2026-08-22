"""Utilitários gerais: slugs, diretórios de job, ffprobe."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import time
import unicodedata
from pathlib import Path


def slugify(text: str, max_len: int = 40) -> str:
    """Gera um slug ASCII simples a partir de um texto (título de clip, etc.)."""
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    text = re.sub(r"-{2,}", "-", text)
    if not text:
        text = "clip"
    return text[:max_len].strip("-") or "clip"


def make_job_id(url: str) -> str:
    """job_id determinístico a partir da URL, para permitir `resume` fácil."""
    h = hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]
    return f"job_{h}"


def job_dir(work_dir: Path, job_id: str) -> Path:
    d = Path(work_dir) / job_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def out_clip_dir(out_dir: Path, score: int, slug: str) -> Path:
    d = Path(out_dir) / f"{score}_{slug}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def read_json(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def ffprobe_duration(path: Path) -> float:
    """Duração em segundos de um arquivo de mídia via ffprobe."""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(path),
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True)
    data = json.loads(out.stdout)
    return float(data["format"]["duration"])


def run_ffmpeg(args: list[str], quiet: bool = True) -> None:
    """Executa ffmpeg com args (sem o binário `ffmpeg` no início)."""
    cmd = ["ffmpeg", "-y"] + args
    proc = subprocess.run(
        cmd,
        stdout=subprocess.DEVNULL if quiet else None,
        stderr=subprocess.PIPE if quiet else None,
        text=True,
    )
    if proc.returncode != 0:
        stderr = proc.stderr or ""
        raise RuntimeError(f"ffmpeg falhou (cmd={' '.join(cmd)}):\n{stderr[-4000:]}")


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
