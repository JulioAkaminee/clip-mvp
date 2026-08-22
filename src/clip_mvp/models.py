"""Modelos de dados compartilhados pelo pipeline do clip-mvp."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class Word(BaseModel):
    """Palavra com timestamps (word-level), quando o STT expõe."""

    start: float
    end: float
    text: str


class Segment(BaseModel):
    """Segmento de transcrição (frase/trecho), com palavras opcionais."""

    id: int
    start: float
    end: float
    text: str
    words: list[Word] = Field(default_factory=list)
    #: Label de falante, quando o modelo de STT expõe (SPEC §9, §14.6). É daqui
    #: que sai a timeline de diarização — sem uma segunda passada de áudio.
    speaker: Optional[str] = None


class Transcript(BaseModel):
    """Transcrição completa de um job."""

    language: str = "pt"
    duration: float = 0.0
    segments: list[Segment] = Field(default_factory=list)
    source: Literal["openrouter_whisper", "fixture"] = "openrouter_whisper"
    has_word_timestamps: bool = False

    def all_words(self) -> list[Word]:
        words: list[Word] = []
        for seg in self.segments:
            words.extend(seg.words)
        return words


class Window(BaseModel):
    """Janela de tempo (start/end) já com fronteira de palavra + padding aplicados."""

    start: float
    end: float

    @property
    def duration_s(self) -> float:
        return round(self.end - self.start, 3)


class Candidate(BaseModel):
    """Candidato a corte gerado pela IA (antes de score/dedupe).

    ``text_excerpt`` é a transcrição **real** da janela 16:9 depois do snap por
    palavra, não a paráfrase que o modelo de candidatos escreveu: é ela que o
    scorer lê e que a penalidade de truncamento avalia. A versão do modelo fica
    em ``llm_excerpt`` para inspeção.
    """

    id: str
    title: str
    text_excerpt: str
    window_9x16: Optional[Window] = None
    window_16x9: Window
    context_complete: bool = True
    llm_notes: str = ""
    vertical_skip_reason: Optional[str] = None
    #: Excerpt original proposto pelo LLM (antes de ser trocado pela transcrição).
    llm_excerpt: str = ""
    #: Transcrição dos primeiros segundos do corte (SPEC §8: hook).
    hook_text: str = ""
    #: O 9:16 fecha contexto por conta própria (começa em fala e fecha frase)?
    vertical_context_complete: bool = True
    #: O 9:16 teve de encolher para caber no teto de 90s (SPEC §2).
    vertical_shrunk: bool = False


class ScoreBreakdown(BaseModel):
    hook: float = 0
    emocao: float = 0
    citavel: float = 0
    arco: float = 0

    @property
    def total(self) -> float:
        return round(self.hook + self.emocao + self.citavel + self.arco, 2)


class Score(BaseModel):
    total: float
    breakdown: ScoreBreakdown
    reason: str
    context_complete: bool = True


class SpeakerSegment(BaseModel):
    start: float
    end: float
    speaker: str


class DiarizationResult(BaseModel):
    segments: list[SpeakerSegment] = Field(default_factory=list)
    method: Literal["diarization", "activity_proxy", "unavailable"] = "unavailable"


class SelectedClip(BaseModel):
    """Um clip selecionado, pronto para render + meta."""

    slug: str
    candidate: Candidate
    score: Score
    vertical_skipped: Optional[str] = None

    @property
    def vertical_ok(self) -> bool:
        return self.vertical_skipped is None


class CostEstimate(BaseModel):
    stt_minutes: float
    stt_usd: float
    #: Passada dedicada de diarização; 0 quando a timeline sai dos labels que a
    #: transcrição já devolveu (SPEC §9, §14.4).
    diarization_usd: float = 0.0
    n_candidates: int
    text_usd: float
    vision_usd: float
    total_usd: float
