"""Testes de estimativa de custo + --dry-run / --budget (SPEC §14.4)."""

from __future__ import annotations

from clip_mvp.budget import apply_budget, estimate_cost, max_candidates_for_budget
from clip_mvp.config import Settings


def _settings() -> Settings:
    return Settings(
        openrouter_api_key="test-key",
        cost_stt_usd_per_min=0.01,
        cost_text_usd_per_candidate=0.001,
        cost_vision_usd_per_frame=0.002,
        frames_per_score=3,
    )


def test_estimate_cost_scales_with_duration_and_candidates():
    settings = _settings()
    cheap = estimate_cost(60, 5, settings)
    expensive = estimate_cost(6000, 20, settings)
    assert expensive.total_usd > cheap.total_usd
    assert cheap.stt_minutes == 1.0


def test_estimate_cost_breaks_down_components():
    settings = _settings()
    est = estimate_cost(600, 10, settings)
    assert est.stt_usd == round(10 * 0.01, 4)
    assert est.text_usd == round(10 * 0.001, 4)
    assert est.vision_usd == round(10 * 3 * 0.002, 4)
    assert est.total_usd == round(est.stt_usd + est.text_usd + est.vision_usd, 4)


def test_max_candidates_for_budget_zero_when_stt_alone_exceeds_budget():
    settings = _settings()
    assert max_candidates_for_budget(duration_s=100 * 60, budget_usd=0.5, settings=settings) == 0


def test_apply_budget_none_means_unlimited():
    settings = _settings()
    n, warning = apply_budget(600, 20, None, settings)
    assert n == 20
    assert warning is None


def test_apply_budget_reduces_candidates_when_over_budget():
    settings = _settings()
    n, warning = apply_budget(600, 50, 0.15, settings)
    assert 0 < n < 50
    assert warning is not None


def test_apply_budget_aborts_when_insufficient_for_stt():
    settings = _settings()
    n, warning = apply_budget(100 * 60, 5, 0.05, settings)
    assert n == 0
    assert warning is not None
