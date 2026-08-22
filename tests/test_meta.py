"""Testes de montagem do meta.json (SPEC §7)."""

from __future__ import annotations

from clip_mvp.meta import build_meta
from clip_mvp.models import Candidate, Score, ScoreBreakdown, Window


def _candidate() -> Candidate:
    return Candidate(
        id="cand_000",
        title="Piada do treino",
        text_excerpt="Cê já tentou aquele treino novo?",
        window_9x16=Window(start=0.0, end=55.6),
        window_16x9=Window(start=0.0, end=104.5),
        context_complete=True,
        llm_notes="hook forte",
    )


def _score() -> Score:
    return Score(
        total=87,
        breakdown=ScoreBreakdown(hook=22, emocao=21, citavel=23, arco=21),
        reason="Pergunta + resposta completa; punchline nos segundos finais",
        context_complete=True,
    )


def test_build_meta_matches_spec_shape():
    candidate = _candidate()
    score = _score()
    meta = build_meta(
        source_url="https://youtube.com/watch?v=abc",
        candidate=candidate,
        score=score,
        window_9x16=candidate.window_9x16,
        window_16x9=candidate.window_16x9,
        vertical_skipped=None,
        selection={"mode": "auto", "candidates": 18, "selected": 7, "min_score": 60},
        social_copy={
            "youtube": {"shorts_title": "Título", "hashtags": ["#Shorts"]},
            "tiktok": {"caption": "Legenda", "hashtags": ["#fyp"]},
        },
        speaker_matching_method="activity_proxy",
    )

    assert meta["source_url"] == "https://youtube.com/watch?v=abc"
    assert meta["windows"]["vertical_9x16"]["duration_s"] == 55.6
    assert meta["windows"]["horizontal_16x9"]["duration_s"] == 104.5
    assert meta["vertical_skipped"] is None
    assert meta["score"] == 87
    assert meta["breakdown"] == {"hook": 22, "emocao": 21, "citavel": 23, "arco": 21}
    assert meta["selection"]["candidates"] == 18
    assert meta["speaker_matching"]["method"] == "activity_proxy"
    assert meta["youtube"]["shorts_title"] == "Título"
    assert meta["tiktok"]["caption"] == "Legenda"


def test_build_meta_vertical_skipped_omits_vertical_window():
    candidate = _candidate()
    candidate.window_9x16 = None
    score = _score()
    meta = build_meta(
        source_url="https://youtube.com/watch?v=abc",
        candidate=candidate,
        score=score,
        window_9x16=None,
        window_16x9=candidate.window_16x9,
        vertical_skipped="context_exceeds_90s",
        selection={"mode": "auto", "candidates": 5, "selected": 2, "min_score": 60},
        social_copy={"youtube": {}, "tiktok": {}},
        speaker_matching_method="activity_proxy",
    )
    assert "vertical_9x16" not in meta["windows"]
    assert meta["vertical_skipped"] == "context_exceeds_90s"
