"""STT via OpenRouter (Whisper) — verbose_json / word timestamps (SPEC §14.1)."""

from __future__ import annotations

import math
import re
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable

from .config import Settings
from .models import Segment, Transcript, Word
from .openrouter import OpenRouterClient
from .utils import ffprobe_duration, run_ffmpeg, write_json

CHUNK_SECONDS_DEFAULT = 600  # ~10 min, SPEC §6

#: Pontuação que o Whisper devolve grudada no fim de uma palavra.
_TRAILING_PUNCT = ".,!?;:…\u2026\u201d\u2019)\u00bb"
_NOT_WORD = re.compile(r"[^0-9A-Za-z\u00c0-\u017f]+")


def _norm_token(token: str) -> str:
    return _NOT_WORD.sub("", token).lower()


def _trailing_punct(token: str) -> str:
    stripped = token.rstrip()
    tail = ""
    while stripped and stripped[-1] in _TRAILING_PUNCT:
        tail = stripped[-1] + tail
        stripped = stripped[:-1]
    return tail


def attach_punctuation(text: str, words: list[Word]) -> list[Word]:
    """Reancora nas palavras a pontuação que só existe no texto do segmento.

    O endpoint de transcrição devolve ``segments[].text`` pontuado, mas os
    tokens de ``words[]`` chegam sem nenhuma pontuação. Como toda a lógica de
    fronteira pergunta "esta palavra termina a frase?" (:func:`ends_sentence`),
    sem isto ``context_complete`` é sempre falso, todo corte leva o teto de
    score de trecho truncado e nenhum passa do limiar. É a diferença entre o
    pipeline funcionar e entregar só cortes reprovados.
    """
    rich = [token for token in (text or "").split() if token.strip()]
    if not rich or not words:
        return words
    if any(_trailing_punct(w.text) for w in words):
        return words  # já veio pontuado: nada a fazer

    out = [w.model_copy() for w in words]
    rich_norm = [_norm_token(token) for token in rich]
    word_norm = [_norm_token(w.text) for w in out]

    matcher = SequenceMatcher(a=rich_norm, b=word_norm, autojunk=False)
    for tag, i1, _i2, j1, j2 in matcher.get_opcodes():
        if tag != "equal":
            continue
        for offset in range(j2 - j1):
            tail = _trailing_punct(rich[i1 + offset])
            if tail:
                out[j1 + offset].text = out[j1 + offset].text + tail

    # Garantia mínima: se o segmento fecha frase, a última palavra dele também
    # fecha — mesmo que o alinhamento token a token tenha falhado no meio.
    final_tail = _trailing_punct(rich[-1])
    if final_tail and not _trailing_punct(out[-1].text):
        out[-1].text = out[-1].text + final_tail
    return out


def _assign_words_to_segments(segments: list[Segment], words: list[Word]) -> None:
    """Distribui cada palavra para **um** segmento só.

    Antes a fatia era ``seg_start - 0.05 <= w.start <= seg_end + 0.05`` por
    segmento, com as folgas se sobrepondo: 7% das palavras de um podcast de 2h
    caíam em dois segmentos e apareciam repetidas no excerpt e na legenda
    ("direitinho Ele Ele era"). Cada palavra pertence ao segmento que cobre o
    seu meio; sem cobertura, ao segmento mais próximo.
    """
    for seg in segments:
        seg.words = []
    if not segments:
        return
    ordered = sorted(segments, key=lambda s: s.start)
    for word in sorted(words, key=lambda w: w.start):
        midpoint = (word.start + word.end) / 2.0
        home = next(
            (seg for seg in ordered if seg.start - 0.05 <= midpoint <= seg.end + 0.05),
            None,
        )
        if home is None:
            home = min(ordered, key=lambda s: min(abs(midpoint - s.start), abs(midpoint - s.end)))
        home.words.append(word)


#: Texto que o Whisper inventa em trecho sem fala. A lista é curta e literal de
#: propósito: "repetiu muito" **não** serve como critério sozinho — num podcast
#: de rap o refrão repete, e "Tá ligado?" apareceu 30 vezes por ser bordão real
#: de quem estava falando. Só derrubamos o que também parece boilerplate.
_HALLUCINATION_PATTERNS = (
    re.compile(r"^\s*(?:https?://|www\.)\S*\s*$", re.IGNORECASE),
    re.compile(r"^\s*\S+\.(?:com|net|org|br|pt|tp|io)(?:\.\w+)?\s*$", re.IGNORECASE),
    re.compile(r"amara\.org", re.IGNORECASE),
    re.compile(r"legendas?\s+(?:pela|por)\s+", re.IGNORECASE),
    re.compile(r"^\s*(?:subtitles?|subscribe|thanks?\s+for\s+watching)\b", re.IGNORECASE),
)

#: Quantas vezes o mesmo texto precisa aparecer para virar suspeito.
_HALLUCINATION_MIN_REPEATS = 3


def looks_like_boilerplate(text: str) -> bool:
    stripped = (text or "").strip()
    if not stripped:
        return False
    return any(pattern.search(stripped) for pattern in _HALLUCINATION_PATTERNS)


def drop_hallucinated_segments(transcript: Transcript) -> int:
    """Esvazia segmentos que o STT alucinou em cima de silêncio.

    O Whisper preenche trecho sem fala com boilerplate — URL de legenda,
    crédito de tradução, "obrigado por assistir". Num podcast de 2h isso virou
    51 segmentos de `www.opusdei.tp`, e um deles chegou a ancorar o começo de um
    corte: o Short abria com a IA lendo uma URL.

    O texto é zerado em vez de removido: os tempos continuam válidos para o
    resto do pipeline, e o trecho simplesmente deixa de existir como fala.
    Devolve quantos segmentos foram esvaziados.
    """
    counts: dict[str, int] = {}
    for seg in transcript.segments:
        key = seg.text.strip().lower()
        if key:
            counts[key] = counts.get(key, 0) + 1

    dropped = 0
    for seg in transcript.segments:
        key = seg.text.strip().lower()
        if not key or counts.get(key, 0) < _HALLUCINATION_MIN_REPEATS:
            continue
        if not looks_like_boilerplate(seg.text):
            continue
        seg.text = ""
        seg.words = []
        dropped += 1
    return dropped


def repair_transcript(transcript: Transcript) -> Transcript:
    """Conserta uma transcrição no lugar: sem palavra repetida, com pontuação.

    Idempotente, e roda também em transcrição vinda do cache: um podcast longo
    já transcrito não precisa ser pago de novo para ganhar a correção.
    """
    drop_hallucinated_segments(transcript)
    if not any(seg.words for seg in transcript.segments):
        return transcript

    unique: dict[tuple[int, int, str], Word] = {}
    for seg in transcript.segments:
        for word in seg.words:
            key = (round(word.start * 1000), _norm_token(word.text))
            # Fica a versão mais rica do token (a que já tiver pontuação).
            current = unique.get(key)
            if current is None or len(word.text) > len(current.text):
                unique[key] = word

    _assign_words_to_segments(transcript.segments, list(unique.values()))
    for seg in transcript.segments:
        if seg.words:
            seg.words = attach_punctuation(seg.text, seg.words)
    return transcript


def _split_audio(audio_path: Path, chunk_seconds: int, tmp_dir: Path) -> list[tuple[Path, float]]:
    """Divide o áudio em pedaços de `chunk_seconds`, retornando (path, offset_s)."""
    duration = ffprobe_duration(audio_path)
    if duration <= chunk_seconds:
        return [(audio_path, 0.0)]

    n_chunks = math.ceil(duration / chunk_seconds)
    chunks: list[tuple[Path, float]] = []
    for i in range(n_chunks):
        offset = i * chunk_seconds
        chunk_path = tmp_dir / f"chunk_{i:03d}.wav"
        run_ffmpeg(
            [
                "-i",
                str(audio_path),
                "-ss",
                str(offset),
                "-t",
                str(chunk_seconds),
                "-ac",
                "1",
                str(chunk_path),
            ]
        )
        chunks.append((chunk_path, float(offset)))
    return chunks


def _parse_verbose_json(raw: dict[str, Any], offset_s: float, id_start: int) -> list[Segment]:
    """Converte a resposta verbose_json (Whisper) em Segments com Words,
    aplicando o offset do chunk. Tolerante a formatos levemente diferentes
    entre providers na OpenRouter (SPEC §15)."""
    raw_segments = raw.get("segments") or []
    raw_words = raw.get("words") or []

    words_all = [
        Word(
            start=float(w.get("start", 0.0)) + offset_s,
            end=float(w.get("end", 0.0)) + offset_s,
            text=str(w.get("word", w.get("text", ""))).strip(),
        )
        for w in raw_words
    ]

    segments: list[Segment] = []
    if raw_segments:
        for i, seg in enumerate(raw_segments):
            seg_start = float(seg.get("start", 0.0)) + offset_s
            seg_end = float(seg.get("end", seg_start)) + offset_s
            segments.append(
                Segment(
                    id=id_start + i,
                    start=seg_start,
                    end=seg_end,
                    text=str(seg.get("text", "")).strip(),
                    words=[],
                )
            )
        _assign_words_to_segments(segments, words_all)
        for seg in segments:
            seg.words = attach_punctuation(seg.text, seg.words)
    elif words_all:
        # Sem segmentos, mas com palavras: cria um único segmento cobrindo tudo.
        text = raw.get("text", "") or " ".join(w.text for w in words_all)
        segments.append(
            Segment(
                id=id_start,
                start=words_all[0].start,
                end=words_all[-1].end,
                text=text.strip(),
                words=words_all,
            )
        )
    elif raw.get("text"):
        segments.append(
            Segment(
                id=id_start,
                start=offset_s,
                end=offset_s,
                text=str(raw["text"]).strip(),
                words=[],
            )
        )

    return segments


def transcribe_audio(
    audio_path: Path,
    settings: Settings,
    *,
    client: OpenRouterClient | None = None,
    language: str = "pt",
    chunk_seconds: int = CHUNK_SECONDS_DEFAULT,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> Transcript:
    """Transcreve o áudio completo (com chunking ~10min) via OpenRouter Whisper.

    Os chunks são enviados em paralelo limitado: STT é espera de rede, e um
    podcast de 1h vira 6 chamadas que não precisam ser sequenciais.

    `client` pode ser injetado (ex.: em testes) para evitar chamadas de rede.
    ``on_progress(concluídos, total, mensagem)`` alimenta a barra e o ETA.
    """
    client = client or OpenRouterClient(settings)
    audio_path = Path(audio_path)

    tmp_dir = Path(tempfile.mkdtemp(prefix="clip_mvp_stt_"))
    try:
        chunks = _split_audio(audio_path, chunk_seconds, tmp_dir)
        total = len(chunks)
        results: dict[int, dict[str, Any]] = {}
        done = 0

        if on_progress:
            on_progress(0, total, f"Transcrevendo… 0/{total} blocos")

        def work(index: int) -> tuple[int, dict[str, Any]]:
            chunk_path, _offset = chunks[index]
            return index, client.transcribe(chunk_path, language=language)

        workers = max(1, min(settings.network_workers, total))
        if workers == 1 or total == 1:
            for i in range(total):
                results[i] = work(i)[1]
                done += 1
                if on_progress:
                    on_progress(done, total, f"Transcrevendo… {done}/{total} blocos")
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [pool.submit(work, i) for i in range(total)]
                for future in as_completed(futures):
                    index, raw = future.result()
                    results[index] = raw
                    done += 1
                    if on_progress:
                        on_progress(done, total, f"Transcrevendo… {done}/{total} blocos")

        # remonta na ordem cronológica: a ordem de conclusão do pool é arbitrária
        all_segments: list[Segment] = []
        next_id = 0
        for i in range(total):
            raw = results.get(i)
            if raw is None:
                continue
            segs = _parse_verbose_json(raw, chunks[i][1], next_id)
            all_segments.extend(segs)
            next_id += len(segs)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    duration = all_segments[-1].end if all_segments else 0.0
    has_words = any(seg.words for seg in all_segments)

    return Transcript(
        language=language,
        duration=duration,
        segments=all_segments,
        source="openrouter_whisper",
        has_word_timestamps=has_words,
    )


def dump_transcript(transcript: Transcript, job_dir: Path) -> Path:
    """Salva a transcrição em work/<job_id>/transcript.json (SPEC §5)."""
    path = Path(job_dir) / "transcript.json"
    write_json(path, transcript.model_dump())
    return path


def load_transcript(job_dir: Path) -> Transcript:
    from .utils import read_json

    path = Path(job_dir) / "transcript.json"
    return repair_transcript(Transcript.model_validate(read_json(path)))
