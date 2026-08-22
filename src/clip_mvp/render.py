"""Render dos formatos de saída: 9:16 center, 16:9, (+ 9:16 facetrack em face_track.py).

SPEC §1, §5, §7, §14.2, §14.5.
"""

from __future__ import annotations

from pathlib import Path

from .audio import LOUDNORM_I, LOUDNORM_LRA, LOUDNORM_TP
from .models import Window
from .utils import run_ffmpeg

VERTICAL_SIZE = (1080, 1920)
HORIZONTAL_SIZE = (1920, 1080)

LOUDNORM_FILTER = f"loudnorm=I={LOUDNORM_I}:TP={LOUDNORM_TP}:LRA={LOUDNORM_LRA}"


def _seek_args(video_path: Path, window: Window) -> list[str]:
    """Seek híbrido: -ss grosseiro antes do -i (rápido) + -ss fino depois
    (preciso), evitando decodificar o vídeo inteiro até o ponto de corte."""
    pre_seek = max(0.0, window.start - 2.0)
    offset = window.start - pre_seek
    duration = max(0.05, window.end - window.start)
    return [
        "-ss",
        f"{pre_seek:.3f}",
        "-i",
        str(video_path),
        "-ss",
        f"{offset:.3f}",
        "-t",
        f"{duration:.3f}",
    ]


def _subtitles_filter(ass_path: Path | None) -> str | None:
    if ass_path is None:
        return None
    escaped = str(ass_path).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
    return f"subtitles=filename='{escaped}'"


def render_vertical_center(
    video_path: Path,
    window: Window,
    out_path: Path,
    *,
    ass_path: Path | None = None,
    size: tuple[int, int] = VERTICAL_SIZE,
) -> Path:
    """Render 9:16 center crop, SEM face tracking (SPEC §9)."""
    w, h = size
    vf_parts = ["crop=ih*9/16:ih", f"scale={w}:{h}"]
    sub = _subtitles_filter(ass_path)
    if sub:
        vf_parts.append(sub)
    vf = ",".join(vf_parts)

    args = _seek_args(video_path, window) + [
        "-vf",
        vf,
        "-af",
        LOUDNORM_FILTER,
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-c:a",
        "aac",
        "-movflags",
        "+faststart",
        str(out_path),
    ]
    run_ffmpeg(args)
    return Path(out_path)


def render_horizontal_16x9(
    video_path: Path,
    window: Window,
    out_path: Path,
    *,
    ass_path: Path | None = None,
    size: tuple[int, int] = HORIZONTAL_SIZE,
) -> Path:
    """Render 16:9 trim limpo, SEM face tracking (SPEC §9)."""
    w, h = size
    vf_parts = [
        f"scale={w}:{h}:force_original_aspect_ratio=increase",
        f"crop={w}:{h}",
    ]
    sub = _subtitles_filter(ass_path)
    if sub:
        vf_parts.append(sub)
    vf = ",".join(vf_parts)

    args = _seek_args(video_path, window) + [
        "-vf",
        vf,
        "-af",
        LOUDNORM_FILTER,
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-c:a",
        "aac",
        "-movflags",
        "+faststart",
        str(out_path),
    ]
    run_ffmpeg(args)
    return Path(out_path)


def cut_raw(video_path: Path, window: Window, out_path: Path) -> Path:
    """Corte simples por timestamp, sem crop/legendas (usado por testes de
    fronteira e como utilitário de baixo nível, SPEC §12 passo 1)."""
    args = _seek_args(video_path, window) + [
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-c:a",
        "aac",
        str(out_path),
    ]
    run_ffmpeg(args)
    return Path(out_path)
