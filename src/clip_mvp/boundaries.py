"""Fronteiras de corte no nível da palavra (SPEC 2 e 14.1).

Regras aplicadas aqui, de forma determinística (nunca delegadas ao LLM):

* nunca cortar no meio de palavra;
* start em início de frase, end em fim de frase com pontuação;
* folga de 200–400ms antes do start e depois do end;
* 9:16 nunca passa de 90s — se o contexto fechado não couber, o vertical é
  descartado (jamais truncado no 1:30).
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import PAD_MAX_S, PAD_MIN_S, VERTICAL_MAX_S
from .transcript import Sentence, Transcript

MIN_VERTICAL_S = 8.0
"""Abaixo disso um 9:16 encolhido não vale como corte."""


@dataclass
class Window:
    start: float
    end: float
    context_complete: bool
    method: str = "word"
    """`word` quando houve word timestamps, `segment` no fallback."""
    note: str | None = None

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    def to_dict(self) -> dict:
        return {
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "duration_s": round(self.duration, 3),
            "context_complete": self.context_complete,
            "boundary_method": self.method,
            "note": self.note,
        }


def _pad(value: float) -> float:
    """Folga dentro da faixa da SPEC (200–400ms)."""
    return min(max(value, PAD_MIN_S), PAD_MAX_S)


def snap_window(
    transcript: Transcript,
    start: float,
    end: float,
    pad_s: float = 0.300,
    max_duration: float | None = None,
) -> Window:
    """Ajusta (start, end) para fronteiras de frase + folga.

    `max_duration` limita a expansão para a frente: se a frase que fecha o
    contexto estourar o limite, a janela volta marcada como
    `context_complete=False` para quem chamou decidir (encolher ou descartar).
    """
    sentences = transcript.sentences()
    if not sentences:
        return Window(start=max(0.0, start), end=end, context_complete=False, method="raw")

    method = transcript.boundary_method
    first = _sentence_containing(sentences, start, prefer="start")
    last = _sentence_containing(sentences, end, prefer="end")
    if first > last:
        first, last = last, first

    snapped_start = sentences[first].start
    snapped_end = sentences[last].end
    context_complete = sentences[last].terminated

    # Expande o fim até fechar o contexto (frase com pontuação forte).
    idx = last
    while not sentences[idx].terminated and idx + 1 < len(sentences):
        nxt = sentences[idx + 1]
        if max_duration is not None and (nxt.end - snapped_start) > max_duration:
            break
        idx += 1
        snapped_end = sentences[idx].end
        context_complete = sentences[idx].terminated

    pad = _pad(pad_s)
    padded_start = _pad_start(transcript, snapped_start, pad)
    padded_end = _pad_end(transcript, snapped_end, pad)
    return Window(
        start=padded_start,
        end=padded_end,
        context_complete=context_complete,
        method=method,
    )


def _pad_start(transcript: Transcript, start: float, pad: float) -> float:
    """Recua até `pad`, sem entrar na palavra anterior."""
    prev_end = 0.0
    for unit in transcript.units:
        if unit.end <= start + 1e-6:
            prev_end = max(prev_end, unit.end)
        else:
            break
    floor = max(0.0, prev_end)
    return max(floor, max(0.0, start - pad))


def _pad_end(transcript: Transcript, end: float, pad: float) -> float:
    """Avança até `pad`, sem invadir a palavra seguinte."""
    limit = end + pad
    for unit in transcript.units:
        if unit.start >= end - 1e-6:
            limit = min(limit, unit.start)
            break
    if transcript.duration:
        limit = min(limit, transcript.duration)
    return max(end, limit)


def _sentence_containing(sentences: list[Sentence], t: float, prefer: str) -> int:
    for i, sentence in enumerate(sentences):
        if sentence.start - 1e-6 <= t <= sentence.end + 1e-6:
            return i
        if t < sentence.start:
            # Caiu no silêncio entre frases.
            return i if prefer == "start" else max(0, i - 1)
    return len(sentences) - 1


def fit_vertical(
    transcript: Transcript,
    window: Window,
    max_duration: float = VERTICAL_MAX_S,
    pad_s: float = 0.300,
) -> Window | None:
    """Tenta caber o momento num 9:16 de até 90s **sem** truncar frase.

    Estratégia: manter o fecho (punchline) e recuar o início frase a frase.
    Devolve `None` quando não existe janela válida — nesse caso o job exporta
    só o 16:9 e registra `vertical_skipped="context_exceeds_90s"`.
    """
    if window.duration <= max_duration and window.context_complete:
        return Window(
            start=window.start,
            end=window.end,
            context_complete=window.context_complete,
            method=window.method,
        )

    sentences = transcript.sentences()
    if not sentences:
        return None

    inner = [s for s in sentences if s.start >= window.start - 0.5 and s.end <= window.end + 0.5]
    if not inner:
        return None

    closing = None
    for sentence in reversed(inner):
        if sentence.terminated:
            closing = sentence
            break
    if closing is None:
        return None

    pad = _pad(pad_s)
    end = _pad_end(transcript, closing.end, pad)
    best: Window | None = None
    closing_index = inner.index(closing)
    for i in range(closing_index, -1, -1):
        start = _pad_start(transcript, inner[i].start, pad)
        duration = end - start
        sentence_count = closing_index - i + 1
        if duration > max_duration:
            break
        # Uma punchline solta não é "contexto completo": exigimos setup + fecho
        # (2+ frases) ou uma fala longa o suficiente para se explicar sozinha.
        if duration >= MIN_VERTICAL_S and (sentence_count >= 2 or duration >= 15.0):
            best = Window(
                start=start,
                end=end,
                context_complete=True,
                method=window.method,
                note="shrunk_to_90s",
            )
    if best is None:
        return None
    return best
