"""Deduplicação de candidatos por overlap temporal ou punchline repetida (SPEC §3, §14.3)."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Generic, TypeVar

T = TypeVar("T")

TEXT_SIMILARITY_THRESHOLD = 0.82
OVERLAP_RATIO_THRESHOLD = 0.5

#: Similaridade de texto só é confiável com vocabulário suficiente: dois
#: trechos de 3 palavras ("Isso mudou tudo.") batem quase 100% por acaso e não
#: são o mesmo momento. Abaixo disso, só o overlap temporal decide. Na prática
#: um excerpt real de corte tem dezenas de palavras, então o piso só barra
#: casos degenerados.
MIN_WORDS_FOR_TEXT_MATCH = 6


def temporal_overlap_ratio(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    """Overlap relativo à janela mais curta (0..1). Ex.: se B está totalmente
    contido em A, overlap=1.0 mesmo que A seja bem maior — é isso que captura
    "mesmo momento, janela redundante" (SPEC §3/§14.3: overlap temporal >50%)."""
    inter_start = max(a_start, b_start)
    inter_end = min(a_end, b_end)
    inter = max(0.0, inter_end - inter_start)
    shortest = min(a_end - a_start, b_end - b_start)
    if shortest <= 0:
        return 0.0
    return inter / shortest


def text_similarity(a: str, b: str, *, min_words: int = 1) -> float:
    """Similaridade 0..1 entre dois trechos.

    ``min_words`` protege contra falso positivo: textos curtos demais não têm
    vocabulário suficiente para que a semelhança signifique "mesma ideia".
    """
    a_norm = (a or "").strip().lower()
    b_norm = (b or "").strip().lower()
    if not a_norm or not b_norm:
        return 0.0
    if len(a_norm.split()) < min_words or len(b_norm.split()) < min_words:
        return 0.0
    return SequenceMatcher(None, a_norm, b_norm).ratio()


@dataclass
class DedupeItem(Generic[T]):
    item: T
    start: float
    end: float
    text: str
    score: float


@dataclass
class DedupeResult(Generic[T]):
    kept: list[T]
    removed_count: int
    removed_reasons: list[str]


def dedupe_items(
    items: list[DedupeItem[T]],
    *,
    overlap_threshold: float = OVERLAP_RATIO_THRESHOLD,
    text_threshold: float = TEXT_SIMILARITY_THRESHOLD,
) -> DedupeResult[T]:
    """Remove itens redundantes: overlap temporal > threshold OU texto muito
    similar (mesma punchline/ideia). Mantém sempre o de maior score. Ordena
    por score desc para decidir quem "vence" primeiro (SPEC §3/§14.3)."""
    ordered = sorted(items, key=lambda d: d.score, reverse=True)
    kept: list[DedupeItem[T]] = []
    removed_count = 0
    removed_reasons: list[str] = []

    for candidate in ordered:
        duplicate_of = None
        reason = None
        for keeper in kept:
            overlap = temporal_overlap_ratio(candidate.start, candidate.end, keeper.start, keeper.end)
            if overlap > overlap_threshold:
                duplicate_of = keeper
                reason = f"overlap={overlap:.2f}"
                break
            sim = text_similarity(
                candidate.text, keeper.text, min_words=MIN_WORDS_FOR_TEXT_MATCH
            )
            if sim > text_threshold:
                duplicate_of = keeper
                reason = f"text_similarity={sim:.2f}"
                break
        if duplicate_of is not None:
            removed_count += 1
            removed_reasons.append(reason or "duplicate")
            continue
        kept.append(candidate)

    return DedupeResult(kept=[k.item for k in kept], removed_count=removed_count, removed_reasons=removed_reasons)
