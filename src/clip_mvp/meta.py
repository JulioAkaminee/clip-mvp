"""`meta.json`: títulos, hashtags e captions YT + TikTok (SPEC 7 e 10)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from .config import Settings
from .models import Candidate, SelectionStats
from .openrouter import OpenRouterClient

PROMPTS_DIR = Path(__file__).parent / "prompts"

STOPWORDS = {
    "que", "para", "com", "uma", "por", "mais", "isso", "você", "voce", "não",
    "nao", "dos", "das", "mas", "como", "meu", "minha", "seu", "sua", "eles",
    "elas", "num", "numa", "pra", "sobre", "aquilo", "esse", "essa", "está",
    "esta", "muito", "quando", "tinha", "porque", "acho", "gente", "todo",
}


def social_text(
    candidate: Candidate,
    settings: Settings,
    platforms: tuple[str, ...] = ("yt", "tiktok"),
) -> dict:
    if settings.ai_enabled:
        try:
            return _llm_social(candidate, settings)
        except Exception:
            pass
    return _template_social(candidate, platforms)


def _llm_social(candidate: Candidate, settings: Settings) -> dict:
    prompt = (PROMPTS_DIR / "meta_pt.md").read_text(encoding="utf-8")
    client = OpenRouterClient(settings)
    data = client.chat_json(
        settings.meta_model,
        [
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": (
                    f"Título de trabalho: {candidate.title}\n"
                    f"Motivo do corte: {candidate.reason}\n"
                    f"Duração 16:9: {candidate.horizontal.duration:.0f}s\n\n"
                    f"Transcrição do corte:\n{candidate.transcript_text[:6000]}"
                ),
            },
        ],
        temperature=0.7,
        max_tokens=1200,
    )
    youtube = data.get("youtube") or {}
    tiktok = data.get("tiktok") or {}
    if not youtube and not tiktok:
        raise ValueError("resposta do LLM sem youtube/tiktok")
    return {"youtube": youtube, "tiktok": tiktok}


def _keywords(text: str, limit: int = 6) -> list[str]:
    words = re.findall(r"[A-Za-zÀ-ÿ]{4,}", (text or "").lower())
    seen: list[str] = []
    for word in words:
        if word in STOPWORDS or word in seen:
            continue
        seen.append(word)
        if len(seen) >= limit:
            break
    return seen


def _hashtag(word: str) -> str:
    return "#" + re.sub(r"[^a-z0-9]", "", word.lower())


def _template_social(candidate: Candidate, platforms: tuple[str, ...]) -> dict:
    title = (candidate.title or "Corte").strip().rstrip(".")
    short_title = title if len(title) <= 60 else title[:57].rsplit(" ", 1)[0] + "..."
    keys = _keywords(f"{candidate.title} {candidate.transcript_text}")
    tags = keys[:6]
    result: dict = {}
    if "yt" in platforms:
        result["youtube"] = {
            "shorts_title": short_title,
            "long_title": (title if len(title) <= 80 else title[:77] + "..."),
            "description": (
                f"{candidate.reason or short_title}\n\n"
                "Corte gerado com clip-mvp. Inscreva-se para mais trechos."
            ),
            "tags": tags,
            "hashtags": ["#Shorts", *[_hashtag(k) for k in keys[:3]]],
        }
    if "tiktok" in platforms:
        result["tiktok"] = {
            "caption": short_title if short_title.endswith("?") else f"{short_title} 👀",
            "hashtags": [_hashtag(k) for k in keys[:4]] + ["#cortes", "#podcastbr"],
        }
    return result


def build_meta(
    candidate: Candidate,
    source_url: str,
    source_title: str,
    stats: SelectionStats,
    settings: Settings,
    exports: dict[str, str],
    social: dict,
    face_track_method: str | None,
    captions_mode: str,
) -> dict:
    windows: dict = {
        "horizontal_16x9": {
            "start": round(candidate.horizontal.start, 3),
            "end": round(candidate.horizontal.end, 3),
            "duration_s": round(candidate.horizontal.duration, 3),
        }
    }
    if candidate.vertical:
        windows["vertical_9x16"] = {
            "start": round(candidate.vertical.start, 3),
            "end": round(candidate.vertical.end, 3),
            "duration_s": round(candidate.vertical.duration, 3),
        }
    meta = {
        "source_url": source_url,
        "source_title": source_title,
        "title": candidate.title,
        "slug": candidate.slug,
        "context_complete": candidate.context_complete,
        "boundary_method": candidate.horizontal.method,
        "windows": windows,
        "vertical_skipped": candidate.vertical_skipped,
        "score": candidate.score,
        "breakdown": candidate.breakdown.to_dict(),
        "reason": candidate.reason,
        "selection": stats.to_dict(),
        "exports": exports,
        "captions": captions_mode,
        "face_track": face_track_method,
        "audio": {"loudnorm": True, "target_i": -16},
        "caption_safe_area": {"bottom_fraction": 0.20},
    }
    meta.update(social)
    return meta


def write_meta(path: Path, meta: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
