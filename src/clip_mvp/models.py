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
    """Candidato a corte gerado pela IA (antes de score/dedupe)."""

    id: str
    title: str
    text_excerpt: str
    window_9x16: Optional[Window] = None
    window_16x9: Window
    context_complete: bool = True
    llm_notes: str = ""
    vertical_skip_reason: Optional[str] = None


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
    n_candidates: int
    text_usd: float
    vision_usd: float
    total_usd: float
