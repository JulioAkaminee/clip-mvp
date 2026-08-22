"""Transcrição PT-BR via OpenRouter (chunks ~10 min, word timestamps)."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from . import demo as demo_mod
from .audio import extract_audio, split_audio
from .config import Settings
from .ffmpeg_utils import duration_of
from .openrouter import OpenRouterClient
from .transcript import Segment, Transcript, Word

ProgressFn = Callable[[float, str], None]


def transcribe(
    source: Path,
    work_dir: Path,
    settings: Settings,
    on_progress: ProgressFn | None = None,
    duration_hint: float | None = None,
) -> Transcript:
    """Devolve a transcrição, com cache em `work/<job>/transcript.json`."""
    cache = work_dir / "transcript.json"
    if cache.exists():
        if on_progress:
            on_progress(1.0, "transcrição em cache reaproveitada")
        return Transcript.load(cache)

    duration = duration_hint or duration_of(source)

    if not settings.ai_enabled:
        transcript = demo_mod.build_transcript(duration, seed=source.name)
        if on_progress:
            on_progress(1.0, "transcrição sintética (modo demo, sem OpenRouter)")
        transcript.save(cache)
        return transcript

    if on_progress:
        on_progress(0.05, "extraindo áudio normalizado para STT")
    audio_path = extract_audio(source, work_dir / "audio.mp3", normalize=True)
    chunks = split_audio(audio_path, work_dir / "audio_chunks")

    client = OpenRouterClient(settings)
    segments: list[Segment] = []
    for i, (chunk, offset) in enumerate(chunks):
        if on_progress:
            on_progress(
                0.1 + 0.9 * (i / max(1, len(chunks))),
                f"STT chunk {i + 1}/{len(chunks)}",
            )
        payload = client.transcribe(chunk, settings.stt_model, language="pt")
        segments.extend(_parse_stt(payload, offset))

    segments.sort(key=lambda s: s.start)
    transcript = Transcript(
        duration=duration,
        segments=segments,
        language="pt",
        stt_model=settings.stt_model,
        diarization=any(s.speaker for s in segments),
    )
    transcript.save(cache)
    if on_progress:
        on_progress(1.0, f"{len(segments)} segmentos transcritos")
    return transcript


def _parse_stt(payload: dict, offset: float) -> list[Segment]:
    """Normaliza `verbose_json` (com fallback quando não há word timestamps)."""
    raw_words = payload.get("words") or []
    words = [
        Word(
            start=float(w.get("start", 0.0)) + offset,
            end=float(w.get("end", w.get("start", 0.0))) + offset,
            text=str(w.get("word") or w.get("text") or "").strip(),
        )
        for w in raw_words
        if str(w.get("word") or w.get("text") or "").strip()
    ]

    raw_segments = payload.get("segments") or []
    if not raw_segments:
        text = (payload.get("text") or "").strip()
        if not text:
            return []
        end = words[-1].end if words else offset
        return [Segment(start=offset, end=end, text=text, words=words)]

    segments: list[Segment] = []
    for raw in raw_segments:
        start = float(raw.get("start", 0.0)) + offset
        end = float(raw.get("end", start)) + offset
        seg_words = [w for w in words if w.start >= start - 0.05 and w.end <= end + 0.05]
        if not seg_words and raw.get("words"):
            seg_words = [
                Word(
                    start=float(w.get("start", start)) + offset,
                    end=float(w.get("end", start)) + offset,
                    text=str(w.get("word") or w.get("text") or "").strip(),
                )
                for w in raw["words"]
                if str(w.get("word") or w.get("text") or "").strip()
            ]
        segments.append(
            Segment(
                start=start,
                end=end,
                text=(raw.get("text") or "").strip(),
                speaker=raw.get("speaker") or raw.get("speaker_id"),
                words=seg_words,
            )
        )
    return segments
