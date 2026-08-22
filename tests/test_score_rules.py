"""Penalidades determinísticas aplicadas em cima da nota do modelo (SPEC §8).

O scorer é um LLM e às vezes se apaixona por um momento truncado. Estas regras
são a rede de segurança: valem independentemente do que o modelo respondeu.
"""

from __future__ import annotations

import pytest

from clip_mvp.config import Settings
from clip_mvp.models import Score, ScoreBreakdown
from clip_mvp.score import (
    TRUNCATED_ARCO_CAP,
    apply_quality_rules,
    extract_frames,
    looks_truncated,
)

CLOSED = "Eu perdi oitenta mil reais por vergonha de cobrar o preço certo."
OPEN = "e aí ele falou que a gente precisava"


def make_score(total: float = 90.0, *, context_complete: bool = True, arco: float = 22.0) -> Score:
    return Score(
        total=total,
        breakdown=ScoreBreakdown(hook=23, emocao=22, citavel=23, arco=arco),
        reason="avaliação do modelo",
        context_complete=context_complete,
    )


def settings(**kwargs) -> Settings:
    return Settings(openrouter_api_key="test-key", **kwargs)


class TestTruncationPenalty:
    def test_model_saying_open_context_caps_the_score(self):
        result = apply_quality_rules(
            make_score(92, context_complete=False),
            text_excerpt=CLOSED,
            duration_s=45.0,
            settings=settings(),
        )
        assert result.total <= 45.0
        assert result.context_complete is False

    def test_text_without_terminal_punctuation_is_treated_as_open(self):
        """Mesmo com o modelo dizendo que fechou, o texto denuncia o corte."""
        result = apply_quality_rules(
            make_score(88, context_complete=True),
            text_excerpt=OPEN,
            duration_s=45.0,
            settings=settings(),
        )
        assert result.total <= 45.0
        assert result.context_complete is False

    def test_boundary_validation_can_veto_the_model(self):
        result = apply_quality_rules(
            make_score(95, context_complete=True),
            text_excerpt=CLOSED,
            duration_s=45.0,
            boundary_context_complete=False,
            settings=settings(),
        )
        assert result.total <= 45.0

    def test_arco_is_capped_when_context_is_open(self):
        result = apply_quality_rules(
            make_score(92, context_complete=False, arco=25),
            text_excerpt=OPEN,
            duration_s=45.0,
            settings=settings(),
        )
        assert result.breakdown.arco <= TRUNCATED_ARCO_CAP

    def test_closed_context_is_left_alone(self):
        result = apply_quality_rules(
            make_score(88), text_excerpt=CLOSED, duration_s=45.0, settings=settings()
        )
        assert result.total == 88
        assert result.breakdown.arco == 22
        assert result.context_complete is True

    def test_truncated_never_outranks_a_complete_clip(self):
        truncated = apply_quality_rules(
            make_score(99, context_complete=False),
            text_excerpt=OPEN,
            duration_s=45.0,
            settings=settings(),
        )
        complete = apply_quality_rules(
            make_score(70), text_excerpt=CLOSED, duration_s=45.0, settings=settings()
        )
        assert truncated.total < complete.total

    def test_penalty_is_explained_in_the_reason(self):
        result = apply_quality_rules(
            make_score(92, context_complete=False),
            text_excerpt=OPEN,
            duration_s=45.0,
            settings=settings(),
        )
        assert "contexto não fecha" in result.reason


class TestShortClipRule:
    def test_very_short_clip_is_capped(self):
        result = apply_quality_rules(
            make_score(95), text_excerpt=CLOSED, duration_s=8.0, settings=settings()
        )
        assert result.total <= 70.0
        assert "curto demais" in result.reason

    def test_normal_duration_is_untouched(self):
        result = apply_quality_rules(
            make_score(95), text_excerpt=CLOSED, duration_s=45.0, settings=settings()
        )
        assert result.total == 95

    def test_rule_can_be_disabled(self):
        result = apply_quality_rules(
            make_score(95),
            text_excerpt=CLOSED,
            duration_s=8.0,
            settings=settings(min_duration_full_arc_s=0.0),
        )
        assert result.total == 95

    def test_thresholds_are_configurable(self):
        result = apply_quality_rules(
            make_score(95),
            text_excerpt=CLOSED,
            duration_s=25.0,
            settings=settings(min_duration_full_arc_s=30.0, short_clip_score_cap=50.0),
        )
        assert result.total == 50.0


class TestBounds:
    @pytest.mark.parametrize("total", [0, 50, 100])
    def test_score_stays_in_range(self, total):
        result = apply_quality_rules(
            make_score(total), text_excerpt=CLOSED, duration_s=45.0, settings=settings()
        )
        assert 0 <= result.total <= 100

    def test_empty_text_is_not_treated_as_truncated(self):
        """Sem excerpt não há evidência de truncamento; não inventar penalidade."""
        assert looks_truncated("") is False
        result = apply_quality_rules(
            make_score(88), text_excerpt="", duration_s=45.0, settings=settings()
        )
        assert result.total == 88

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("Isso mudou tudo.", False),
            ("Será que funciona?", False),
            ("Não acredito!", False),
            ("e aí ele falou que", True),
            ("porque isso é", True),
        ],
    )
    def test_looks_truncated(self, text, expected):
        assert looks_truncated(text) is expected


class TestFrameExtraction:
    def test_frames_are_cached_between_runs(self, tmp_path, sample_video_path):
        """O resume não pode pagar de novo pela extração (SPEC §14.4)."""
        out = tmp_path / "frames"
        first = extract_frames(sample_video_path, 0.0, 5.0, out, n=3)
        assert len(first) == 3
        stamps = [p.stat().st_mtime_ns for p in first]

        second = extract_frames(sample_video_path, 0.0, 5.0, out, n=3)
        assert [p.stat().st_mtime_ns for p in second] == stamps

    def test_frames_are_downscaled_for_the_vision_call(self, tmp_path, sample_video_path):
        paths = extract_frames(sample_video_path, 0.0, 5.0, tmp_path / "f", n=1, width=256)
        assert paths[0].exists()
        # payload pequeno: o scorer só precisa enxergar enquadramento e reação
        assert paths[0].stat().st_size < 120_000
