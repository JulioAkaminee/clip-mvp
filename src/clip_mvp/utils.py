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


def source_title(job_dir: Path) -> str:
    """Título do vídeo de origem, para a lista de jobs.

    Todo job de YouTube tem a mesma URL visível (`youtube.com/watch`), então a
    lista lateral mostrava a mesma linha para todos — impossível dizer qual é
    qual. O título real vem do `source.info.json` que o yt-dlp grava junto com
    o download.

    Fica cacheado em `job.json` na primeira leitura: jobs criados antes desta
    função não têm o campo, e reler o `.info.json` (que passa de 1MB) a cada
    listagem seria desperdício.
    """
    job_dir = Path(job_dir)
    job_file = job_dir / "job.json"
    meta = read_json(job_file) if job_file.is_file() else {}
    cached = (meta.get("source_title") or "").strip()
    if cached:
        return cached

    info_file = job_dir / "source.info.json"
    if not info_file.is_file():
        return ""
    try:
        title = str(read_json(info_file).get("title") or "").strip()
    except Exception:  # noqa: BLE001 - título é conforto, não pode quebrar a lista
        return ""
    if title and meta:
        try:
            write_json(job_file, {**meta, "source_title": title})
        except Exception:  # noqa: BLE001
            pass
    return title
