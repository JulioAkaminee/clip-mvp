"""Score de viralização (texto + 3 frames) — SPEC 8."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Callable

from .config import Settings
from .feedback import few_shot_block
from .ffmpeg_utils import extract_frames
from .models import Breakdown, Candidate
from .openrouter import OpenRouterClient, image_part

ProgressFn = Callable[[float, str], None]
PROMPTS_DIR = Path(__file__).parent / "prompts"

TRUNCATED_PENALTY = 0.55
"""Trecho sem contexto fechado: score derrubado (SPEC 8)."""


def score_candidates(
    candidates: list[Candidate],
    source: Path,
    work_dir: Path,
    settings: Settings,
    on_progress: ProgressFn | None = None,
) -> list[Candidate]:
    cache_path = work_dir / "scores.json"
    cache: dict[str, dict] = {}
    if cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            cache = {}

    prompt = (PROMPTS_DIR / "score_pt.md").read_text(encoding="utf-8")
    feedback = few_shot_block(settings)
    client = OpenRouterClient(settings) if settings.ai_enabled else None

    for i, candidate in enumerate(candidates):
        key = _cache_key(candidate)
        if on_progress:
            on_progress(i / max(1, len(candidates)), f"score {i + 1}/{len(candidates)}")
        if key in cache:
            _apply(candidate, cache[key])
            continue
        if client is None:
            result = _heuristic_score(candidate)
        else:
            result = _vision_score(
                client, settings, prompt, feedback, candidate, source, work_dir
            )
        cache[key] = result
        _apply(candidate, result)

    cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    if on_progress:
        on_progress(1.0, f"{len(candidates)} candidatos pontuados")
    return candidates


def _cache_key(candidate: Candidate) -> str:
    raw = f"{candidate.horizontal.start:.2f}-{candidate.horizontal.end:.2f}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def _apply(candidate: Candidate, result: dict) -> None:
    candidate.breakdown = Breakdown.from_dict(result.get("breakdown"))
    candidate.score = int(result.get("score") or candidate.breakdown.total)
    if result.get("reason"):
        candidate.reason = result["reason"]
    if result.get("context_complete") is not None:
        candidate.context_complete = bool(result["context_complete"]) and candidate.context_complete
    if not candidate.context_complete:
        candidate.score = int(candidate.score * TRUNCATED_PENALTY)


def _vision_score(
    client: OpenRouterClient,
    settings: Settings,
    prompt: str,
    feedback: str,
    candidate: Candidate,
    source: Path,
    work_dir: Path,
) -> dict:
    window = candidate.horizontal
    mid = window.start + window.duration / 2
    frames_dir = work_dir / "frames" / candidate.id
    frames: list[Path] = []
    try:
        frames = extract_frames(
            source,
            [window.start + 0.5, mid, max(window.start, window.end - 1.0)],
            frames_dir,
        )
    except Exception:
        frames = []

    content: list[dict] = [
        {
            "type": "text",
            "text": (
                f"{feedback}\n\nDuração do corte: {window.duration:.1f}s "
                f"(9:16 {'disponível' if candidate.vertical else 'descartado por contexto >90s'}).\n"
                f"Trecho:\n{candidate.transcript_text[:6000]}"
            ),
        }
    ]
    content.extend(image_part(frame) for frame in frames)
    return client.chat_json(
        settings.score_model,
        [
            {"role": "system", "content": prompt},
            {"role": "user", "content": content},
        ],
        temperature=0.2,
        max_tokens=800,
    )


def _heuristic_score(candidate: Candidate) -> dict:
    """Score determinístico do modo demo (sem vision)."""
    seed = int(hashlib.sha1(candidate.transcript_text.encode()).hexdigest()[:8], 16)
    text = candidate.transcript_text
    words = len(text.split())
    hook = 12 + (seed % 11)
    emocao = 11 + ((seed >> 4) % 12)
    citavel = 10 + ((seed >> 8) % 13)
    arco = 14 + ((seed >> 12) % 10)
    if any(mark in text for mark in ("?", "!")):
        hook = min(25, hook + 3)
    if words > 120:
        arco = min(25, arco + 3)
    if not candidate.context_complete:
        arco = 3
    breakdown = {"hook": hook, "emocao": emocao, "citavel": citavel, "arco": arco}
    return {
        "score": sum(breakdown.values()),
        "breakdown": breakdown,
        "context_complete": candidate.context_complete,
        "reason": candidate.reason
        or "Bloco abre com pergunta e fecha com resposta completa (score heurístico do modo demo).",
    }
