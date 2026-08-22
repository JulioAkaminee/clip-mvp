"""meta.json: títulos/hashtags/captions YT + TikTok (SPEC §7, §10)."""

from __future__ import annotations

from importlib import resources
from typing import Any

from .config import Settings
from .models import Candidate, Score, Window
from .openrouter import OpenRouterClient


def _load_prompt(name: str) -> str:
    return resources.files("clip_mvp.prompts").joinpath(name).read_text(encoding="utf-8")


def generate_social_copy(
    candidate: Candidate,
    settings: Settings,
    *,
    client: OpenRouterClient | None = None,
) -> dict[str, Any]:
    """Gera títulos/descrições/hashtags PT-BR para YouTube e TikTok (SPEC §10)."""
    client = client or OpenRouterClient(settings)
    system = _load_prompt("meta_pt.md")
    user = (
        f"Título de trabalho: {candidate.title}\n"
        f"Trecho da transcrição: {candidate.text_excerpt}\n"
        f"Contexto adicional: {candidate.llm_notes}"
    )
    return client.chat_json(model=settings.meta_model, system=system, user=user)


def build_meta(
    *,
    source_url: str,
    candidate: Candidate,
    score: Score,
    window_9x16: Window | None,
    window_16x9: Window,
    vertical_skipped: str | None,
    selection: dict[str, Any],
    social_copy: dict[str, Any],
    speaker_matching_method: str,
    boundary_info: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Monta o dict final de meta.json seguindo o formato da SPEC §7."""
    windows: dict[str, Any] = {
        "horizontal_16x9": {
            "start": window_16x9.start,
            "end": window_16x9.end,
            "duration_s": window_16x9.duration_s,
        }
    }
    if window_9x16 is not None:
        windows["vertical_9x16"] = {
            "start": window_9x16.start,
            "end": window_9x16.end,
            "duration_s": window_9x16.duration_s,
        }

    return {
        "source_url": source_url,
        "context_complete": bool(score.context_complete and candidate.context_complete),
        "windows": windows,
        "vertical_skipped": vertical_skipped,
        "score": round(score.total),
        "breakdown": {
            "hook": score.breakdown.hook,
            "emocao": score.breakdown.emocao,
            "citavel": score.breakdown.citavel,
            "arco": score.breakdown.arco,
        },
        "reason": score.reason,
        "selection": selection,
        "boundaries": boundary_info
        or {
            "word_level_snapping": True,
            "never_mid_word": True,
        },
        "speaker_matching": {"method": speaker_matching_method},
        "youtube": social_copy.get("youtube", {}),
        "tiktok": social_copy.get("tiktok", {}),
    }
