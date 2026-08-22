"""Fronteira de corte: SPEC 2 e 14.1 (o requisito mais duro do produto)."""

from clip_mvp.boundaries import MIN_VERTICAL_S, Window, fit_vertical, snap_window
from clip_mvp.config import PAD_MAX_S, PAD_MIN_S, VERTICAL_MAX_S
from clip_mvp.transcript import SENTENCE_END, Segment, Transcript, Word


def _words(text: str, start: float, step: float = 0.4) -> list[Word]:
    out = []
    t = start
    for token in text.split():
        out.append(Word(start=t, end=t + step * 0.8, text=token))
        t += step
    return out


def _transcript(sentences: list[str], gap: float = 0.5) -> Transcript:
    segments: list[Segment] = []
    t = 1.0
    for sentence in sentences:
        words = _words(sentence, t)
        segments.append(
            Segment(start=words[0].start, end=words[-1].end, text=sentence, words=words)
        )
        t = words[-1].end + gap
    return Transcript(duration=t + 5.0, segments=segments)


def test_nunca_corta_no_meio_de_palavra(transcript):
    """Start/end sempre caem fora do intervalo de qualquer palavra."""
    window = snap_window(transcript, 120.7, 168.3)
    for word in transcript.words:
        assert not (word.start < window.start < word.end), "start caiu dentro de uma palavra"
        assert not (word.start < window.end < word.end), "end caiu dentro de uma palavra"


def test_snap_expande_ate_fechar_a_frase():
    data = _transcript(
        [
            "Primeira pergunta do host aqui.",
            "Resposta começa e continua",
            "e só termina agora com ponto.",
            "Outro assunto totalmente diferente.",
        ]
    )
    # Pedido termina no meio da resposta (segunda frase, sem pontuação forte).
    requested_end = data.segments[1].end
    window = snap_window(data, data.segments[1].start, requested_end)
    assert window.context_complete
    assert window.end >= data.segments[2].end
    assert SENTENCE_END.search(data.segments[2].text)


def test_pad_dentro_da_faixa_da_spec():
    data = _transcript(["Uma frase completa aqui.", "Outra frase completa aqui."])
    first = data.segments[0]
    window = snap_window(data, first.start + 0.05, first.end)
    pad_before = first.start - window.start
    assert 0 <= pad_before <= PAD_MAX_S + 1e-6
    assert PAD_MIN_S <= PAD_MAX_S  # sanidade da constante
    assert window.start >= 0.0


def test_pad_nao_invade_palavra_vizinha():
    data = _transcript(["Frase um curta.", "Frase dois curta."], gap=0.05)
    window = snap_window(data, data.segments[1].start, data.segments[1].end)
    assert window.start >= data.segments[0].end - 1e-6


def test_vertical_respeita_teto_de_90s(transcript):
    long_window = snap_window(transcript, 60.0, 260.0)
    assert long_window.duration > VERTICAL_MAX_S
    fitted = fit_vertical(transcript, long_window)
    if fitted is not None:
        assert fitted.duration <= VERTICAL_MAX_S
        assert fitted.context_complete
        assert fitted.duration >= MIN_VERTICAL_S


def test_vertical_descartado_quando_contexto_nao_fecha_em_90s():
    """Frase única de mais de 90s: melhor não exportar 9:16 do que truncar."""
    long_sentence = " ".join(["palavra"] * 400) + "."
    data = _transcript([long_sentence])
    window = snap_window(data, data.segments[0].start, data.segments[0].end)
    assert window.duration > VERTICAL_MAX_S
    assert fit_vertical(data, window) is None


def test_fit_vertical_mantem_o_fecho_do_contexto():
    data = _transcript(
        [
            "Setup bem longo que ocupa muito tempo da conversa toda.",
            "Mais setup ainda para estourar o limite de noventa segundos.",
            "A punchline vem aqui no final e fecha o raciocínio.",
        ]
    )
    window = Window(start=data.segments[0].start, end=data.segments[-1].end, context_complete=True)
    fitted = fit_vertical(data, window, max_duration=window.duration - 1.0)
    assert fitted is not None
    assert abs(fitted.end - window.end) < 1.0, "o fecho (punchline) tem que ficar no 9:16"


def test_fallback_para_segmentos_sem_word_timestamps():
    data = _transcript(["Uma frase completa.", "Outra frase completa."])
    for segment in data.segments:
        segment.words = []
    assert not data.has_word_timestamps
    window = snap_window(data, 0.0, data.segments[0].end)
    assert window.method == "segment"
    assert window.duration > 0
