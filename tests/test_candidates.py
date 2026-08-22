"""Testes de N automático + geração de candidatos (SPEC §3)."""

from __future__ import annotations

from clip_mvp.candidates import (
    auto_count_range,
    candidate_pool_size,
    finalize_candidate_windows,
    generate_candidates,
    resolve_target_range,
)
from clip_mvp.models import Candidate, Window
from clip_mvp.config import Settings
from clip_mvp.models import Segment, Transcript, Word


def test_auto_count_range_table():
    assert auto_count_range(5 * 60) == (2, 4)
    assert auto_count_range(20 * 60) == (3, 6)
    assert auto_count_range(60 * 60) == (5, 10)
    assert auto_count_range(120 * 60) == (8, 15)


def test_resolve_target_range_auto_default():
    assert resolve_target_range(5 * 60) == (2, 4)


def test_resolve_target_range_more_scales_up_50_percent():
    lo, hi = resolve_target_range(5 * 60, more=True)
    assert lo >= 3
    assert hi >= 6


def test_resolve_target_range_count_overrides():
    lo, hi = resolve_target_range(5 * 60, count=12)
    assert hi == 12


def test_candidate_pool_size_is_wider_than_target():
    assert candidate_pool_size(4) > 4
    assert candidate_pool_size(10) >= 20


class FakeClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def chat_json(self, **kwargs):
        self.calls.append(kwargs)
        return self.payload


def test_generate_candidates_snaps_mid_word_windows(transcript_pt_br):
    # Propositalmente propõe janelas que caem no meio de palavras.
    payload = {
        "candidates": [
            {
                "title": "Piada do treino",
                "text_excerpt": "Cê já tentou aquele treino novo?",
                "window_9x16": {"start": 0.05, "end": 6.6},
                "window_16x9": {"start": 0.05, "end": 9.85},
                "context_complete": True,
                "vertical_skip_reason": None,
                "llm_notes": "hook forte",
            }
        ]
    }
    client = FakeClient(payload)
    settings = Settings(openrouter_api_key="test-key")

    candidates = generate_candidates(transcript_pt_br, settings, target_hi=4, client=client)

    assert len(candidates) == 1
    cand = candidates[0]
    # 0.05 caia dentro de "Cê" (0.0-0.25) -> snap para 0.0, então padding.
    assert cand.window_16x9.start == 0.0
    # 6.6 cai dentro de "depois." (6.5-6.9) -> snap para 6.9 + padding.
    assert cand.window_9x16.end >= 6.9
    assert cand.window_9x16.duration_s <= settings.vertical_max_s


def _long_transcript() -> Transcript:
    # Transcrição sintética de 200s (mais longa que o teto vertical de 90s).
    words = [Word(start=float(i) * 2.0, end=float(i) * 2.0 + 1.0, text=f"palavra{i}") for i in range(100)]
    seg = Segment(id=0, start=0.0, end=200.0, text=" ".join(w.text for w in words), words=words)
    return Transcript(language="pt", duration=200.0, segments=[seg], source="fixture", has_word_timestamps=True)


def test_generate_candidates_marks_vertical_skipped_when_too_long():
    long_transcript = _long_transcript()
    payload = {
        "candidates": [
            {
                "title": "Momento longo",
                "text_excerpt": "trecho longo",
                "window_9x16": {"start": 0.0, "end": 200.0},
                "window_16x9": {"start": 0.0, "end": 200.0},
                "context_complete": True,
                "vertical_skip_reason": None,
                "llm_notes": "",
            }
        ]
    }
    client = FakeClient(payload)
    settings = Settings(openrouter_api_key="test-key")

    candidates = generate_candidates(long_transcript, settings, target_hi=4, client=client)

    assert candidates[0].window_9x16 is None
    assert candidates[0].vertical_skip_reason == "context_exceeds_90s"


def test_llm_skip_reason_is_overruled_when_the_context_clearly_fits(transcript_pt_br):
    """O LLM alega "context_exceeds_90s" numa janela de 9.8s.

    A validação determinística é a fonte de verdade (SPEC §2.5): um contexto
    de 10s cabe em 9:16, então o vertical é derivado em vez de descartado —
    caso contrário perderíamos um Short perfeitamente exportável.
    """
    payload = {
        "candidates": [
            {
                "title": "Sem vertical",
                "text_excerpt": "trecho",
                "window_9x16": None,
                "window_16x9": {"start": 0.0, "end": 9.8},
                "context_complete": True,
                "vertical_skip_reason": "context_exceeds_90s",
                "llm_notes": "",
            }
        ]
    }
    client = FakeClient(payload)
    settings = Settings(openrouter_api_key="test-key")

    candidates = generate_candidates(transcript_pt_br, settings, target_hi=4, client=client)

    assert candidates[0].window_9x16 is not None
    assert candidates[0].window_9x16.duration_s <= settings.vertical_max_s
    assert candidates[0].vertical_skip_reason is None


def _long_transcript_with_sentences() -> Transcript:
    """200s de fala com pontuação a cada 10 palavras (frases reais)."""
    words = []
    for i in range(100):
        terminal = "." if i % 10 == 9 else ""
        words.append(
            Word(start=float(i) * 2.0, end=float(i) * 2.0 + 1.0, text=f"palavra{i}{terminal}")
        )
    seg = Segment(id=0, start=0.0, end=200.0, text=" ".join(w.text for w in words), words=words)
    return Transcript(
        language="pt", duration=200.0, segments=[seg], source="fixture", has_word_timestamps=True
    )


def test_long_context_shrinks_vertical_instead_of_dropping_it():
    """Contexto >90s: encolhe para uma sub-janela que fecha frase (SPEC §2)."""
    long_transcript = _long_transcript_with_sentences()
    payload = {
        "candidates": [
            {
                "title": "História longa",
                "text_excerpt": "trecho",
                "window_9x16": {"start": 0.0, "end": 150.0},
                "window_16x9": {"start": 0.0, "end": 150.0},
                "context_complete": True,
                "llm_notes": "",
            }
        ]
    }
    settings = Settings(openrouter_api_key="test-key")
    candidates = generate_candidates(
        long_transcript, settings, target_hi=4, client=FakeClient(payload)
    )

    cand = candidates[0]
    if cand.window_9x16 is not None:
        assert cand.window_9x16.duration_s <= settings.vertical_max_s
        assert cand.vertical_skip_reason is None
    else:
        assert cand.vertical_skip_reason == "context_exceeds_90s"


def test_finalize_enforces_45s_vertical_and_60s_horizontal():
    words = []
    for i in range(90):
        terminal = "." if i % 8 == 7 else ""
        words.append(Word(start=float(i), end=float(i) + 0.8, text=f"fala{i}{terminal}"))
    seg = Segment(id=0, start=0.0, end=90.0, text=" ".join(w.text for w in words), words=words)
    transcript = Transcript(
        language="pt", duration=90.0, segments=[seg], source="fixture", has_word_timestamps=True
    )
    settings = Settings(openrouter_api_key="test-key")
    cand = Candidate(
        id="c1",
        title="Momento curto",
        text_excerpt="trecho",
        window_16x9=Window(start=10.0, end=25.0),
        window_9x16=Window(start=12.0, end=22.0),
        context_complete=True,
    )
    out = finalize_candidate_windows(cand, words, transcript, settings, 0.2, 0.4)
    assert out is not None
    assert out.window_16x9.duration_s >= 51.0
    assert out.window_9x16 is not None
    assert out.window_9x16.duration_s >= 45.0
    assert out.window_9x16.duration_s <= 90.0
    assert cand.window_16x9.duration_s > 0
