"""Áudio: extração e normalização de loudness (SPEC §1, §14.2)."""

from __future__ import annotations

from pathlib import Path

from .utils import run_ffmpeg

# Alvo EBU R128 típico para diálogo/podcast.
LOUDNORM_I = "-16.0"
LOUDNORM_TP = "-1.5"
LOUDNORM_LRA = "11.0"

#: Taxa de amostragem obrigatória na saída.
#:
#: O filtro `loudnorm` reamostra internamente para 192 kHz. Sem um `-ar`
#: explícito o encoder AAC herda essa taxa e o arquivo sai em 96 kHz — que o
#: ffmpeg lê sem reclamar, mas nenhum navegador decodifica: o `<video>` trava
#: em readyState 0, sem imagem, sem som e sem erro. 48 kHz é o teto do AAC-LC
#: em Chrome, Safari e Firefox, e o que TikTok e YouTube esperam.
OUTPUT_SAMPLE_RATE = 48000

#: Argumentos de áudio de todo export final.
AUDIO_ENCODE_ARGS: list[str] = ["-c:a", "aac", "-b:a", "192k", "-ar", str(OUTPUT_SAMPLE_RATE), "-ac", "2"]


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
    args += ["-ar", str(OUTPUT_SAMPLE_RATE), str(out_path)]
    run_ffmpeg(args)
    return out_path
