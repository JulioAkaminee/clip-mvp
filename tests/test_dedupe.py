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
