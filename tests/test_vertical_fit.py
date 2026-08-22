"""Encolher o 9:16 antes de descartar, mas sem entregar fragmento (SPEC §2).

A spec dá duas saídas quando o contexto fechado passa de 90s: encolher para uma
janela menor que **ainda tenha contexto completo**, ou exportar só o 16:9. Um
recorte de poucos segundos não é a primeira saída — é um Short que começa do
nada — então nesse caso o certo é a segunda.
"""

from __future__ import annotations

from clip_mvp.boundaries import (
    MIN_SHRUNK_VERTICAL_S,
    VERTICAL_TOO_SHORT,
    fit_vertical_window,
)
from clip_mvp.candidates import generate_candidates
from clip_mvp.config import Settings
from clip_mvp.meta import build_meta
from clip_mvp.models import Score, ScoreBreakdown, Segment, Transcript, Word


class FakeClient:
    def __init__(self, payload: dict):
        self.payload = payload

    def chat_json(self, **kwargs):
        return self.payload


def settings(**kwargs) -> Settings:
    return Settings(openrouter_api_key="test-key", **kwargs)


def _words(specs: list[tuple[float, float, str]]) -> list[Word]:
    return [Word(start=s, end=e, text=t) for s, e, t in specs]


class TestShrinkFloor:
    def _long_words_with_late_sentence(self) -> list[Word]:
        """120s de fala em que a única fronteira de frase útil está no fim.

        Frase 1 fecha em 5s; depois vem um bloco corrido de 100s sem pontuação
        nem pausa, e a frase final fecha em 118s. A única sub-janela que fecha
        frase e cabe em 90s é o fiapo final.
        """
        words = [
            Word(start=0.0, end=1.0, text="Começa"),
            Word(start=1.2, end=5.0, text="assim."),
        ]
        t = 5.2
        while t < 112.0:
            words.append(Word(start=t, end=t + 0.3, text="corrido"))
            t += 0.35
        words.append(Word(start=112.2, end=118.0, text="final."))
        return words

    def test_a_few_second_fragment_is_rejected_in_favour_of_16x9_only(self):
        words = self._long_words_with_late_sentence()
        fitted, reason = fit_vertical_window(0.0, 118.5, words, max_duration_s=90.0)
        assert fitted is None
        assert reason == "context_exceeds_90s"

    def test_lowering_the_floor_accepts_the_same_fragment(self):
        """O piso é uma decisão de produto, não uma regra física: é ajustável."""
        words = self._long_words_with_late_sentence()
        fitted, reason = fit_vertical_window(
            0.0, 118.5, words, max_duration_s=90.0, min_duration_s=1.0
        )
        assert reason is None
        assert fitted is not None
        assert fitted.duration_s <= 90.0

    def test_a_real_sub_window_still_shrinks_instead_of_being_dropped(self):
        """Contexto de 150s com frases a cada 20s: encolher é a saída certa."""
        words = []
        for i in range(30):
            terminal = "." if i % 4 == 3 else ""
            words.append(Word(start=i * 5.0, end=i * 5.0 + 2.0, text=f"palavra{i}{terminal}"))
        fitted, reason = fit_vertical_window(0.0, 150.0, words, max_duration_s=90.0)
        assert reason is None
        assert fitted is not None
        assert MIN_SHRUNK_VERTICAL_S <= fitted.duration_s <= 90.0
        assert fitted.ends_on_sentence is True

    def test_a_window_below_the_floor_is_refused_as_too_short(self):
        """Trecho curto demais não vira Short — e o motivo diz isso, não 'passou de 90s'."""
        words = _words([(0.0, 1.0, "Curto"), (1.1, 2.0, "assim.")])
        fitted, reason = fit_vertical_window(0.0, 2.0, words, max_duration_s=90.0)
        assert fitted is None
        assert reason == VERTICAL_TOO_SHORT

    def test_a_window_that_already_fits_is_kept(self):
        """Dentro da faixa (piso ≤ duração ≤ teto) a janela passa intacta."""
        words = _words([(0.0, 1.0, "Curto"), (1.1, 2.0, "assim.")])
        fitted, reason = fit_vertical_window(
            0.0, 2.0, words, max_duration_s=90.0, min_duration_s=1.0
        )
        assert reason is None
        assert fitted is not None


class TestVerticalHonesty:
    def _transcript(self) -> Transcript:
        words = []
        for i in range(30):
            terminal = "." if i % 4 == 3 else ""
            words.append(Word(start=i * 5.0, end=i * 5.0 + 2.0, text=f"palavra{i}{terminal}"))
        seg = Segment(
            id=0, start=0.0, end=150.0, text=" ".join(w.text for w in words), words=words
        )
        return Transcript(
            language="pt",
            duration=150.0,
            segments=[seg],
            source="fixture",
            has_word_timestamps=True,
        )

    def _candidate(self):
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
        return generate_candidates(
            self._transcript(), settings(), target_hi=4, client=FakeClient(payload)
        )[0]

    def test_a_shrunk_vertical_is_flagged_as_such(self):
        cand = self._candidate()
        assert cand.window_9x16 is not None
        assert cand.vertical_shrunk is True
        assert cand.vertical_context_complete is True

    def test_meta_json_records_the_vertical_context(self):
        cand = self._candidate()
        meta = build_meta(
            source_url="https://example.com/v",
            candidate=cand,
            score=Score(
                total=80.0,
                breakdown=ScoreBreakdown(hook=20, emocao=20, citavel=20, arco=20),
                reason="ok",
            ),
            window_9x16=cand.window_9x16,
            window_16x9=cand.window_16x9,
            vertical_skipped=None,
            selection={"mode": "auto"},
            social_copy={},
            speaker_matching_method="activity_proxy",
        )
        vertical = meta["windows"]["vertical_9x16"]
        assert vertical["context_complete"] is True
        assert vertical["shrunk_from_16x9"] is True

    def test_a_vertical_equal_to_the_16x9_is_not_marked_as_shrunk(self):
        words = _words([(0.0, 1.0, "Curto"), (1.1, 2.0, "assim.")])
        seg = Segment(id=0, start=0.0, end=2.0, text="Curto assim.", words=words)
        transcript = Transcript(
            language="pt",
            duration=2.0,
            segments=[seg],
            source="fixture",
            has_word_timestamps=True,
        )
        payload = {
            "candidates": [
                {
                    "title": "Curto",
                    "text_excerpt": "Curto assim.",
                    "window_9x16": {"start": 0.0, "end": 2.0},
                    "window_16x9": {"start": 0.0, "end": 2.0},
                    "context_complete": True,
                    "llm_notes": "",
                }
            ]
        }
        cand = generate_candidates(
            transcript, settings(), target_hi=4, client=FakeClient(payload)
        )[0]
        assert cand.vertical_shrunk is False
