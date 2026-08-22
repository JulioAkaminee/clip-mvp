"""Quantidade dinâmica de cortes, dedupe e orçamento (SPEC 3, 14.3, 14.4)."""

from clip_mvp.boundaries import Window
from clip_mvp.budget import estimate, fit_candidates_to_budget
from clip_mvp.candidates import plan_count
from clip_mvp.config import target_range
from clip_mvp.dedupe import dedupe, overlap_ratio
from clip_mvp.models import Candidate


def _unique_text(idx: int) -> str:
    """Texto longo e sem vocabulário em comum entre candidatos."""
    return " ".join(f"assunto{idx}termo{i}" for i in range(30))


def _candidate(idx: int, start: float, end: float, score: int, text: str = "") -> Candidate:
    return Candidate(
        id=f"c{idx}",
        title=f"corte {idx}",
        reason="",
        horizontal=Window(start=start, end=end, context_complete=True),
        vertical=Window(start=start, end=min(end, start + 60), context_complete=True),
        transcript_text=text or _unique_text(idx),
        score=score,
    )


def test_faixa_alvo_varia_com_a_duracao():
    assert target_range(5 * 60) == (2, 4)
    assert target_range(20 * 60) == (3, 6)
    assert target_range(60 * 60) == (5, 10)
    assert target_range(120 * 60) == (8, 15)


def test_n_de_cortes_nao_e_fixo():
    curto = plan_count(8 * 60)
    longo = plan_count(120 * 60)
    assert (curto.target_min, curto.target_max) != (longo.target_min, longo.target_max)
    assert curto.pool >= 6 and longo.pool > curto.pool


def test_more_pede_cerca_de_50_por_cento_mais():
    auto = plan_count(45 * 60, "auto")
    more = plan_count(45 * 60, "more")
    assert more.target_max >= auto.target_max * 1.4


def test_count_forca_o_teto():
    plan = plan_count(45 * 60, "count", 12)
    assert plan.target_max == 12
    assert plan.pool >= 12


def test_dedupe_por_overlap_mantem_maior_score():
    kept, removed = dedupe(
        [
            _candidate(1, 100, 200, 70),
            _candidate(2, 120, 210, 85),  # overlap > 50%
            _candidate(3, 600, 700, 66),
        ]
    )
    assert len(kept) == 2
    assert {c.id for c in kept} == {"c2", "c3"}
    assert removed[0][0].id == "c1"
    assert removed[0][0].dedupe_of == "c2"


def test_dedupe_por_punchline_repetida():
    punchline = "e ele riu, mandou o contrato no mesmo dia e virou meu socio dois anos depois"
    kept, removed = dedupe(
        [
            _candidate(1, 10, 60, 71, "primeiro setup da historia contada de um jeito. " + punchline),
            _candidate(
                2,
                900,
                950,
                64,
                "outro setup completamente diferente e mais longo, contado de outra forma, "
                "com outras palavras no comeco do trecho. " + punchline,
            ),
        ]
    )
    assert len(kept) == 1
    assert kept[0].id == "c1"
    assert removed and removed[0][1] in {"texto_similar", "mesma_punchline"}


def test_overlap_ratio():
    assert overlap_ratio(0, 100, 50, 150) == 0.5
    assert overlap_ratio(0, 100, 200, 300) == 0.0
    assert overlap_ratio(0, 100, 10, 30) == 1.0


def test_estimativa_cresce_com_duracao_e_candidatos():
    curta = estimate(600, 10, 4)
    longa = estimate(3600, 25, 10)
    assert longa.total_usd > curta.total_usd
    assert {line.step for line in curta.lines} == {
        "stt",
        "candidatos",
        "score (vision)",
        "meta (títulos/hashtags)",
    }


def test_budget_reduz_candidatos_antes_de_abortar():
    allowed, est = fit_candidates_to_budget(3600, 30, 10, budget_usd=0.30)
    assert allowed <= 30
    if est.within_budget:
        assert allowed < 30
        assert est.total_usd <= 0.30
    else:
        assert "acima do orçamento" in est.note


def test_budget_impossivel_e_sinalizado():
    _, est = fit_candidates_to_budget(7200, 40, 15, budget_usd=0.001)
    assert not est.within_budget
    assert est.note
