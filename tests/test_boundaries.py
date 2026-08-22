"""Testes de fronteira de corte: nunca cortar no meio de palavra (SPEC §2.5, §14.1)."""

from __future__ import annotations

from clip_mvp.boundaries import (
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
    result = snap_to_word_boundaries(0.8, 3.9, WORDS, pad_before_s=0.0, pad_after_s=0.0)
    assert result.snapped_start is True
    assert result.start == 0.6


def test_snap_end_inside_word_extends_to_word_end():
    # 3.9 cai dentro de "doeu" (3.75-4.1) -> deve estender end para 4.1
    result = snap_to_word_boundaries(0.6, 3.9, WORDS, pad_before_s=0.0, pad_after_s=0.0)
    assert result.snapped_end is True
    assert result.end == 4.1


def test_snap_exact_word_boundaries_no_snap_needed():
    result = snap_to_word_boundaries(0.6, 3.45, WORDS, pad_before_s=0.0, pad_after_s=0.0)
    assert result.snapped_start is False
    assert result.snapped_end is False


def test_padding_applied_after_snap_within_200_400ms_range():
    result = snap_to_word_boundaries(0.6, 3.45, WORDS, pad_before_s=0.3, pad_after_s=0.3)
    assert result.start == 0.3
    assert result.end == 3.75
    assert 0.2 <= result.pad_before_s <= 0.4
    assert 0.2 <= result.pad_after_s <= 0.4


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
    result = snap_window(0.8, 3.9, words=WORDS, segments=SEGMENTS, pad_before_s=0.0, pad_after_s=0.0)
    assert result.start == 0.6
    assert result.end == 4.1


def test_snap_window_falls_back_to_segments_without_words():
    result = snap_window(1.0, 4.0, words=[], segments=SEGMENTS, pad_before_s=0.0, pad_after_s=0.0)
    assert result.start == 0.0
    assert result.end == 6.9
