"""Wrappers finos de ffmpeg/ffprobe."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


class FFmpegError(RuntimeError):
    pass


def require_ffmpeg() -> None:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise FFmpegError(
            "ffmpeg/ffprobe não encontrados. Instale com `brew install ffmpeg` (macOS)."
        )


def run(cmd: list[str], timeout: float | None = None, cwd: Path | None = None) -> str:
    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=timeout,
        cwd=str(cwd) if cwd else None,
    )
    if proc.returncode != 0:
        tail = "\n".join((proc.stdout or "").strip().splitlines()[-20:])
        raise FFmpegError(f"comando falhou ({' '.join(cmd[:3])}...):\n{tail}")
    return proc.stdout or ""


def probe(path: Path) -> dict:
    out = run(
        [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ]
    )
    return json.loads(out or "{}")


def duration_of(path: Path) -> float:
    info = probe(path)
    fmt_duration = (info.get("format") or {}).get("duration")
    if fmt_duration:
        return float(fmt_duration)
    for stream in info.get("streams", []):
        if stream.get("duration"):
            return float(stream["duration"])
    return 0.0


def video_size(path: Path) -> tuple[int, int]:
    for stream in probe(path).get("streams", []):
        if stream.get("codec_type") == "video":
            return int(stream.get("width") or 0), int(stream.get("height") or 0)
    return 0, 0


def extract_frames(
    source: Path, timestamps: list[float], out_dir: Path, width: int = 512
) -> list[Path]:
    """Um JPEG por timestamp (usado pelo score com vision e pelo poster)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    frames: list[Path] = []
    for i, ts in enumerate(timestamps):
        dest = out_dir / f"frame_{i}.jpg"
        run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-ss",
                f"{max(0.0, ts):.3f}",
                "-i",
                str(source),
                "-frames:v",
                "1",
                "-vf",
                f"scale={width}:-2",
                "-q:v",
                "4",
                str(dest),
            ]
        )
        if dest.exists():
            frames.append(dest)
    return frames
