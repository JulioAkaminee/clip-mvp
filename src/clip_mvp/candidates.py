"""Geração de candidatos a corte + decisão automática de N (SPEC §3, §14.1)."""

from __future__ import annotations

import math
from importlib import resources
from typing import Any

from .boundaries import snap_window
from .config import Settings
from .models import Candidate, Transcript, Window
from .openrouter import OpenRouterClient

# Heurística de faixa alvo de cortes finais por duração da fonte (SPEC §3).
_AUTO_RANGE_TABLE: list[tuple[float, tuple[int, int]]] = [
    (10 * 60, (2, 4)),
    (30 * 60, (3, 6)),
    (90 * 60, (5, 10)),
    (math.inf, (8, 15)),
]


def auto_count_range(duration_s: float) -> tuple[int, int]:
    """Faixa alvo (min, max) de cortes finais, conforme a tabela da SPEC §3."""
    for ceiling, rng in _AUTO_RANGE_TABLE:
        if duration_s < ceiling:
            return rng
    return _AUTO_RANGE_TABLE[-1][1]


def resolve_target_range(
    duration_s: float,
    *,
    more: bool = False,
    count: int | None = None,
) -> tuple[int, int]:
    """Resolve a faixa alvo final considerando --more / --count (SPEC §3).

    `--count N` força um teto de N (ainda sujeito ao limiar de score: nunca
    inventa clip fraco). `--more` pede ~+50% do que o auto escolheria.
    """
    lo, hi = auto_count_range(duration_s)
    if count is not None:
        return (1, max(1, count))
    if more:
        lo = max(1, math.ceil(lo * 1.5))
        hi = max(lo, math.ceil(hi * 1.5))
    return (lo, hi)


def candidate_pool_size(target_hi: int) -> int:
    """LLM gera ~2-3x a faixa alvo de candidatos amplos (SPEC §3.1)."""
    return max(6, math.ceil(target_hi * 2.5))


def _load_prompt(name: str) -> str:
    return resources.files("clip_mvp.prompts").joinpath(name).read_text(encoding="utf-8")


def _transcript_excerpt_for_prompt(transcript: Transcript, max_chars: int = 12000) -> str:
    lines = []
    for seg in transcript.segments:
        lines.append(f"[{seg.start:.1f}-{seg.end:.1f}] {seg.text}")
    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n... (truncado)"
    return text


def _format_feedback_examples(examples: list[dict[str, Any]] | None) -> str:
    if not examples:
        return ""
    parts = ["\nExemplos de feedback anterior do usuário (few-shot, use para calibrar gosto):"]
    for ex in examples:
        verdict = ex.get("verdict", "?")
        reason = ex.get("reason", "")
        note = ex.get("note", "")
        parts.append(f"- [{verdict}] score={ex.get('score')} reason={reason!r} nota_usuario={note!r}")
    return "\n".join(parts)


def _parse_candidate(raw: dict[str, Any], idx: int) -> Candidate | None:
    w16 = raw.get("window_16x9")
    if not w16:
        return None
    w9 = raw.get("window_9x16")
    return Candidate(
        id=f"cand_{idx:03d}",
        title=str(raw.get("title", f"Momento {idx + 1}"))[:200],
        text_excerpt=str(raw.get("text_excerpt", ""))[:2000],
        window_9x16=Window(start=float(w9["start"]), end=float(w9["end"])) if w9 else None,
        window_16x9=Window(start=float(w16["start"]), end=float(w16["end"])),
        context_complete=bool(raw.get("context_complete", True)),
        llm_notes=str(raw.get("llm_notes", ""))[:1000],
        vertical_skip_reason=raw.get("vertical_skip_reason"),
    )


def generate_candidates(
    transcript: Transcript,
    settings: Settings,
    *,
    target_hi: int,
    client: OpenRouterClient | None = None,
    feedback_examples: list[dict[str, Any]] | None = None,
) -> list[Candidate]:
    """Chama o modelo de candidatos na OpenRouter e retorna candidatos com
    janelas já ajustadas por fronteira de palavra + padding (SPEC §14.1)."""
    client = client or OpenRouterClient(settings)
    pool_size = candidate_pool_size(target_hi)

    system = _load_prompt("candidates_pt.md")
    user = (
        f"Duração total do vídeo: {transcript.duration:.1f}s.\n"
        f"Gere aproximadamente {pool_size} candidatos amplos e diversos.\n\n"
        f"Transcrição (formato [inicio-fim] texto):\n{_transcript_excerpt_for_prompt(transcript)}"
        f"{_format_feedback_examples(feedback_examples)}"
    )

    result = client.chat_json(model=settings.candidate_model, system=system, user=user)
    raw_candidates = result.get("candidates", [])

    words = transcript.all_words()
    pad_before = settings.pad_ms_min / 1000.0
    pad_after = settings.pad_ms_max / 1000.0

    candidates: list[Candidate] = []
    for i, raw in enumerate(raw_candidates):
        cand = _parse_candidate(raw, i)
        if cand is None:
            continue
        cand.window_16x9 = _snap(cand.window_16x9, words, transcript, pad_before, pad_after)
        if cand.window_9x16 is not None:
            snapped = _snap(cand.window_9x16, words, transcript, pad_before, pad_after)
            if snapped.duration_s > settings.vertical_max_s:
                cand.window_9x16 = None
                cand.vertical_skip_reason = "context_exceeds_90s"
            else:
                cand.window_9x16 = snapped
        candidates.append(cand)

    return candidates


def _snap(window: Window, words, transcript: Transcript, pad_before: float, pad_after: float) -> Window:
    result = snap_window(
        window.start,
        window.end,
        words=words,
        segments=transcript.segments,
        pad_before_s=pad_before,
        pad_after_s=pad_after,
        media_duration=transcript.duration or None,
    )
    return Window(start=result.start, end=result.end)
