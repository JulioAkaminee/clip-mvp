"""Diarização (speaker↔rosto) com fallback documentado (SPEC §9, §14.6).

Fluxo:
1. Tenta diarização via OpenRouter, no modelo do papel de diarização
   (configurável na tela de Configurações; vazio = mesmo modelo de STT). Se a
   resposta não tiver speaker labels (a maioria dos modelos Whisper-compatíveis
   na OpenRouter não expõe isso hoje — SPEC §15), cai no fallback.
2. Fallback documentado (`activity_proxy`): sem diarização de áudio, o
   `face_track.detect_face_centers` já escolhe, por padrão, o rosto de maior
   área (mais "em foco"/central) como proxy de quem está falando — é uma
   heurística simples e barata (Mac i5 16GB friendly), no lugar de uma
   análise completa de movimento de boca por frame. O método usado é sempre
   registrado em `meta.json.speaker_matching.method`.
"""

from __future__ import annotations

from pathlib import Path

from .config import Settings
from .models import DiarizationResult, SpeakerSegment
from .openrouter import OpenRouterClient


def diarize(audio_path: Path, settings: Settings, *, client: OpenRouterClient | None = None) -> DiarizationResult:
    """Tenta diarização via OpenRouter; retorna `method="unavailable"` se o
    provider não expuser speaker labels (fallback tratado por quem chama)."""
    client = client or OpenRouterClient(settings)
    try:
        raw = client.transcribe(
            audio_path, language="pt", model=settings.model_for_diarization()
        )
    except Exception:
        return DiarizationResult(segments=[], method="unavailable")

    raw_segments = raw.get("segments") or []
    speaker_segments: list[SpeakerSegment] = []
    for seg in raw_segments:
        speaker = seg.get("speaker") or seg.get("speaker_id")
        if speaker is None:
            continue
        speaker_segments.append(
            SpeakerSegment(start=float(seg.get("start", 0.0)), end=float(seg.get("end", 0.0)), speaker=str(speaker))
        )

    if not speaker_segments:
        return DiarizationResult(segments=[], method="unavailable")

    return DiarizationResult(segments=speaker_segments, method="diarization")


def speaker_at(diarization: DiarizationResult, t: float) -> str | None:
    for seg in diarization.segments:
        if seg.start <= t < seg.end:
            return seg.speaker
    return None


def resolve_speaker_matching_method(diarization: DiarizationResult | None) -> str:
    """Método a registrar em meta.json.speaker_matching.method (SPEC §14.6)."""
    if diarization is not None and diarization.method == "diarization" and diarization.segments:
        return "diarization"
    return "activity_proxy"
