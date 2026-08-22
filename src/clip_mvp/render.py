"""Render dos exports com ffmpeg (SPEC 6 e 7).

Todo export sai com áudio normalizado (loudnorm) e `+faststart` para tocar
direto no player do navegador. Face tracking só entra no `vertical_facetrack`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .audio import LOUDNORM_FILTER
from .boundaries import Window
from .face_track import TrackResult
from .ffmpeg_utils import run, video_size

VERTICAL_W, VERTICAL_H = 1080, 1920
HORIZONTAL_W, HORIZONTAL_H = 1280, 720
VIDEO_ARGS = [
    "-c:v",
    "libx264",
    "-preset",
    "veryfast",
    "-crf",
    "21",
    "-pix_fmt",
    "yuv420p",
    "-c:a",
    "aac",
    "-b:a",
    "128k",
    "-ar",
    "48000",
    "-movflags",
    "+faststart",
]


@dataclass
class RenderResult:
    path: Path
    format: str
    duration_s: float
    burned_captions: bool
    face_track: str | None = None


def _base_cmd(source: Path, window: Window) -> list[str]:
    return [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        f"{window.start:.3f}",
        "-t",
        f"{window.duration:.3f}",
        "-i",
        str(source),
    ]


def _audio_filter() -> list[str]:
    return ["-af", f"asetpts=PTS-STARTPTS,{LOUDNORM_FILTER}"]


def _crop_size(width: int, height: int) -> tuple[int, int]:
    """Maior recorte 9:16 que cabe na fonte (par, para yuv420p)."""
    crop_w = min(width, int(height * 9 / 16))
    crop_h = min(height, int(crop_w * 16 / 9))
    return crop_w - (crop_w % 2), crop_h - (crop_h % 2)


def render_horizontal(
    source: Path,
    window: Window,
    out_path: Path,
    ass_name: str | None = None,
    work_dir: Path | None = None,
) -> RenderResult:
    """16:9 com trim limpo, sem face tracking; legenda opcional (lower third)."""
    work_dir = work_dir or out_path.parent
    filters = [
        "setpts=PTS-STARTPTS",
        f"scale={HORIZONTAL_W}:{HORIZONTAL_H}:force_original_aspect_ratio=decrease",
        f"pad={HORIZONTAL_W}:{HORIZONTAL_H}:(ow-iw)/2:(oh-ih)/2",
        "setsar=1",
    ]
    if ass_name:
        filters.append(f"ass={ass_name}")
    cmd = [
        *_base_cmd(source, window),
        "-vf",
        ",".join(filters),
        *_audio_filter(),
        *VIDEO_ARGS,
        out_path.name,
    ]
    run(cmd, cwd=work_dir)
    return RenderResult(
        path=out_path,
        format="horizontal_16x9",
        duration_s=window.duration,
        burned_captions=bool(ass_name),
    )


def render_vertical_center(
    source: Path,
    window: Window,
    out_path: Path,
    ass_name: str | None = None,
    work_dir: Path | None = None,
) -> RenderResult:
    """9:16 center crop, sem tracking."""
    work_dir = work_dir or out_path.parent
    width, height = video_size(source)
    crop_w, crop_h = _crop_size(width or 1280, height or 720)
    filters = [
        "setpts=PTS-STARTPTS",
        f"crop={crop_w}:{crop_h}:(iw-{crop_w})/2:(ih-{crop_h})/2",
        f"scale={VERTICAL_W}:{VERTICAL_H}",
        "setsar=1",
    ]
    if ass_name:
        filters.append(f"ass={ass_name}")
    cmd = [
        *_base_cmd(source, window),
        "-vf",
        ",".join(filters),
        *_audio_filter(),
        *VIDEO_ARGS,
        out_path.name,
    ]
    run(cmd, cwd=work_dir)
    return RenderResult(
        path=out_path,
        format="vertical_center",
        duration_s=window.duration,
        burned_captions=bool(ass_name),
    )


def write_sendcmd(
    keyframes: list[tuple[float, float]],
    crop_w: int,
    frame_width: int,
    dest: Path,
) -> None:
    """Arquivo de comandos do ffmpeg movendo o `x` do crop no tempo."""
    lines: list[str] = []
    last_x: int | None = None
    max_x = max(0, frame_width - crop_w)
    for t, center in keyframes:
        x = int(round(min(max(center - crop_w / 2.0, 0), max_x)))
        if last_x is not None and x == last_x:
            continue
        lines.append(f"{max(0.0, t):.3f} crop x {x};")
        last_x = x
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")


def render_vertical_facetrack(
    source: Path,
    window: Window,
    out_path: Path,
    tracking: TrackResult,
    ass_name: str | None = None,
    work_dir: Path | None = None,
) -> RenderResult:
    """9:16 seguindo o rosto (ou quem está falando, quando há diarização)."""
    work_dir = work_dir or out_path.parent
    width, height = video_size(source)
    width, height = width or 1280, height or 720
    crop_w, crop_h = _crop_size(width, height)

    if not tracking.available:
        result = render_vertical_center(source, window, out_path, ass_name, work_dir)
        return RenderResult(
            path=result.path,
            format="vertical_facetrack",
            duration_s=result.duration_s,
            burned_captions=result.burned_captions,
            face_track="center_fallback",
        )

    cmd_file = work_dir / f"{out_path.stem}_track.cmd"
    write_sendcmd(tracking.keyframes, crop_w, width, cmd_file)
    initial_x = int(
        round(min(max(tracking.keyframes[0][1] - crop_w / 2.0, 0), max(0, width - crop_w)))
    )
    filters = [
        "setpts=PTS-STARTPTS",
        f"sendcmd=f={cmd_file.name}",
        f"crop={crop_w}:{crop_h}:{initial_x}:(ih-{crop_h})/2",
        f"scale={VERTICAL_W}:{VERTICAL_H}",
        "setsar=1",
    ]
    if ass_name:
        filters.append(f"ass={ass_name}")
    cmd = [
        *_base_cmd(source, window),
        "-vf",
        ",".join(filters),
        *_audio_filter(),
        *VIDEO_ARGS,
        out_path.name,
    ]
    run(cmd, cwd=work_dir)
    return RenderResult(
        path=out_path,
        format="vertical_facetrack",
        duration_s=window.duration,
        burned_captions=bool(ass_name),
        face_track=tracking.method,
    )


def render_poster(source: Path, at: float, out_path: Path, width: int = 640) -> Path:
    """Thumbnail usado nos cards da UI."""
    run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            f"{max(0.0, at):.3f}",
            "-i",
            str(source),
            "-frames:v",
            "1",
            "-vf",
            f"scale={width}:-2",
            "-q:v",
            "4",
            str(out_path),
        ]
    )
    return out_path
