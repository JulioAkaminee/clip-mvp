"""Testes de fronteira de corte: nunca cortar no meio de palavra (SPEC §2.5, §14.1)."""

from __future__ import annotations

import pytest

from clip_mvp.boundaries import (
    fit_vertical_window,
    crosses_word_midpoint,
    snap_to_segment_boundaries,
    snap_to_word_boundaries,
    snap_window,
)
from clip_mvp.models import Segment, Word

WORDS = [
    Word(start=0.0, end=0.25, text="Cê"),
    Word(start=0.3, end=0.55, text="já"),
    Word(start=0.6, end=1.1, text="tentou"),
    Word(start=1.15, end=1.6, text="aquele"),
    Word(start=1.65, end=2.1, text="treino"),
    Word(start=2.15, end=2.6, text="novo?"),
    Word(start=3.2, end=3.45, text="Sim,"),
    Word(start=3.5, end=3.7, text="mas"),
    Word(start=3.75, end=4.1, text="doeu"),
]


def test_snap_start_inside_word_moves_to_word_start():
    # 0.8 cai dentro de "tentou" (0.6-1.1) -> deve empurrar start para 0.6
    result = snap_to_word_boundaries(
        0.8, 3.9, WORDS, pad_before_s=0.0, pad_after_s=0.0, expand_to_context=False
    )
    assert result.snapped_start is True
    assert result.start == 0.6


def test_snap_end_inside_word_extends_to_word_end():
    # 3.9 cai dentro de "doeu" (3.75-4.1) -> deve estender end para 4.1
    result = snap_to_word_boundaries(
        0.6, 3.9, WORDS, pad_before_s=0.0, pad_after_s=0.0, expand_to_context=False
    )
    assert result.snapped_end is True
    assert result.end == 4.1


def test_snap_exact_word_boundaries_no_snap_needed():
    result = snap_to_word_boundaries(
        0.6, 3.45, WORDS, pad_before_s=0.0, pad_after_s=0.0, expand_to_context=False
    )
    assert result.snapped_start is False
    assert result.snapped_end is False


def test_padding_applied_after_snap_within_200_400ms_range():
    """A folga é limitada ao silêncio disponível.

    Aqui só há 50ms de silêncio antes de "tentou" e depois de "Sim,", então a
    folga encolhe: aplicar os 300ms cheios incluiria as palavras vizinhas
    inteiras ("já" e "mas") no corte.
    """
    result = snap_to_word_boundaries(
        0.6, 3.45, WORDS, pad_before_s=0.3, pad_after_s=0.3, expand_to_context=False
    )
    assert result.start == 0.55
    assert result.end == 3.5
    assert crosses_word_midpoint(result.start, result.end, WORDS) is False
    assert 0.2 <= result.pad_before_s <= 0.4
    assert 0.2 <= result.pad_after_s <= 0.4


def test_full_padding_is_used_when_there_is_room():
    # gap de 0.6s antes de "Sim," (3.2) -> cabe a folga cheia de 0.4s
    result = snap_to_word_boundaries(
        3.2, 3.45, WORDS, pad_before_s=0.4, pad_after_s=0.4, expand_to_context=False
    )
    assert result.start == pytest.approx(2.8, abs=0.01)


def test_padding_never_goes_below_zero():
    result = snap_to_word_boundaries(0.05, 0.2, WORDS, pad_before_s=0.4, pad_after_s=0.4)
    assert result.start == 0.0


def test_padding_never_exceeds_media_duration():
    result = snap_to_word_boundaries(3.75, 4.1, WORDS, pad_before_s=0.4, pad_after_s=0.4, media_duration=4.2)
    assert result.end == 4.2


def test_resulting_window_never_crosses_word_midpoint():
    # Propositalmente cai no meio de duas palavras diferentes.
    result = snap_to_word_boundaries(0.8, 3.9, WORDS, pad_before_s=0.2, pad_after_s=0.2)
    assert crosses_word_midpoint(result.start, result.end, WORDS) is False


def test_crosses_word_midpoint_detects_bad_cut():
    assert crosses_word_midpoint(0.8, 2.0, WORDS) is True
    assert crosses_word_midpoint(0.6, 1.1, WORDS) is False


SEGMENTS = [
    Segment(id=0, start=0.0, end=2.6, text="Cê já tentou aquele treino novo?", words=[]),
    Segment(id=1, start=3.2, end=6.9, text="Sim, mas doeu tanto...", words=[]),
]


def test_segment_fallback_expands_to_segment_boundaries():
    # start cai no meio do segmento 0, end cai no meio do segmento 1.
    result = snap_to_segment_boundaries(1.0, 4.0, SEGMENTS, pad_before_s=0.0, pad_after_s=0.0)
    assert result.start == 0.0
    assert result.end == 6.9


def test_snap_window_prefers_words_over_segments():
    result = snap_window(
        0.8,
        3.9,
        words=WORDS,
        segments=SEGMENTS,
        pad_before_s=0.0,
        pad_after_s=0.0,
        expand_to_context=False,
    )
    assert result.start == 0.6
    assert result.end == 4.1


def test_snap_window_falls_back_to_segments_without_words():
    result = snap_window(1.0, 4.0, words=[], segments=SEGMENTS, pad_before_s=0.0, pad_after_s=0.0)
    assert result.start == 0.0
    assert result.end == 6.9


# --------------------------------------------------------------------------
# Fechamento de contexto (SPEC §2.1-§2.3): o snap por palavra sozinho ainda
# entrega corte que começa/termina no meio da ideia.
# --------------------------------------------------------------------------

CONTEXT_WORDS = [
    Word(start=0.0, end=0.4, text="Todo"),
    Word(start=0.45, end=0.8, text="mundo"),
    Word(start=0.85, end=1.2, text="erra"),
    Word(start=1.25, end=1.7, text="nisso."),
    Word(start=2.2, end=2.5, text="Eu"),
    Word(start=2.55, end=2.9, text="perdi"),
    Word(start=2.95, end=3.4, text="oitenta"),
    Word(start=3.45, end=3.7, text="mil"),
    Word(start=3.75, end=4.3, text="reais."),
    Word(start=4.8, end=5.1, text="Foi"),
    Word(start=5.15, end=5.4, text="feio."),
]


def test_expands_start_to_beginning_of_utterance():
    """Começar em "oitenta" é começar no meio da frase — deve recuar até "Eu"."""
    result = snap_to_word_boundaries(2.95, 4.3, CONTEXT_WORDS, pad_before_s=0.2, pad_after_s=0.4)
    assert result.starts_on_sentence is True
    assert result.start <= 2.2


def test_expands_end_until_sentence_closes():
    """Terminar em "oitenta" corta a ideia — deve seguir até "reais."."""
    result = snap_to_word_boundaries(2.2, 3.4, CONTEXT_WORDS, pad_before_s=0.2, pad_after_s=0.4)
    assert result.ends_on_sentence is True
    assert result.end >= 4.3
    assert result.context_complete is True


def test_expansion_can_be_disabled_for_primitive_snapping():
    result = snap_to_word_boundaries(
        2.95, 3.4, CONTEXT_WORDS, pad_before_s=0.0, pad_after_s=0.0, expand_to_context=False
    )
    assert result.start == 2.95
    assert result.end == 3.4


def test_context_incomplete_when_nothing_closes():
    open_words = [
        Word(start=0.0, end=0.3, text="e"),
        Word(start=0.35, end=0.6, text="aí"),
        Word(start=0.65, end=1.0, text="ele"),
    ]
    result = snap_to_word_boundaries(0.0, 1.0, open_words, pad_before_s=0.2, pad_after_s=0.4)
    assert result.ends_on_sentence is False
    assert result.context_complete is False


def test_padding_never_swallows_neighbour_word():
    """A folga usa o silêncio disponível; nunca puxa a palavra vizinha inteira."""
    # gap entre "nisso." (1.7) e "Eu" (2.2) é 0.5s
    result = snap_to_word_boundaries(
        2.2, 4.3, CONTEXT_WORDS, pad_before_s=0.4, pad_after_s=0.4, expand_to_context=False
    )
    assert result.start >= 1.7, "a folga entrou na palavra anterior"
    assert crosses_word_midpoint(result.start, result.end, CONTEXT_WORDS) is False


def test_pad_is_clamped_to_a_small_gap():
    # gap entre "mil" (3.7) e "reais." (3.75) é 0.05s: a folga não pode passar disso
    result = snap_to_word_boundaries(
        3.75, 4.3, CONTEXT_WORDS, pad_before_s=0.2, pad_after_s=0.4, expand_to_context=False
    )
    assert result.start >= 3.7


# --------------------------------------------------------------------------
# Encaixe do 9:16 em 90s (SPEC §2): encolher antes de descartar
# --------------------------------------------------------------------------


def _long_words(n: int = 120, *, sentence_every: int = 10) -> list[Word]:
    words = []
    t = 0.0
    for i in range(n):
        terminal = "." if i % sentence_every == sentence_every - 1 else ""
        words.append(Word(start=t, end=t + 0.8, text=f"palavra{i}{terminal}"))
        t += 1.0
    return words


def test_window_already_under_90s_passes_through():
    result, skipped = fit_vertical_window(
        2.2, 5.4, CONTEXT_WORDS, max_duration_s=90.0, min_duration_s=2.0
    )
    assert skipped is None
    assert result is not None
    assert result.duration_s <= 90.0


def test_short_vertical_expands_toward_minimum_when_words_allow():
    words = _long_words(80, sentence_every=8)
    result, skipped = fit_vertical_window(
        10.0, 20.0, words, max_duration_s=90.0, min_duration_s=45.0
    )
    assert skipped is None
    assert result is not None
    assert result.duration_s >= 45.0
    assert result.duration_s <= 90.0


def test_long_context_shrinks_to_sentence_aligned_subwindow():
    words = _long_words()
    result, skipped = fit_vertical_window(0.0, 119.8, words, max_duration_s=90.0)
    assert skipped is None, "deveria encolher em vez de descartar"
    assert result is not None
    assert result.duration_s <= 90.0
    assert result.ends_on_sentence is True
    assert result.starts_on_sentence is True, "deve preferir começar em início de fala"


def test_skips_vertical_when_no_closed_context_fits():
    # 100s de fala sem nenhuma pontuação terminal: impossível fechar em 90s
    words = _long_words(100, sentence_every=1000)
    result, skipped = fit_vertical_window(0.0, 99.8, words, max_duration_s=90.0)
    assert result is None
    assert skipped == "context_exceeds_90s"


def test_fitted_window_never_exceeds_the_cap():
    words = _long_words()
    for end in (95.0, 105.0, 119.8):
        result, _ = fit_vertical_window(0.0, end, words, max_duration_s=90.0)
        if result is not None:
            assert result.duration_s <= 90.0
