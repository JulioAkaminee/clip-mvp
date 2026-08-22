"""Áudio: extração e normalização de loudness (SPEC §1, §14.2)."""

from __future__ import annotations

from pathlib import Path

from .utils import run_ffmpeg

# Alvo EBU R128 típico para diálogo/podcast.
LOUDNORM_I = "-16.0"
LOUDNORM_TP = "-1.5"
LOUDNORM_LRA = "11.0"


def extract_audio(video_path: Path, out_path: Path, sample_rate: int = 16000) -> Path:
    """Extrai áudio mono do vídeo para uso no STT (wav 16kHz)."""
    out_path = Path(out_path)
    run_ffmpeg(
        [
            "-i",
            str(video_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            str(out_path),
        ]
    )
    return out_path


def loudnorm(in_path: Path, out_path: Path, *, video: bool = False) -> Path:
    """Aplica ffmpeg loudnorm (single-pass) para consistência de loudness
    entre falantes/cortes (SPEC §14.2). Evita picos estourados após o crop."""
    in_path = Path(in_path)
    out_path = Path(out_path)
    filter_arg = f"loudnorm=I={LOUDNORM_I}:TP={LOUDNORM_TP}:LRA={LOUDNORM_LRA}"

    args = ["-i", str(in_path)]
    if video:
        args += ["-af", filter_arg, "-c:v", "copy"]
    else:
        args += ["-af", filter_arg]
    args += [str(out_path)]
    run_ffmpeg(args)
    return out_path
