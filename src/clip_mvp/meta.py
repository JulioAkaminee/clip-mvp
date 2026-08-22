"""meta.json: títulos/hashtags/captions YT + TikTok (SPEC §7, §10)."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
from typing import Any

from .config import Settings
from .models import Candidate, Score, Window
from .openrouter import OpenRouterClient


def _load_prompt(name: str) -> str:
    return resources.files("clip_mvp.prompts").joinpath(name).read_text(encoding="utf-8")


def fallback_social_copy(title: str, excerpt: str = "") -> dict[str, Any]:
    """Textos publicáveis mesmo se a IA de meta falhar."""
    raw = (title or "Corte do podcast").strip()
    if raw.lower().startswith("o hook"):
        raw = "esse momento do podcast"
    replacements = {
        "infancia": "infância",
        "ambicoes": "ambições",
        "influencia": "influência",
        "musica": "música",
        "irmao": "irmão",
        "cachaca": "cachaça",
        "sao paulo": "São Paulo",
    }
    lowered = raw.lower()
    for old, new in replacements.items():
        lowered = lowered.replace(old, new)
    topic = lowered[:1].upper() + lowered[1:]
    topic_l = topic.lower()
    shorts_options = [
        f"A virada sobre {topic_l}",
        f"Ele conta tudo: {topic_l}",
        f"O recorte de {topic_l}",
    ]
    shorts = shorts_options[sum(ord(ch) for ch in topic_l) % 3][:58]
    long_title = f"{topic}: do começo da pergunta até a resposta fechar"[:70]
    hook = topic
    yt_desc = (
        f"{shorts}\n\n"
        f"Corte do podcast sobre {topic.lower()}. Assunto fechado, sem corte no meio da fala.\n\n"
        "#Shorts #Podcast #Cortes"
    )
    yt_long = (
        f"{long_title}\n\n"
        f"O momento completo sobre {topic.lower()} — do começo da pergunta até a resposta fechar.\n"
        "Se curtiu, assiste o episódio inteiro.\n\n"
        "#Podcast #Cortes #YouTube"
    )
    return {
        "youtube": {
            "shorts_title": shorts,
            "description": yt_desc,
            "long_title": long_title,
            "horizontal_title": long_title,
            "horizontal_description": yt_long,
            "tags": ["podcast", "cortes", "entrevista", topic.lower()],
            "hashtags": ["#Shorts", "#Podcast", "#Cortes"],
        },
        "tiktok": {
            "title": shorts,
            "caption": hook[:140],
            "hashtags": ["#fyp", "#podcastbr", "#cortes", "#viral"],
        },
    }


def _merge_social(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    out = {"youtube": dict(base.get("youtube") or {}), "tiktok": dict(base.get("tiktok") or {})}
    for net in ("youtube", "tiktok"):
        incoming = extra.get(net) or {}
        if isinstance(incoming, dict):
            for key, value in incoming.items():
                if value:
                    out[net][key] = value
    return out


@dataclass
class SocialCopy:
    """Textos sociais + de onde eles vieram.

    O fallback existe para o job nunca travar por causa de copy, mas engolir a
    falha em silêncio fazia todo corte sair com título de template sem ninguém
    ficar sabendo que o modelo de textos nunca respondeu.
    """

    copy: dict[str, Any]
    source: str = "llm"
    error: str = ""

    @property
    def is_fallback(self) -> bool:
        return self.source == "fallback"


def generate_social_copy(
    candidate: Candidate,
    settings: Settings,
    *,
    client: OpenRouterClient | None = None,
) -> SocialCopy:
    """Gera títulos/descrições/hashtags PT-BR para YouTube e TikTok (SPEC §10)."""
    fallback = fallback_social_copy(candidate.title, candidate.text_excerpt)
    try:
        client = client or OpenRouterClient(settings)
        system = _load_prompt("meta_pt.md")
        user = (
            f"Título de trabalho: {candidate.title}\n"
            f"Trecho da transcrição: {candidate.text_excerpt}\n"
            f"Contexto adicional: {candidate.llm_notes}"
        )
        generated = client.chat_json(model=settings.meta_model, system=system, user=user)
        if isinstance(generated, dict) and (generated.get("youtube") or generated.get("tiktok")):
            return SocialCopy(copy=_merge_social(fallback, generated), source="llm")
        return SocialCopy(
            copy=fallback,
            source="fallback",
            error="o modelo de textos respondeu sem os campos de YouTube/TikTok",
        )
    except Exception as exc:  # noqa: BLE001 - o job não pode travar por causa de copy
        return SocialCopy(copy=fallback, source="fallback", error=str(exc)[:200])


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
    subtitles: dict[str, Any] | None = None,
    copy_source: str = "llm",
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
            # O 9:16 pode ser uma sub-janela do 16:9 (contexto >90s encolhido,
            # SPEC §2). Quem publica precisa saber disso sem abrir o vídeo.
            "context_complete": bool(candidate.vertical_context_complete),
            "shrunk_from_16x9": bool(candidate.vertical_shrunk),
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
        "copy_source": copy_source,
        "youtube": social_copy.get("youtube", {}),
        "tiktok": social_copy.get("tiktok", {}),
        "subtitles": subtitles
        or {
            "style": "viral",
            "position_v": 0.2,
            "font_size": 1.0,
            "color": "#FFDE00",
            "outline_color": "#000000",
            "uppercase": True,
            "highlight": "pop",
            "highlight_color": "#FFFFFF",
        },
    }
