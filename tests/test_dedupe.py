"""Testes de deduplicação por overlap temporal / punchline repetida (SPEC §3, §14.3)."""

from __future__ import annotations

from clip_mvp.dedupe import DedupeItem, dedupe_items, temporal_overlap_ratio, text_similarity


def test_temporal_overlap_ratio_full_containment_is_1():
    # B (10-20) está totalmente contido em A (0-30): overlap relativo a B = 1.0
    assert temporal_overlap_ratio(0, 30, 10, 20) == 1.0


def test_temporal_overlap_ratio_no_overlap_is_0():
    assert temporal_overlap_ratio(0, 10, 20, 30) == 0.0


def test_temporal_overlap_ratio_partial():
    # A: 0-10, B: 5-15 -> intersecao 5-10 (5s), menor janela = 10s -> 0.5
    assert temporal_overlap_ratio(0, 10, 5, 15) == 0.5


def test_text_similarity_identical_is_1():
    assert text_similarity("mesma piada aqui", "mesma piada aqui") == 1.0


def test_text_similarity_different_is_low():
    assert text_similarity("um assunto totalmente diferente", "outra coisa qualquer sem relacao") < 0.5


def test_dedupe_removes_overlapping_keeps_higher_score():
    items = [
        DedupeItem(item="A", start=0, end=20, text="piada do carro", score=70),
        DedupeItem(item="B", start=5, end=15, text="piada completamente diferente sobre outra coisa", score=90),
    ]
    result = dedupe_items(items)
    assert result.kept == ["B"]
    assert result.removed_count == 1


def test_dedupe_removes_similar_text_keeps_higher_score():
    items = [
        DedupeItem(item="low", start=0, end=10, text="ele contou a piada do carro quebrado", score=55),
        DedupeItem(item="high", start=200, end=210, text="ele contou a piada do carro quebrado", score=88),
    ]
    result = dedupe_items(items)
    assert result.kept == ["high"]
    assert result.removed_count == 1


def test_dedupe_keeps_distinct_candidates():
    items = [
        DedupeItem(item="A", start=0, end=10, text="assunto A totalmente distinto", score=60),
        DedupeItem(item="B", start=100, end=110, text="assunto B nada a ver com o outro", score=65),
        DedupeItem(item="C", start=300, end=310, text="assunto C tambem diferente de tudo", score=70),
    ]
    result = dedupe_items(items)
    assert set(result.kept) == {"A", "B", "C"}
    assert result.removed_count == 0


def test_short_texts_are_not_treated_as_the_same_moment():
    """Dois trechos curtos batem quase 100% por acaso — não são duplicata."""
    items = [
        DedupeItem(item="a", start=0.0, end=30.0, text="Isso mudou tudo.", score=90.0),
        DedupeItem(item="b", start=600.0, end=630.0, text="Isso mudou tudo.", score=80.0),
    ]
    result = dedupe_items(items)
    assert result.kept == ["a", "b"]
    assert result.removed_count == 0


def test_long_near_identical_texts_are_still_deduped():
    text = (
        "eu perdi oitenta mil reais no primeiro ano por vergonha de cobrar o preço "
        "certo, porque eu olhava pro cliente e falava um número trinta por cento "
        "menor do que tinha calculado em casa antes da reunião"
    )
    items = [
        DedupeItem(item="a", start=0.0, end=60.0, text=text, score=90.0),
        DedupeItem(item="b", start=600.0, end=660.0, text=text, score=70.0),
    ]
    result = dedupe_items(items)
    assert result.kept == ["a"]
    assert result.removed_count == 1


def test_text_similarity_respects_min_words():
    assert text_similarity("mudou tudo", "mudou tudo", min_words=6) == 0.0
    assert text_similarity("mudou tudo", "mudou tudo") > 0.9
