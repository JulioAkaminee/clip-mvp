"""Estimativa de custo OpenRouter — `--dry-run` / `--budget` (SPEC 14.4).

Os preços são aproximações configuráveis por env; o objetivo é dar ordem de
grandeza *antes* do passo caro (score com vision).
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass

STT_USD_PER_MIN = float(os.environ.get("CLIP_MVP_COST_STT_PER_MIN", "0.006"))
CANDIDATES_USD_PER_1K_TOKENS = float(os.environ.get("CLIP_MVP_COST_TEXT_PER_1K", "0.0004"))
VISION_USD_PER_CANDIDATE = float(os.environ.get("CLIP_MVP_COST_VISION_PER_CLIP", "0.0035"))
META_USD_PER_CLIP = float(os.environ.get("CLIP_MVP_COST_META_PER_CLIP", "0.0008"))

CHARS_PER_TOKEN = 4.0


@dataclass
class CostLine:
    step: str
    detail: str
    usd: float


@dataclass
class Estimate:
    duration_s: float
    candidates: int
    selected: int
    lines: list[CostLine]
    total_usd: float
    within_budget: bool = True
    budget_usd: float | None = None
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "duration_s": round(self.duration_s, 1),
            "candidates": self.candidates,
            "selected": self.selected,
            "lines": [asdict(line) for line in self.lines],
            "total_usd": round(self.total_usd, 4),
            "within_budget": self.within_budget,
            "budget_usd": self.budget_usd,
            "note": self.note,
        }


def estimate(
    duration_s: float,
    candidates: int,
    selected: int,
    transcript_chars: int | None = None,
    budget_usd: float | None = None,
) -> Estimate:
    minutes = max(0.0, duration_s) / 60.0
    # ~140 palavras/min ≈ 6 chars/palavra quando não temos a transcrição ainda.
    chars = transcript_chars if transcript_chars is not None else int(minutes * 140 * 6)
    tokens = chars / CHARS_PER_TOKEN

    lines = [
        CostLine("stt", f"{minutes:.1f} min de áudio", minutes * STT_USD_PER_MIN),
        CostLine(
            "candidatos",
            f"~{tokens / 1000:.1f}k tokens de transcrição",
            (tokens / 1000.0) * CANDIDATES_USD_PER_1K_TOKENS,
        ),
        CostLine(
            "score (vision)",
            f"{candidates} candidatos × 3 frames",
            candidates * VISION_USD_PER_CANDIDATE,
        ),
        CostLine(
            "meta (títulos/hashtags)",
            f"{selected} cortes × YT + TikTok",
            selected * META_USD_PER_CLIP,
        ),
    ]
    total = sum(line.usd for line in lines)
    est = Estimate(
        duration_s=duration_s,
        candidates=candidates,
        selected=selected,
        lines=lines,
        total_usd=total,
        budget_usd=budget_usd,
    )
    if budget_usd is not None:
        est.within_budget = total <= budget_usd
        if not est.within_budget:
            est.note = (
                f"estimativa US$ {total:.2f} acima do orçamento US$ {budget_usd:.2f}"
            )
    return est


def fit_candidates_to_budget(
    duration_s: float,
    candidates: int,
    selected: int,
    budget_usd: float,
    transcript_chars: int | None = None,
    min_candidates: int = 4,
) -> tuple[int, Estimate]:
    """Reduz o nº de candidatos até caber no orçamento (SPEC 14.4).

    Devolve `(candidatos_permitidos, estimativa)`. Se nem o piso couber, a
    estimativa volta com `within_budget=False` para o job abortar com mensagem.
    """
    n = candidates
    est = estimate(duration_s, n, selected, transcript_chars, budget_usd)
    while not est.within_budget and n > min_candidates:
        n -= 1
        est = estimate(duration_s, n, min(selected, n), transcript_chars, budget_usd)
    if est.within_budget and n < candidates:
        est.note = f"candidatos reduzidos de {candidates} para {n} pelo orçamento"
    return n, est
