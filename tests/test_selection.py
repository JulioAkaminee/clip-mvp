"""Seleção final: limiar absoluto + piso relativo + teto da faixa (SPEC §3).

O limiar absoluto responde "isso é publicável?". Ele não responde "isso presta
ao lado do resto deste vídeo?": num podcast com um momento de 92, entregar
também um de 61 só porque passou dos 60 dilui o lote — que é justamente o corte
mediano que a SPEC §3.5 pede para não entregar.
"""

from __future__ import annotations

from clip_mvp.models import Candidate, Score, ScoreBreakdown, Window
from clip_mvp.pipeline import _select_clips


#: Assuntos sem vocabulário em comum: o dedupe não deve entrar nestes testes.
_TOPICS = [
    "precificacao de servicos criativos para clientes grandes",
    "receita caseira de bolo de cenoura com cobertura",
    "mercado de criptomoedas quebrando pela terceira vez",
    "treinamento de forca para corredores amadores lesionados",
    "documentario sobre naufragios no litoral catarinense",
    "programacao funcional aplicada a bancos de dados",
]


def _pair(idx: int, total: float, *, start: float | None = None):
    """Candidato isolado no tempo e no vocabulário, para o dedupe não interferir."""
    start = start if start is not None else idx * 600.0
    return (
        Candidate(
            id=f"cand_{idx:03d}",
            title=f"Momento {idx}",
            text_excerpt=_TOPICS[idx % len(_TOPICS)],
            window_16x9=Window(start=start, end=start + 60.0),
            window_9x16=Window(start=start, end=start + 40.0),
            context_complete=True,
        ),
        Score(
            total=total,
            breakdown=ScoreBreakdown(hook=20, emocao=20, citavel=20, arco=20),
            reason="ok",
            context_complete=True,
        ),
    )


def _select(scores: list[float], **kwargs):
    scored = [_pair(i, total) for i, total in enumerate(scores)]
    defaults = dict(min_score=60.0, max_score_only=None, count_cap=10, keep_at_least=1)
    defaults.update(kwargs)
    return _select_clips(scored, **defaults)


class TestAbsoluteThreshold:
    def test_below_the_threshold_is_dropped(self):
        outcome = _select([90.0, 55.0], relative_gap=None)
        assert [round(s.total) for _, s in outcome.selected] == [90]

    def test_max_score_only_overrides_the_threshold(self):
        outcome = _select([90.0, 75.0], max_score_only=80.0, relative_gap=None)
        assert [round(s.total) for _, s in outcome.selected] == [90]

    def test_count_cap_limits_the_batch(self):
        outcome = _select([95.0, 92.0, 90.0, 88.0], count_cap=2, relative_gap=None)
        assert len(outcome.selected) == 2


class TestRelativeFloor:
    def test_a_clip_far_below_the_best_is_dropped(self):
        outcome = _select([92.0, 88.0, 61.0], relative_gap=22.0, keep_at_least=1)
        assert [round(s.total) for _, s in outcome.selected] == [92, 88]
        assert outcome.below_floor_removed == 1
        assert outcome.quality_floor == 70.0

    def test_a_tight_batch_is_left_alone(self):
        outcome = _select([92.0, 88.0, 84.0], relative_gap=22.0)
        assert len(outcome.selected) == 3
        assert outcome.below_floor_removed == 0
        # o piso vigente é reportado mesmo quando não corta ninguém
        assert outcome.quality_floor == 70.0

    def test_the_floor_never_pushes_below_the_target_range_minimum(self):
        """SPEC §3 dá um piso de quantidade por duração; o piso relativo o respeita."""
        outcome = _select([92.0, 64.0, 62.0], relative_gap=22.0, keep_at_least=3)
        assert len(outcome.selected) == 3
        assert outcome.below_floor_removed == 0

    def test_a_weak_but_uniform_batch_survives(self):
        """Sem um destaque, o piso relativo cai abaixo do limiar e não morde."""
        outcome = _select([66.0, 64.0, 62.0], relative_gap=22.0)
        assert len(outcome.selected) == 3

    def test_disabling_the_gap_keeps_everything_above_the_threshold(self):
        outcome = _select([92.0, 61.0], relative_gap=None)
        assert len(outcome.selected) == 2

    def test_a_zero_gap_is_the_same_as_disabled(self):
        outcome = _select([92.0, 61.0], relative_gap=0.0)
        assert len(outcome.selected) == 2

    def test_a_single_survivor_is_never_thrown_away(self):
        outcome = _select([92.0], relative_gap=22.0)
        assert len(outcome.selected) == 1
        assert outcome.below_floor_removed == 0
