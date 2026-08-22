"""STT via OpenRouter (Whisper) — verbose_json / word timestamps (SPEC §14.1)."""

from __future__ import annotations

import math
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .config import Settings
from .models import Segment, Transcript, Word
from .openrouter import OpenRouterClient
from .utils import ffprobe_duration, run_ffmpeg, write_json

CHUNK_SECONDS_DEFAULT = 600  # ~10 min, SPEC §6


def _split_audio(audio_path: Path, chunk_seconds: int, tmp_dir: Path) -> list[tuple[Path, float]]:
    """Divide o áudio em pedaços de `chunk_seconds`, retornando (path, offset_s)."""
    duration = ffprobe_duration(audio_path)
    if duration <= chunk_seconds:
        return [(audio_path, 0.0)]

    n_chunks = math.ceil(duration / chunk_seconds)
    chunks: list[tuple[Path, float]] = []
    for i in range(n_chunks):
        offset = i * chunk_seconds
        chunk_path = tmp_dir / f"chunk_{i:03d}.wav"
        run_ffmpeg(
            [
                "-i",
                str(audio_path),
                "-ss",
                str(offset),
                "-t",
                str(chunk_seconds),
                "-ac",
                "1",
                str(chunk_path),
            ]
        )
        chunks.append((chunk_path, float(offset)))
    return chunks


def _parse_verbose_json(raw: dict[str, Any], offset_s: float, id_start: int) -> list[Segment]:
    """Converte a resposta verbose_json (Whisper) em Segments com Words,
    aplicando o offset do chunk. Tolerante a formatos levemente diferentes
    entre providers na OpenRouter (SPEC §15)."""
    raw_segments = raw.get("segments") or []
    raw_words = raw.get("words") or []

    words_all = [
        Word(
            start=float(w.get("start", 0.0)) + offset_s,
            end=float(w.get("end", 0.0)) + offset_s,
            text=str(w.get("word", w.get("text", ""))).strip(),
        )
        for w in raw_words
    ]

    segments: list[Segment] = []
    if raw_segments:
        for i, seg in enumerate(raw_segments):
            seg_start = float(seg.get("start", 0.0)) + offset_s
            seg_end = float(seg.get("end", seg_start)) + offset_s
            seg_words = [w for w in words_all if seg_start - 0.05 <= w.start <= seg_end + 0.05]
            segments.append(
                Segment(
                    id=id_start + i,
                    start=seg_start,
                    end=seg_end,
                    text=str(seg.get("text", "")).strip(),
                    words=seg_words,
                )
            )
    elif words_all:
        # Sem segmentos, mas com palavras: cria um único segmento cobrindo tudo.
        text = raw.get("text", "") or " ".join(w.text for w in words_all)
        segments.append(
            Segment(
                id=id_start,
                start=words_all[0].start,
                end=words_all[-1].end,
                text=text.strip(),
                words=words_all,
            )
        )
    elif raw.get("text"):
        segments.append(
            Segment(
                id=id_start,
                start=offset_s,
                end=offset_s,
                text=str(raw["text"]).strip(),
                words=[],
            )
        )

    return segments


def transcribe_audio(
    audio_path: Path,
    settings: Settings,
    *,
    client: OpenRouterClient | None = None,
    language: str = "pt",
    chunk_seconds: int = CHUNK_SECONDS_DEFAULT,
) -> Transcript:
    """Transcreve o áudio completo (com chunking ~10min) via OpenRouter Whisper.

    `client` pode ser injetado (ex.: em testes) para evitar chamadas de rede.
    """
    client = client or OpenRouterClient(settings)
    audio_path = Path(audio_path)

    tmp_dir = Path(tempfile.mkdtemp(prefix="clip_mvp_stt_"))
    try:
        chunks = _split_audio(audio_path, chunk_seconds, tmp_dir)
        all_segments: list[Segment] = []
        next_id = 0
        for chunk_path, offset in chunks:
            raw = client.transcribe(chunk_path, language=language)
            segs = _parse_verbose_json(raw, offset, next_id)
            all_segments.extend(segs)
            next_id += len(segs)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    duration = all_segments[-1].end if all_segments else 0.0
    has_words = any(seg.words for seg in all_segments)

    return Transcript(
        language=language,
        duration=duration,
        segments=all_segments,
        source="openrouter_whisper",
        has_word_timestamps=has_words,
    )


def dump_transcript(transcript: Transcript, job_dir: Path) -> Path:
    """Salva a transcrição em work/<job_id>/transcript.json (SPEC §5)."""
    path = Path(job_dir) / "transcript.json"
    write_json(path, transcript.model_dump())
    return path


def load_transcript(job_dir: Path) -> Transcript:
    from .utils import read_json

    path = Path(job_dir) / "transcript.json"
    return Transcript.model_validate(read_json(path))
