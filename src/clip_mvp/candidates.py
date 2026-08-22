"""Candidatos + decisão de N (SPEC 3).

A IA decide **quais** e **quantos** momentos valem corte; `--more` e `--count`
só mexem no alvo, nunca forçam a criação de corte ruim. Todas as janelas
devolvidas pelo LLM passam pela validação determinística de `boundaries`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .boundaries import Window, fit_vertical, snap_window
from .config import Settings, VERTICAL_MAX_S, target_range
from .feedback import few_shot_block
from .models import Candidate
from .openrouter import OpenRouterClient
from .paths import slugify
from .transcript import Transcript, transcript_as_prompt_lines

ProgressFn = Callable[[float, str], None]

MIN_CLIP_S = 12.0
CANDIDATE_POOL_FACTOR = 2.5
"""Pool amplo: ~2–3× a faixa alvo (SPEC 3)."""

PROMPTS_DIR = Path(__file__).parent / "prompts"


@dataclass
class CountPlan:
    mode: str
    target_min: int
    target_max: int
    pool: int

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "target_min": self.target_min,
            "target_max": self.target_max,
            "pool": self.pool,
        }


def plan_count(
    duration_s: float,
    mode: str = "auto",
    count: int | None = None,
    pool_cap: int = 40,
) -> CountPlan:
    """Faixa alvo + tamanho do pool de candidatos."""
    lo, hi = target_range(duration_s)
    if mode == "more":
        lo = max(1, math.ceil(lo * 1.5))
        hi = max(lo, math.ceil(hi * 1.5))
    elif mode == "count" and count:
        lo, hi = max(1, min(count, count)), max(1, count)
    pool = min(pool_cap, max(6, math.ceil(hi * CANDIDATE_POOL_FACTOR)))
    return CountPlan(mode=mode, target_min=lo, target_max=hi, pool=pool)


def generate(
    transcript: Transcript,
    settings: Settings,
    plan: CountPlan,
    on_progress: ProgressFn | None = None,
) -> list[Candidate]:
    if settings.ai_enabled:
        raw = _llm_candidates(transcript, settings, plan, on_progress)
    else:
        raw = _demo_candidates(transcript, plan)
        if on_progress:
            on_progress(0.9, f"{len(raw)} candidatos heurísticos (modo demo)")
    candidates = [c for c in (_normalize(transcript, item, i) for i, item in enumerate(raw)) if c]
    candidates.sort(key=lambda c: c.horizontal.start)
    if on_progress:
        on_progress(1.0, f"{len(candidates)} candidatos com contexto validado")
    return candidates


# --- LLM ---------------------------------------------------------------------
def _llm_candidates(
    transcript: Transcript,
    settings: Settings,
    plan: CountPlan,
    on_progress: ProgressFn | None,
) -> list[dict]:
    prompt = (PROMPTS_DIR / "candidates_pt.md").read_text(encoding="utf-8")
    prompt = (
        prompt.replace("{n_candidates}", str(plan.pool))
        .replace("{target_min}", str(plan.target_min))
        .replace("{target_max}", str(plan.target_max))
    )
    feedback = few_shot_block(settings)
    user = (
        f"Duração da fonte: {transcript.duration / 60:.1f} min.\n"
        f"Limite do 9:16: {VERTICAL_MAX_S:.0f}s.\n\n"
        f"{feedback}\n\nTRANSCRIÇÃO COM TIMESTAMPS:\n"
        f"{transcript_as_prompt_lines(transcript)}"
    )
    if on_progress:
        on_progress(0.2, f"pedindo {plan.pool} candidatos ao LLM")
    client = OpenRouterClient(settings)
    data = client.chat_json(
        settings.candidate_model,
        [
            {"role": "system", "content": prompt},
            {"role": "user", "content": user},
        ],
        temperature=0.5,
        max_tokens=6000,
    )
    items = data.get("candidates") or data.get("items") or []
    if on_progress:
        on_progress(0.9, f"LLM devolveu {len(items)} candidatos")
    return [item for item in items if isinstance(item, dict)]


# --- Heurística offline (modo demo) ------------------------------------------
def _demo_candidates(transcript: Transcript, plan: CountPlan) -> list[dict]:
    segments = transcript.segments
    if not segments:
        return []
    wanted = plan.pool
    step = max(2, len(segments) // max(1, wanted))
    items: list[dict] = []
    index = 0
    while index < len(segments) and len(items) < wanted:
        block: list = []
        cursor = index
        target = 45.0 + 25.0 * ((len(items) % 3))
        while cursor < len(segments):
            block.append(segments[cursor])
            cursor += 1
            if block[-1].end - block[0].start >= target:
                break
        # O turno tem que fechar: se o mesmo falante continua, o bloco continua.
        while cursor < len(segments) and segments[cursor].speaker == block[-1].speaker:
            block.append(segments[cursor])
            cursor += 1
        if not block:
            break
        start, end = block[0].start, block[-1].end
        if end - start >= MIN_CLIP_S:
            single_speaker = len({s.speaker for s in block if s.speaker}) == 1
            vertical: dict | None
            if end - start > VERTICAL_MAX_S and single_speaker:
                # Monólogo: o raciocínio só fecha no fim → não cabe em 9:16.
                vertical = None
            else:
                v_start = start
                for seg in block:
                    if end - seg.start <= VERTICAL_MAX_S - 6:
                        v_start = seg.start
                        break
                vertical = {"start": v_start, "end": end}
            items.append(
                {
                    "id": f"c{len(items) + 1}",
                    "title": _short_title(block[0].text),
                    "reason": "Bloco com pergunta, resposta e fecho no último trecho.",
                    "horizontal": {"start": start, "end": end},
                    "vertical": vertical,
                    "context_complete": True,
                }
            )
        index += step
    return items


def _short_title(text: str, max_len: int = 66) -> str:
    text = (text or "corte").strip().rstrip(".,;:")
    if len(text) <= max_len:
        return text
    return text[:max_len].rsplit(" ", 1)[0]


# --- Validação determinística ------------------------------------------------
def _normalize(transcript: Transcript, raw: dict, index: int) -> Candidate | None:
    horizontal_raw = raw.get("horizontal") or raw.get("window") or {}
    try:
        h_start = float(horizontal_raw.get("start"))
        h_end = float(horizontal_raw.get("end"))
    except (TypeError, ValueError):
        return None
    if h_end <= h_start:
        return None

    horizontal = snap_window(transcript, h_start, h_end)
    if horizontal.duration < MIN_CLIP_S:
        return None

    vertical, skipped = _vertical_window(transcript, raw, horizontal)
    title = (raw.get("title") or "corte").strip()
    candidate = Candidate(
        id=str(raw.get("id") or f"c{index + 1}"),
        title=title,
        reason=(raw.get("reason") or "").strip(),
        horizontal=horizontal,
        vertical=vertical,
        transcript_text=transcript.text_between(horizontal.start, horizontal.end),
        context_complete=horizontal.context_complete and bool(raw.get("context_complete", True)),
        vertical_skipped=skipped,
        slug=slugify(title),
    )
    return candidate


def _vertical_window(
    transcript: Transcript, raw: dict, horizontal: Window
) -> tuple[Window | None, str | None]:
    """Aplica o teto de 90s sem nunca truncar frase (SPEC 2)."""
    raw_vertical = raw.get("vertical")
    if raw_vertical is None:
        # A IA sinalizou que o contexto mínimo não cabe em 9:16: só 16:9.
        return None, "context_exceeds_90s"

    try:
        v_start = float(raw_vertical.get("start"))
        v_end = float(raw_vertical.get("end"))
    except (TypeError, ValueError):
        return None, "vertical_window_invalida"
    if v_end <= v_start:
        return None, "vertical_window_invalida"

    snapped = snap_window(transcript, v_start, v_end, max_duration=VERTICAL_MAX_S)
    window = fit_vertical(transcript, snapped) or fit_vertical(transcript, horizontal)
    if window is None or window.duration > VERTICAL_MAX_S or not window.context_complete:
        return None, "context_exceeds_90s"
    return window, None
