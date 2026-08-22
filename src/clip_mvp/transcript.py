"""Estruturas da transcrição (palavras, segmentos, frases)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

SENTENCE_END = re.compile(r"[.!?…]+[\"'”’)\]]*\s*$")


@dataclass
class Word:
    start: float
    end: float
    text: str

    def to_dict(self) -> dict:
        return {"start": self.start, "end": self.end, "text": self.text}


@dataclass
class Segment:
    start: float
    end: float
    text: str
    speaker: str | None = None
    words: list[Word] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "start": self.start,
            "end": self.end,
            "text": self.text,
            "speaker": self.speaker,
            "words": [w.to_dict() for w in self.words],
        }


@dataclass
class Sentence:
    start: float
    end: float
    text: str
    terminated: bool
    """True quando a frase termina em pontuação forte (contexto fechado)."""


@dataclass
class Transcript:
    duration: float
    segments: list[Segment] = field(default_factory=list)
    language: str = "pt"
    stt_model: str = ""
    diarization: bool = False

    # --- índices derivados ---------------------------------------------------
    @property
    def words(self) -> list[Word]:
        out: list[Word] = []
        for seg in self.segments:
            out.extend(seg.words)
        return out

    @property
    def has_word_timestamps(self) -> bool:
        return any(seg.words for seg in self.segments)

    @property
    def units(self) -> list[Word]:
        """Menor unidade confiável: palavra quando existe, senão o segmento."""
        if self.has_word_timestamps:
            return self.words
        return [Word(s.start, s.end, s.text.strip()) for s in self.segments]

    @property
    def boundary_method(self) -> str:
        return "word" if self.has_word_timestamps else "segment"

    def sentences(self) -> list[Sentence]:
        """Agrupa unidades em frases usando pontuação forte."""
        units = self.units
        sentences: list[Sentence] = []
        buf: list[Word] = []
        for unit in units:
            buf.append(unit)
            if SENTENCE_END.search(unit.text):
                sentences.append(_sentence_from(buf, terminated=True))
                buf = []
        if buf:
            sentences.append(_sentence_from(buf, terminated=False))
        return sentences

    def text_between(self, start: float, end: float) -> str:
        parts = [
            u.text
            for u in self.units
            if u.end > start + 1e-6 and u.start < end - 1e-6
        ]
        return " ".join(p.strip() for p in parts if p.strip()).strip()

    def to_dict(self) -> dict:
        return {
            "duration": self.duration,
            "language": self.language,
            "stt_model": self.stt_model,
            "diarization": self.diarization,
            "has_word_timestamps": self.has_word_timestamps,
            "segments": [s.to_dict() for s in self.segments],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Transcript":
        segments = [
            Segment(
                start=float(s["start"]),
                end=float(s["end"]),
                text=s.get("text", ""),
                speaker=s.get("speaker"),
                words=[
                    Word(float(w["start"]), float(w["end"]), w.get("text", ""))
                    for w in s.get("words", [])
                ],
            )
            for s in data.get("segments", [])
        ]
        return cls(
            duration=float(data.get("duration") or 0.0),
            segments=segments,
            language=data.get("language", "pt"),
            stt_model=data.get("stt_model", ""),
            diarization=bool(data.get("diarization")),
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )

    @classmethod
    def load(cls, path: Path) -> "Transcript":
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _sentence_from(units: list[Word], terminated: bool) -> Sentence:
    text = " ".join(u.text.strip() for u in units if u.text.strip()).strip()
    return Sentence(start=units[0].start, end=units[-1].end, text=text, terminated=terminated)


def transcript_as_prompt_lines(transcript: Transcript, max_chars: int = 60_000) -> str:
    """Transcrição com timestamps, pronta para o prompt do LLM."""
    lines: list[str] = []
    total = 0
    for seg in transcript.segments:
        speaker = f" {seg.speaker}:" if seg.speaker else ""
        line = f"[{seg.start:.1f}-{seg.end:.1f}]{speaker} {seg.text.strip()}"
        total += len(line) + 1
        if total > max_chars:
            lines.append("[...transcrição truncada...]")
            break
        lines.append(line)
    return "\n".join(lines)
