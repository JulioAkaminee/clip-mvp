"""Lógica determinística de fronteira de corte (SPEC §2.5 / §14.1).

Regra dura do produto: a IA nunca deve cortar no meio de uma palavra. Este
módulo é puro (sem I/O) para ser fácil de testar: dado uma janela proposta
(possivelmente "no meio" de uma palavra) e a lista de palavras/segmentos da
transcrição, produz uma janela ajustada que:

1. Nunca corta uma palavra pela metade (sempre inclui a palavra inteira caso
   o corte proposto caia dentro dela).
2. Expande início/fim até o **contexto fechar** — começo de fala e pontuação
   terminal (SPEC §2, regras 1 a 3). Sem isso o snap por palavra ainda entrega
   corte que começa no meio da frase.
3. Aplica folga (padding) de 200-400ms antes do início e depois do fim, sem
   invadir a fala vizinha.
4. Se só houver timestamps de segmento (sem palavra), expande até o fim do
   segmento (que normalmente termina em pontuação).
5. Nunca deixa o resultado sair do intervalo válido de mídia [0, duration].
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import Segment, Word

#: Pontuação que indica ideia fechada.
TERMINAL_PUNCT = ".!?…"

#: Quanto podemos esticar procurando o fechamento do contexto (SPEC §2.3:
#: "estender o fim até o bloco conversacional fechar").
MAX_FORWARD_EXPAND_S = 12.0
MAX_BACKWARD_EXPAND_S = 8.0

#: Silêncio entre palavras que já vale como fronteira natural de bloco.
NATURAL_GAP_S = 0.45

#: Janela que o espectador usa para decidir se continua assistindo (SPEC §8: hook).
HOOK_WINDOW_S = 3.0


@dataclass(frozen=True)
class BoundaryResult:
    start: float
    end: float
    snapped_start: bool
    snapped_end: bool
    pad_before_s: float
    pad_after_s: float
    #: True quando começa em fronteira de fala e termina em pontuação terminal.
    context_complete: bool = False
    starts_on_sentence: bool = False
    ends_on_sentence: bool = False
    expanded_start_s: float = 0.0
    expanded_end_s: float = 0.0

    @property
    def duration_s(self) -> float:
        return round(self.end - self.start, 3)


def ends_sentence(word: Word) -> bool:
    text = (word.text or "").strip()
    return bool(text) and text[-1] in TERMINAL_PUNCT


def words_in_window(words: list[Word], start: float, end: float) -> list[Word]:
    """Palavras faladas dentro de ``[start, end]``, em ordem.

    Inclui a palavra que só encosta na janela: é o que o espectador ouve.
    """
    return [
        w
        for w in sorted(words, key=lambda w: w.start)
        if w.end > start + 1e-6 and w.start < end - 1e-6
    ]


def text_in_window(words: list[Word], start: float, end: float) -> str:
    """Transcrição real da janela — o texto que o corte exportado vai dizer.

    Usar isto em vez do ``text_excerpt`` que o LLM de candidatos escreveu é o
    que faz a penalidade de truncamento e o scorer julgarem o corte de verdade,
    e não uma paráfrase que pode ter sido aparada em qualquer ponto.
    """
    return " ".join(w.text.strip() for w in words_in_window(words, start, end) if w.text.strip())


def hook_text(words: list[Word], start: float, *, hook_window_s: float = HOOK_WINDOW_S) -> str:
    """O que é dito nos primeiros segundos do corte (SPEC §8: hook 0–25)."""
    return text_in_window(words, start, start + max(0.1, hook_window_s))


def segment_text_in_window(segments: list[Segment], start: float, end: float) -> str:
    """Fallback de :func:`text_in_window` quando o STT só deu segmentos."""
    parts = [
        (seg.text or "").strip()
        for seg in sorted(segments, key=lambda s: s.start)
        if seg.end > start + 1e-6 and seg.start < end - 1e-6
    ]
    return " ".join(p for p in parts if p)


def _snap_point_to_words(point: float, words: list[Word], *, is_start: bool) -> tuple[float, bool]:
    """Se `point` cai estritamente dentro de uma palavra, empurra para a
    fronteira daquela palavra (start.start se is_start, senão word.end).
    Retorna (novo_ponto, houve_snap)."""
    for w in words:
        if w.start < point < w.end:
            return (w.start, True) if is_start else (w.end, True)
    return point, False


def _index_of_start(point: float, words: list[Word]) -> int:
    """Índice da palavra que inicia a janela em `point`."""
    for i, w in enumerate(words):
        if w.end > point + 1e-6:
            return i
    return max(0, len(words) - 1)


def _index_of_end(point: float, words: list[Word]) -> int:
    """Índice da última palavra inteiramente contida até `point`."""
    for i in range(len(words) - 1, -1, -1):
        if words[i].start < point - 1e-6:
            return i
    return 0


def expand_end_to_closed_context(
    words: list[Word], idx: int, *, max_expand_s: float = MAX_FORWARD_EXPAND_S
) -> tuple[int, bool]:
    """Avança até a próxima palavra com pontuação terminal (SPEC §2.2).

    Se não houver pontuação dentro do limite, aceita uma pausa longa como
    fronteira natural. Retorna ``(índice, fechou_frase)``.
    """
    if not words:
        return idx, False
    idx = min(max(idx, 0), len(words) - 1)
    if ends_sentence(words[idx]):
        return idx, True

    limit = words[idx].end + max_expand_s
    j = idx
    while j + 1 < len(words) and words[j + 1].end <= limit:
        j += 1
        if ends_sentence(words[j]):
            return j, True

    k = idx
    while k + 1 < len(words) and words[k + 1].end <= limit:
        k += 1
        if k + 1 < len(words) and (words[k + 1].start - words[k].end) >= NATURAL_GAP_S:
            return k, False
    return j, False


def expand_start_to_closed_context(
    words: list[Word], idx: int, *, max_expand_s: float = MAX_BACKWARD_EXPAND_S
) -> tuple[int, bool]:
    """Recua até logo depois de uma pontuação terminal (SPEC §2.1).

    Evita o clássico "corte que começa no meio da frase". Retorna
    ``(índice, começa_em_fronteira_de_fala)``.
    """
    if not words:
        return idx, False
    idx = min(max(idx, 0), len(words) - 1)
    if idx == 0 or ends_sentence(words[idx - 1]):
        return idx, True

    limit = words[idx].start - max_expand_s
    j = idx
    while j - 1 >= 0 and words[j - 1].start >= limit:
        j -= 1
        if j == 0 or ends_sentence(words[j - 1]):
            return j, True
        if (words[j].start - words[j - 1].end) >= NATURAL_GAP_S:
            return j, False
    return j, False


def _pad_without_swallowing(
    gap_s: float, pad_min_s: float, pad_max_s: float
) -> float:
    """Folga real: nunca invade a palavra vizinha.

    Com espaço de sobra usa o pad máximo; com pouco espaço divide o silêncio
    com a fala vizinha, respeitando o mínimo da spec quando possível.
    """
    if gap_s <= 0:
        return 0.0
    if gap_s >= pad_max_s:
        return pad_max_s
    if gap_s >= pad_min_s:
        return max(pad_min_s, gap_s * 0.5)
    return gap_s




def snap_to_word_boundaries(
    start: float,
    end: float,
    words: list[Word],
    *,
    pad_before_s: float = 0.3,
    pad_after_s: float = 0.3,
    media_duration: float | None = None,
    expand_to_context: bool = True,
) -> BoundaryResult:
    """Ajusta (start, end) para nunca cortar palavra nem contexto + padding.

    Ordem das operações (importa):

    1. snap para fronteira de palavra (nunca no meio de palavra);
    2. expande até o contexto fechar, se ``expand_to_context`` (SPEC §2);
    3. aplica folga limitada ao silêncio disponível — a folga nunca engole
       uma palavra da fala vizinha.

    `words` deve ser a lista de palavras da transcrição (não precisa estar
    restrita à janela; a função só olha para as que colidem com os pontos).
    """
    if end <= start:
        raise ValueError("end deve ser maior que start")

    words_sorted = sorted(words, key=lambda w: w.start)
    if not words_sorted:
        return BoundaryResult(
            start=round(max(0.0, start - pad_before_s), 3),
            end=round(end + pad_after_s, 3),
            snapped_start=False,
            snapped_end=False,
            pad_before_s=pad_before_s,
            pad_after_s=pad_after_s,
        )

    snapped_start, did_snap_start = _snap_point_to_words(start, words_sorted, is_start=True)
    snapped_end, did_snap_end = _snap_point_to_words(end, words_sorted, is_start=False)

    i0 = _index_of_start(snapped_start, words_sorted)
    i1 = max(i0, _index_of_end(snapped_end, words_sorted))

    starts_on_sentence = i0 == 0 or ends_sentence(words_sorted[i0 - 1])
    ends_on_sentence = ends_sentence(words_sorted[i1])
    expanded_start_s = 0.0
    expanded_end_s = 0.0

    if expand_to_context:
        new_i0, starts_on_sentence = expand_start_to_closed_context(words_sorted, i0)
        if new_i0 < i0:
            expanded_start_s = words_sorted[i0].start - words_sorted[new_i0].start
            i0 = new_i0
        new_i1, _ = expand_end_to_closed_context(words_sorted, i1)
        if new_i1 > i1:
            expanded_end_s = words_sorted[new_i1].end - words_sorted[i1].end
            i1 = new_i1
        ends_on_sentence = ends_sentence(words_sorted[i1])

    word_start = words_sorted[i0].start
    word_end = words_sorted[i1].end

    gap_before = word_start - (words_sorted[i0 - 1].end if i0 > 0 else 0.0)
    ceiling = media_duration if media_duration is not None else float("inf")
    next_start = words_sorted[i1 + 1].start if i1 + 1 < len(words_sorted) else ceiling
    gap_after = min(next_start, ceiling) - word_end

    pad_min = min(pad_before_s, pad_after_s)
    pad_max = max(pad_before_s, pad_after_s)
    lead = _pad_without_swallowing(gap_before, pad_min, pad_max)
    tail = _pad_without_swallowing(gap_after, pad_min, pad_max)

    padded_start = max(0.0, word_start - lead)
    padded_end = word_end + tail
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
        context_complete=starts_on_sentence and ends_on_sentence,
        starts_on_sentence=starts_on_sentence,
        ends_on_sentence=ends_on_sentence,
        expanded_start_s=round(expanded_start_s, 3),
        expanded_end_s=round(expanded_end_s, 3),
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
    end_index: int | None = None
    for i, seg in enumerate(segs_sorted):
        if seg.start < end <= seg.end:
            new_end = seg.end
            did_snap_end = new_end != end
            end_index = i
            break

    # Sem word timestamps a granularidade é o segmento; se ele não fecha em
    # pontuação, segue para o próximo até fechar (SPEC §14.1).
    ends_on_sentence = False
    if end_index is not None:
        j = end_index
        while j < len(segs_sorted):
            text = (segs_sorted[j].text or "").strip()
            if text and text[-1] in TERMINAL_PUNCT:
                new_end = segs_sorted[j].end
                ends_on_sentence = True
                break
            if segs_sorted[j].end - new_start > MAX_FORWARD_EXPAND_S + (end - start):
                break
            j += 1
        else:
            new_end = segs_sorted[-1].end

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
        context_complete=ends_on_sentence,
        starts_on_sentence=True,
        ends_on_sentence=ends_on_sentence,
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
    expand_to_context: bool = True,
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
            expand_to_context=expand_to_context,
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


def fit_vertical_window(
    start: float,
    end: float,
    words: list[Word],
    *,
    max_duration_s: float = 90.0,
    pad_before_s: float = 0.2,
    pad_after_s: float = 0.4,
    media_duration: float | None = None,
) -> tuple[BoundaryResult | None, str | None]:
    """Tenta caber o momento em ≤90s **sem** truncar frase (SPEC §2).

    A spec dá duas saídas para um contexto maior que 90s: (a) encolher, se
    ainda houver contexto completo numa janela menor, ou (b) descartar o
    vertical. Descartar direto joga fora 9:16 que era perfeitamente
    exportável, então tentamos (a) primeiro: procuramos a maior sub-janela que
    comece em fronteira de fala, termine em pontuação terminal e caiba no teto
    — preferindo as que terminam junto do fim canônico, porque é lá que mora a
    punchline.

    Retorna ``(janela, motivo_do_skip)``; um dos dois é sempre ``None``.
    """
    if end - start <= max_duration_s:
        result = snap_to_word_boundaries(
            start,
            end,
            words,
            pad_before_s=pad_before_s,
            pad_after_s=pad_after_s,
            media_duration=media_duration,
        )
        if result.duration_s <= max_duration_s:
            return result, None

    inner = [w for w in sorted(words, key=lambda w: w.start) if w.start >= start - 1e-3 and w.end <= end + 1e-3]
    if not inner:
        return None, "context_exceeds_90s"

    # Um início de fala vale mais que uma simples pausa: começar logo depois de
    # um ponto final soa como o começo de uma ideia, começar numa pausa no meio
    # do raciocínio não.
    starts: list[tuple[int, bool]] = []
    for i, w in enumerate(inner):
        after_sentence = i == 0 or ends_sentence(inner[i - 1])
        after_pause = i > 0 and (w.start - inner[i - 1].end) >= NATURAL_GAP_S
        if after_sentence or after_pause:
            starts.append((i, after_sentence))
    ends = [i for i, w in enumerate(inner) if ends_sentence(w)]
    if not ends or not starts:
        return None, "context_exceeds_90s"

    best: tuple[tuple[bool, float], int, int] | None = None
    for ei in reversed(ends):  # preferir terminar o mais perto da punchline
        for si, after_sentence in starts:
            if si > ei:
                continue
            duration = inner[ei].end - inner[si].start + pad_before_s + pad_after_s
            if duration > max_duration_s:
                continue
            rank = (after_sentence, duration)
            if best is None or rank > best[0]:
                best = (rank, si, ei)
        if best is not None:
            break

    if best is None:
        return None, "context_exceeds_90s"

    _, si, ei = best
    fitted = snap_to_word_boundaries(
        inner[si].start,
        inner[ei].end,
        words,
        pad_before_s=pad_before_s,
        pad_after_s=pad_after_s,
        media_duration=media_duration,
        expand_to_context=False,
    )
    if fitted.duration_s > max_duration_s or not fitted.ends_on_sentence:
        return None, "context_exceeds_90s"
    return fitted, None


def crosses_word_midpoint(start: float, end: float, words: list[Word]) -> bool:
    """True se `start` ou `end` caem estritamente dentro de alguma palavra
    (ou seja, o corte cortaria essa palavra pela metade). Útil em testes e em
    validação defensiva antes do render."""
    for w in words:
        if w.start < start < w.end or w.start < end < w.end:
            return True
    return False
