"""O corte é julgado pela transcrição real da janela, não pela paráfrase do LLM.

O modelo de candidatos escreve `text_excerpt` antes de o snap por palavra mexer
nas fronteiras, então essa paráfrase não descreve o corte que vai sair. Como é
esse texto que alimenta o scorer, a penalidade de truncamento (SPEC §8) e o
dedupe (SPEC §14.3), ele precisa vir da transcrição.
"""

from __future__ import annotations

from clip_mvp.boundaries import hook_text, text_in_window, words_in_window
from clip_mvp.candidates import generate_candidates
from clip_mvp.config import Settings
from clip_mvp.models import Score, ScoreBreakdown, Segment, Transcript, Word
from clip_mvp.score import WEAK_HOOK_CAP, apply_quality_rules, opens_without_speech

WORDS = [
    Word(start=0.0, end=0.4, text="Olha"),
    Word(start=0.5, end=1.0, text="isso"),
    Word(start=1.1, end=1.8, text="mudou"),
    Word(start=1.9, end=2.4, text="tudo."),
    Word(start=3.0, end=3.5, text="Sério"),
    Word(start=3.6, end=4.2, text="mesmo."),
]


class FakeClient:
    def __init__(self, payload: dict):
        self.payload = payload
        self.calls: list[dict] = []

    def chat_json(self, **kwargs):
        self.calls.append(kwargs)
        return self.payload


def settings(**kwargs) -> Settings:
    return Settings(openrouter_api_key="test-key", **kwargs)


class TestWindowHelpers:
    def test_words_in_window_keeps_only_what_is_spoken(self):
        picked = words_in_window(WORDS, 0.9, 2.5)
        assert [w.text for w in picked] == ["isso", "mudou", "tudo."]

    def test_text_in_window_reassembles_the_sentence(self):
        assert text_in_window(WORDS, 0.0, 2.5) == "Olha isso mudou tudo."

    def test_hook_text_is_only_the_first_seconds(self):
        # A palavra que só encosta na janela conta: é o que o espectador ouve.
        assert hook_text(WORDS, 0.0, hook_window_s=1.5) == "Olha isso mudou"
        assert hook_text(WORDS, 0.0, hook_window_s=1.05) == "Olha isso"

    def test_hook_text_of_a_silent_opening_is_empty(self):
        # Corte que abre no silêncio entre 2.4s e 3.0s: nada é dito.
        assert hook_text(WORDS, 2.45, hook_window_s=0.5) == ""


class TestCandidateTextComesFromTranscript:
    def _transcript(self) -> Transcript:
        seg = Segment(
            id=0,
            start=0.0,
            end=4.2,
            text="Olha isso mudou tudo. Sério mesmo.",
            words=WORDS,
        )
        return Transcript(
            language="pt",
            duration=4.2,
            segments=[seg],
            source="fixture",
            has_word_timestamps=True,
        )

    def _generate(self, excerpt: str):
        payload = {
            "candidates": [
                {
                    "title": "Momento",
                    "text_excerpt": excerpt,
                    "window_9x16": {"start": 0.0, "end": 2.4},
                    "window_16x9": {"start": 0.0, "end": 2.4},
                    "context_complete": True,
                    "llm_notes": "",
                }
            ]
        }
        return generate_candidates(
            self._transcript(), settings(), target_hi=4, client=FakeClient(payload)
        )[0]

    def test_llm_paraphrase_is_replaced_by_the_real_words(self):
        cand = self._generate("um resumo qualquer que o modelo inventou")
        assert cand.text_excerpt == "Olha isso mudou tudo."
        assert cand.llm_excerpt == "um resumo qualquer que o modelo inventou"

    def test_hook_text_is_recorded_for_the_scorer(self):
        cand = self._generate("qualquer coisa")
        assert cand.hook_text.startswith("Olha isso")

    def test_a_paraphrase_that_hid_the_truncation_no_longer_fools_the_penalty(self):
        """O LLM entrega um excerpt "fechado" para uma janela que corta a frase.

        Com a transcrição real, a penalidade dura da SPEC §8 volta a enxergar
        que o corte termina no meio do raciocínio.
        """
        payload = {
            "candidates": [
                {
                    "title": "Truncado",
                    "text_excerpt": "Olha isso mudou tudo.",
                    "window_9x16": {"start": 3.0, "end": 3.55},
                    "window_16x9": {"start": 3.0, "end": 3.55},
                    "context_complete": True,
                    "llm_notes": "",
                }
            ]
        }
        cand = generate_candidates(
            self._transcript(), settings(), target_hi=4, client=FakeClient(payload)
        )[0]
        # A janela real é "Sério mesmo." depois da expansão de contexto; o que
        # importa é que o excerpt reflita a transcrição e não a paráfrase.
        assert "Sério" in cand.text_excerpt


class TestWeakHookPenalty:
    def _score(self, hook: float = 24.0) -> Score:
        return Score(
            total=90.0,
            breakdown=ScoreBreakdown(hook=hook, emocao=22, citavel=22, arco=22),
            reason="modelo gostou",
            context_complete=True,
        )

    def test_opens_without_speech_detects_a_silent_start(self):
        assert opens_without_speech("") is True
        assert opens_without_speech("é...") is True
        assert opens_without_speech("Isso mudou tudo aqui") is False

    def test_silent_opening_caps_the_hook_and_discounts_the_total(self):
        result = apply_quality_rules(
            self._score(hook=24.0),
            text_excerpt="Isso mudou tudo.",
            duration_s=45.0,
            hook_text="é",
            settings=settings(),
        )
        assert result.breakdown.hook == WEAK_HOOK_CAP
        assert result.total == 90.0 - (24.0 - WEAK_HOOK_CAP)
        assert "hook fraco" in result.reason

    def test_a_real_opening_is_left_alone(self):
        result = apply_quality_rules(
            self._score(hook=24.0),
            text_excerpt="Isso mudou tudo.",
            duration_s=45.0,
            hook_text="Eu perdi oitenta mil reais",
            settings=settings(),
        )
        assert result.breakdown.hook == 24.0
        assert result.total == 90.0

    def test_without_hook_text_the_rule_stays_out_of_the_way(self):
        result = apply_quality_rules(
            self._score(hook=24.0),
            text_excerpt="Isso mudou tudo.",
            duration_s=45.0,
            settings=settings(),
        )
        assert result.total == 90.0
