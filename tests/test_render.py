"""Testes de render (corte por timestamp, aspect ratio) usando ffmpeg real
sobre o fixture de vídeo (SPEC §12 passo 1, §14.5)."""

from __future__ import annotations

from pathlib import Path

from clip_mvp.models import Window
from clip_mvp.render import (
    HORIZONTAL_SIZE,
    VERTICAL_SIZE,
    cut_raw,
    render_horizontal_16x9,
    render_vertical_center,
)
from clip_mvp.utils import ffprobe_duration


def _video_dims(path: Path) -> tuple[int, int]:
    import json
    import subprocess

    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(out.stdout)["streams"][0]
    return data["width"], data["height"]


def test_cut_raw_produces_correct_duration(tmp_path: Path, sample_video_path: Path):
    window = Window(start=2.0, end=6.0)
    out = tmp_path / "cut.mp4"
    cut_raw(sample_video_path, window, out)

    assert out.exists()
    duration = ffprobe_duration(out)
    assert abs(duration - window.duration_s) < 0.35


def test_cut_raw_respects_boundaries_near_start_and_end(tmp_path: Path, sample_video_path: Path):
    # Corte próximo ao início e ao fim do vídeo-fonte (bordas), sem estourar.
    window = Window(start=0.0, end=1.0)
    out = tmp_path / "cut_start.mp4"
    cut_raw(sample_video_path, window, out)
    assert abs(ffprobe_duration(out) - 1.0) < 0.35


def test_render_vertical_center_produces_9x16(tmp_path: Path, sample_video_path: Path):
    window = Window(start=1.0, end=5.0)
    out = tmp_path / "vertical_center.mp4"
    render_vertical_center(sample_video_path, window, out)

    assert out.exists()
    w, h = _video_dims(out)
    assert (w, h) == VERTICAL_SIZE
    assert abs(ffprobe_duration(out) - window.duration_s) < 0.5


def test_render_horizontal_16x9_produces_16x9(tmp_path: Path, sample_video_path: Path):
    window = Window(start=0.5, end=6.0)
    out = tmp_path / "horizontal_16x9.mp4"
    render_horizontal_16x9(sample_video_path, window, out)

    assert out.exists()
    w, h = _video_dims(out)
    assert (w, h) == HORIZONTAL_SIZE
    assert abs(ffprobe_duration(out) - window.duration_s) < 0.5
