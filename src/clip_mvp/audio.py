"""Áudio: extração para STT, chunking e loudnorm (SPEC 14.2)."""

from __future__ import annotations

import math
from pathlib import Path

from .ffmpeg_utils import duration_of, run

LOUDNORM_FILTER = "loudnorm=I=-16:TP=-1.5:LRA=11"
"""Alvo de diálogo consistente entre falantes/cortes, sem pico estourado."""

STT_CHUNK_SECONDS = 600
"""~10 min por chunk (SPEC 6) para respeitar o limite do endpoint STT."""


def extract_audio(source: Path, dest: Path, normalize: bool = True) -> Path:
    """Extrai mono 16 kHz para STT (opcionalmente já normalizado)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    filters = ["aresample=16000"]
    if normalize:
        filters.append(LOUDNORM_FILTER)
    run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            "-vn",
            "-ac",
            "1",
            "-af",
            ",".join(filters),
            "-c:a",
            "libmp3lame",
            "-b:a",
            "64k",
            str(dest),
        ]
    )
    return dest


def split_audio(source: Path, out_dir: Path, chunk_s: int = STT_CHUNK_SECONDS) -> list[tuple[Path, float]]:
    """Divide o áudio em pedaços; devolve (arquivo, offset_em_segundos)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    total = duration_of(source)
    if total <= chunk_s:
        return [(source, 0.0)]
    chunks: list[tuple[Path, float]] = []
    count = math.ceil(total / chunk_s)
    for i in range(count):
        offset = i * chunk_s
        dest = out_dir / f"chunk_{i:03d}.mp3"
        run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-ss",
                f"{offset}",
                "-t",
                f"{chunk_s}",
                "-i",
                str(source),
                "-c",
                "copy",
                str(dest),
            ]
        )
        if dest.exists():
            chunks.append((dest, float(offset)))
    return chunks
