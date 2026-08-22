"""Lógica determinística de fronteira de corte (SPEC §2.5 / §14.1).

Regra dura do produto: a IA nunca deve cortar no meio de uma palavra. Este
módulo é puro (sem I/O) para ser fácil de testar: dado uma janela proposta
(possivelmente "no meio" de uma palavra) e a lista de palavras/segmentos da
transcrição, produz uma janela ajustada que:

1. Nunca corta uma palavra pela metade (sempre inclui a palavra inteira caso
   o corte proposto caia dentro dela).
2. Aplica folga (padding) de 200-400ms antes do início e depois do fim.
3. Se só houver timestamps de segmento (sem palavra), expande até o fim do
   segmento (que normalmente termina em pontuação).
4. Nunca deixa o resultado sair do intervalo válido de mídia [0, duration].
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import Segment, Word


@dataclass(frozen=True)
class BoundaryResult:
    start: float
    end: float
    snapped_start: bool
    snapped_end: bool
    pad_before_s: float
    pad_after_s: float

    @property
    def duration_s(self) -> float:
        return round(self.end - self.start, 3)


def _snap_point_to_words(point: float, words: list[Word], *, is_start: bool) -> tuple[float, bool]:
    """Se `point` cai estritamente dentro de uma palavra, empurra para a
    fronteira daquela palavra (start.start se is_start, senão word.end).
    Retorna (novo_ponto, houve_snap)."""
    for w in words:
        if w.start < point < w.end:
            return (w.start, True) if is_start else (w.end, True)
    return point, False




def snap_to_word_boundaries(
    start: float,
    end: float,
    words: list[Word],
    *,
    pad_before_s: float = 0.3,
    pad_after_s: float = 0.3,
    media_duration: float | None = None,
) -> BoundaryResult:
    """Ajusta (start, end) para nunca cortar palavra + aplica padding.

    `words` deve ser a lista de palavras da transcrição (não precisa estar
    restrita à janela; a função só olha para as que colidem com os pontos).
    """
    if end <= start:
        raise ValueError("end deve ser maior que start")

    words_sorted = sorted(words, key=lambda w: w.start)

    snapped_start, did_snap_start = _snap_point_to_words(start, words_sorted, is_start=True)
    snapped_end, did_snap_end = _snap_point_to_words(end, words_sorted, is_start=False)

    padded_start = snapped_start - max(0.0, pad_before_s)
    padded_end = snapped_end + max(0.0, pad_after_s)

    # Se o padding, por si só, empurrou o ponto para dentro de outra palavra
    # (gap entre palavras menor que a folga), estende até a fronteira dessa
    # palavra — o padding nunca deve cortar uma palavra pela metade (SPEC §14.1).
    padded_start, _ = _snap_point_to_words(padded_start, words_sorted, is_start=True)
    padded_end, _ = _snap_point_to_words(padded_end, words_sorted, is_start=False)

    padded_start = max(0.0, padded_start)
    if media_duration is not None:
        padded_end = min(media_duration, padded_end)

    if padded_end <= padded_start:
        # Janela degenerada (não deveria ocorrer com pads razoáveis); mantém ao menos o snap.
        padded_end = max(padded_end, padded_start + 0.01)

    return BoundaryResult(
        start=round(padded_start, 3),
        end=round(padded_end, 3),
        snapped_start=did_snap_start,
        snapped_end=did_snap_end,
        pad_before_s=pad_before_s,
        pad_after_s=pad_after_s,
    )


def snap_to_segment_boundaries(
    start: float,
    end: float,
    segments: list[Segment],
    *,
    pad_before_s: float = 0.3,
    pad_after_s: float = 0.3,
    media_duration: float | None = None,
) -> BoundaryResult:
    """Fallback quando não há timestamps por palavra: expande até o início/fim
    do segmento que contém cada ponto (segmentos costumam terminar em
    pontuação, então isso evita cortar no meio de uma frase)."""
    if end <= start:
        raise ValueError("end deve ser maior que start")

    segs_sorted = sorted(segments, key=lambda s: s.start)

    new_start = start
    did_snap_start = False
    for seg in segs_sorted:
        if seg.start <= start < seg.end:
            new_start = seg.start
            did_snap_start = new_start != start
            break

    new_end = end
    did_snap_end = False
    for seg in segs_sorted:
        if seg.start < end <= seg.end:
            new_end = seg.end
            did_snap_end = new_end != end
            break

    padded_start = max(0.0, new_start - max(0.0, pad_before_s))
    padded_end = new_end + max(0.0, pad_after_s)
    if media_duration is not None:
        padded_end = min(media_duration, padded_end)

    return BoundaryResult(
        start=round(padded_start, 3),
        end=round(padded_end, 3),
        snapped_start=did_snap_start,
        snapped_end=did_snap_end,
        pad_before_s=pad_before_s,
        pad_after_s=pad_after_s,
    )


def snap_window(
    start: float,
    end: float,
    *,
    words: list[Word] | None,
    segments: list[Segment] | None = None,
    pad_before_s: float = 0.3,
    pad_after_s: float = 0.3,
    media_duration: float | None = None,
) -> BoundaryResult:
    """Escolhe automaticamente snap por palavra (preferido) ou por segmento
    (fallback), conforme disponibilidade (SPEC §14.1)."""
    if words:
        return snap_to_word_boundaries(
            start,
            end,
            words,
            pad_before_s=pad_before_s,
            pad_after_s=pad_after_s,
            media_duration=media_duration,
        )
    if segments:
        return snap_to_segment_boundaries(
            start,
            end,
            segments,
            pad_before_s=pad_before_s,
            pad_after_s=pad_after_s,
            media_duration=media_duration,
        )
    # Sem palavras nem segmentos: não há como validar; retorna como veio.
    return BoundaryResult(
        start=round(max(0.0, start), 3),
        end=round(end, 3),
        snapped_start=False,
        snapped_end=False,
        pad_before_s=pad_before_s,
        pad_after_s=pad_after_s,
    )


def crosses_word_midpoint(start: float, end: float, words: list[Word]) -> bool:
    """True se `start` ou `end` caem estritamente dentro de alguma palavra
    (ou seja, o corte cortaria essa palavra pela metade). Útil em testes e em
    validação defensiva antes do render."""
    for w in words:
        if w.start < start < w.end or w.start < end < w.end:
            return True
    return False
