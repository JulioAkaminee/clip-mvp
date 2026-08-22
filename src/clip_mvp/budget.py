"""Estimativa de custo OpenRouter + --dry-run / --budget (SPEC §14.4)."""

from __future__ import annotations

from .config import Settings
from .models import CostEstimate


def estimate_cost(duration_s: float, n_candidates: int, settings: Settings) -> CostEstimate:
    """Estima custo (USD) de STT + candidatos (texto) + score (vision), ANTES
    do passo caro de vision. Valores aproximados/configuráveis via .env —
    servem só para decisão de orçamento, não são cobrança real (SPEC §14.4)."""
    stt_minutes = duration_s / 60.0
    stt_usd = stt_minutes * settings.cost_stt_usd_per_min
    text_usd = n_candidates * settings.cost_text_usd_per_candidate
    vision_usd = n_candidates * settings.frames_per_score * settings.cost_vision_usd_per_frame
    total = stt_usd + text_usd + vision_usd
    return CostEstimate(
        stt_minutes=round(stt_minutes, 2),
        stt_usd=round(stt_usd, 4),
        n_candidates=n_candidates,
        text_usd=round(text_usd, 4),
        vision_usd=round(vision_usd, 4),
        total_usd=round(total, 4),
    )


def max_candidates_for_budget(duration_s: float, budget_usd: float, settings: Settings) -> int:
    """Maior nº de candidatos que cabe no orçamento (dado o custo fixo de STT).
    Retorna 0 se nem o STT sozinho couber no orçamento."""
    stt_minutes = duration_s / 60.0
    stt_usd = stt_minutes * settings.cost_stt_usd_per_min
    remaining = budget_usd - stt_usd
    if remaining <= 0:
        return 0
    per_candidate = settings.cost_text_usd_per_candidate + (
        settings.frames_per_score * settings.cost_vision_usd_per_frame
    )
    if per_candidate <= 0:
        return 10**9
    return max(0, int(remaining // per_candidate))


def apply_budget(
    duration_s: float,
    n_candidates: int,
    budget_usd: float | None,
    settings: Settings,
) -> tuple[int, str | None]:
    """Reduz `n_candidates` para caber no orçamento, ou retorna aviso claro se
    nem 1 candidato couber (SPEC §14.4). Retorna (n_candidates_permitido, aviso)."""
    if budget_usd is None:
        return n_candidates, None

    allowed = max_candidates_for_budget(duration_s, budget_usd, settings)
    if allowed <= 0:
        return 0, (
            f"Orçamento de ${budget_usd:.2f} não cobre nem a transcrição estimada "
            f"(~${duration_s / 60.0 * settings.cost_stt_usd_per_min:.2f}). Abortando."
        )
    if allowed < n_candidates:
        return allowed, (
            f"Orçamento de ${budget_usd:.2f} reduz candidatos de {n_candidates} para {allowed}."
        )
    return n_candidates, None
