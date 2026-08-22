"""Deduplicação de candidatos por overlap temporal ou punchline repetida (SPEC §3, §14.3)."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
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

#: A comparação caractere-a-caractere só pega quase-cópias literais. Dois
#: candidatos que descrevem a **mesma ideia** com janelas diferentes dividem o
#: vocabulário mas não a sequência de caracteres, então o sinal que fecha esse
#: buraco é a sobreposição de palavras de conteúdo (SPEC §14.3: "mesma
#: punchline/ideia").
TOKEN_OVERLAP_THRESHOLD = 0.62

#: `SequenceMatcher` é O(n·m); com excerpts de milhares de caracteres e dezenas
#: de candidatos isso vira segundos de CPU só para deduplicar. Comparar os
#: primeiros caracteres já resolve o caso "mesma janela, texto idêntico".
MAX_CHARS_FOR_SEQUENCE_MATCH = 600

#: Palavras funcionais do PT-BR: aparecem em todo trecho e só inflariam a
#: interseção de vocabulário sem dizer nada sobre o assunto.
_STOPWORDS = frozenset(
    """
    a as o os um uma uns umas de do da dos das em no na nos nas por pelo pela
    pelos pelas para pra pro com sem sob sobre entre ate ate a e ou mas porque
    porem entao que quem qual quais quando onde como se ja nao sim muito mais
    menos tambem so apenas eu tu ele ela nos vos eles elas voce voces me te lhe
    nos vos os as lhes meu minha meus minhas teu tua seu sua seus suas nosso
    nossa isso isto aquilo esse essa este esta aquele aquela ai la aqui e era
    foi ser sou somos sao estar esta estao estava tem tinha ter teve vai vou
    fazer faz fez ficar fica muito bem tipo cara assim coisa dai né ne pois
    """.split()
)


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = text.encode("ascii", "ignore").decode("ascii")
    return text.lower()


def content_tokens(text: str) -> frozenset[str]:
    """Palavras de conteúdo (sem acento, sem stopword, ≥3 letras) do trecho."""
    words = re.findall(r"[a-z0-9]+", _normalize(text))
    return frozenset(w for w in words if len(w) >= 3 and w not in _STOPWORDS)


def token_overlap_ratio(a: frozenset[str], b: frozenset[str], *, min_tokens: int = 5) -> float:
    """Fração do vocabulário de conteúdo do trecho **mais curto** que reaparece
    no outro (0..1).

    Usar o menor dos dois como denominador é o que captura "o mesmo momento com
    mais setup em volta": o candidato curto está inteiro dentro do longo.
    """
    if len(a) < min_tokens or len(b) < min_tokens:
        return 0.0
    shortest = min(len(a), len(b))
    return len(a & b) / shortest


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
    return SequenceMatcher(
        None, a_norm[:MAX_CHARS_FOR_SEQUENCE_MATCH], b_norm[:MAX_CHARS_FOR_SEQUENCE_MATCH]
    ).ratio()


@dataclass
class DedupeItem(Generic[T]):
    item: T
    start: float
    end: float
    text: str
    score: float
    #: Janela do 9:16, quando existe. Dois candidatos podem se sobrepor pouco no
    #: 16:9 e ainda assim gerar praticamente o mesmo Short — e é o Short que vai
    #: para o TikTok.
    alt_start: float | None = None
    alt_end: float | None = None
    _tokens: frozenset[str] = field(default=frozenset(), repr=False, compare=False)

    def tokens(self) -> frozenset[str]:
        if not self._tokens:
            self._tokens = content_tokens(self.text)
        return self._tokens


@dataclass
class DedupeResult(Generic[T]):
    kept: list[T]
    removed_count: int
    removed_reasons: list[str]


def _worst_overlap(a: DedupeItem, b: DedupeItem) -> tuple[float, str]:
    """Maior overlap entre as janelas de A e B, olhando 16:9 e 9:16."""
    overlap = temporal_overlap_ratio(a.start, a.end, b.start, b.end)
    label = "overlap"
    if (
        a.alt_start is not None
        and a.alt_end is not None
        and b.alt_start is not None
        and b.alt_end is not None
    ):
        vertical = temporal_overlap_ratio(a.alt_start, a.alt_end, b.alt_start, b.alt_end)
        if vertical > overlap:
            return vertical, "overlap_9x16"
    return overlap, label


def dedupe_items(
    items: list[DedupeItem[T]],
    *,
    overlap_threshold: float = OVERLAP_RATIO_THRESHOLD,
    text_threshold: float = TEXT_SIMILARITY_THRESHOLD,
    token_threshold: float = TOKEN_OVERLAP_THRESHOLD,
) -> DedupeResult[T]:
    """Remove itens redundantes: overlap temporal > threshold (no 16:9 ou no
    9:16) OU mesma ideia — por vocabulário de conteúdo ou por texto quase
    idêntico. Mantém sempre o de maior score. Ordena por score desc para
    decidir quem "vence" primeiro (SPEC §3/§14.3)."""
    ordered = sorted(items, key=lambda d: d.score, reverse=True)
    kept: list[DedupeItem[T]] = []
    removed_count = 0
    removed_reasons: list[str] = []

    for candidate in ordered:
        reason = None
        for keeper in kept:
            overlap, label = _worst_overlap(candidate, keeper)
            if overlap > overlap_threshold:
                reason = f"{label}={overlap:.2f}"
                break
            tokens = token_overlap_ratio(candidate.tokens(), keeper.tokens())
            if tokens > token_threshold:
                reason = f"token_overlap={tokens:.2f}"
                break
            sim = text_similarity(
                candidate.text, keeper.text, min_words=MIN_WORDS_FOR_TEXT_MATCH
            )
            if sim > text_threshold:
                reason = f"text_similarity={sim:.2f}"
                break
        if reason is not None:
            removed_count += 1
            removed_reasons.append(reason)
            continue
        kept.append(candidate)

    return DedupeResult(kept=[k.item for k in kept], removed_count=removed_count, removed_reasons=removed_reasons)
