"""Testes de SRT/ASS + safe area (SPEC §10, §14.5)."""

from __future__ import annotations

from clip_mvp.models import Word
from clip_mvp.subtitles import (
    build_ass,
    build_cues_from_words,
    cues_to_srt,
)


def test_build_cues_from_words_relative_to_window_start(transcript_pt_br):
    words = transcript_pt_br.all_words()
    cues = build_cues_from_words(words, window_start=3.2, window_end=6.9)
    assert cues[0].start == 0.0  # "Sim," começa exatamente em 3.2 -> relativo = 0
    assert all(c.start >= 0 for c in cues)
    assert cues[-1].end <= 6.9 - 3.2 + 0.01


def test_build_cues_from_words_respects_max_chars_and_splits_on_sentence_end():
    words = [Word(start=i * 0.3, end=i * 0.3 + 0.25, text=w) for i, w in enumerate(["Uma", "frase", "curta."])]
    words += [Word(start=(i + 3) * 0.3, end=(i + 3) * 0.3 + 0.25, text=w) for i, w in enumerate(["Outra", "frase."])]
    cues = build_cues_from_words(words, 0.0, 2.0)
    # Deve quebrar em pelo menos 2 cues por causa do fim de frase ("curta.")
    assert len(cues) >= 2


def test_cues_to_srt_format():
    cues = build_cues_from_words(
        [Word(start=0.0, end=0.5, text="Oi"), Word(start=0.6, end=1.2, text="mundo")], 0.0, 2.0
    )
    srt = cues_to_srt(cues)
    assert "-->" in srt
    assert "," in srt.splitlines()[1]  # timestamp usa vírgula (SRT), não ponto


def test_vertical_safe_area_avoids_bottom_20_percent():
    cues = build_cues_from_words([Word(start=0.0, end=0.5, text="Oi")], 0.0, 1.0)
    ass_vertical = build_ass(cues, video_width=1080, video_height=1920, is_vertical=True)
    ass_horizontal = build_ass(cues, video_width=1920, video_height=1080, is_vertical=False)

    def margin_v(ass_text: str) -> int:
        style_line = next(line for line in ass_text.splitlines() if line.startswith("Style:"))
        return int(style_line.split(",")[-2])

    vertical_margin = margin_v(ass_vertical)
    horizontal_margin = margin_v(ass_horizontal)

    # Vertical deve reservar proporcionalmente muito mais espaço inferior
    # (safe area ~20% da altura) do que o horizontal (terço inferior clássico).
    assert vertical_margin / 1920 >= 0.18
    assert horizontal_margin / 1080 < vertical_margin / 1920


def test_srt_never_splits_a_single_word_across_two_cues(transcript_pt_br):
    words = transcript_pt_br.all_words()
    cues = build_cues_from_words(words, 0.0, transcript_pt_br.duration)
    all_cue_text = " ".join(c.text for c in cues)
    for w in words:
        assert w.text in all_cue_text
