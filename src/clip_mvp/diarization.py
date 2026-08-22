"""Diarização (speaker↔rosto) com fallback documentado (SPEC §9, §14.6).

De onde vem a timeline de falantes, em ordem:

1. **Dos labels que o próprio STT já devolveu.** A SPEC §9 admite "modelo STT
   com speaker labels", e a transcrição já foi paga uma vez: quando o provider
   preenche ``speaker``/``speaker_id`` nos segmentos, a timeline sai de graça.
2. **De uma passada dedicada, se o usuário escolheu um modelo para isso.** O
   papel de diarização é configurável (tela de Configurações / 
   ``OPENROUTER_DIARIZATION_MODEL``) justamente porque o modelo de STT pode não
   expor speaker labels e outro modelo pode. Quando ele aponta para um modelo
   **diferente** do STT, vale pagar uma segunda passada — ela reusa o caminho
   chunkado da transcrição, então respeita o limite de tamanho do endpoint
   (SPEC §15), e entra na estimativa de custo (SPEC §14.4).
   Com o papel vazio (default) a segunda passada seria a mesma requisição, no
   mesmo modelo, para receber a mesma ausência de labels: puro desperdício.
3. **Fallback documentado (``activity_proxy``).** A maioria dos modelos
   Whisper-compatíveis na OpenRouter não expõe speaker labels hoje (SPEC §15).
   Sem timeline, o ``face_track`` escolhe o rosto de maior área (mais "em
   foco") como proxy de quem fala — heurística barata, adequada ao i5 16GB.

O método que de fato guiou o crop é sempre registrado em
``meta.json.speaker_matching.method``.
"""

from __future__ import annotations

from pathlib import Path

from .config import Settings
from .models import DiarizationResult, SpeakerSegment, Transcript
from .openrouter import OpenRouterClient

#: Dois segmentos consecutivos do mesmo falante separados por menos que isso são
#: a mesma fala: o STT quebra por frase, não por turno de conversa.
MERGE_GAP_S = 1.0


def uses_dedicated_pass(settings: Settings) -> bool:
    """O papel de diarização aponta para um modelo diferente do de STT?

    É o que decide se existe uma segunda passada de áudio a pagar. Também é
    consultado pela estimativa de custo, para o ``--budget`` não ser
    surpreendido (SPEC §14.4).
    """
    dedicated = (settings.diarization_model or "").strip()
    return bool(dedicated) and dedicated != (settings.stt_model or "").strip()


def diarization_from_transcript(transcript: Transcript) -> DiarizationResult:
    """Timeline de falantes a partir dos labels de speaker da transcrição.

    Segmentos consecutivos do mesmo falante são fundidos em um turno só, para
    que o face track não veja uma troca de falante em cada frase.
    """
    turns: list[SpeakerSegment] = []
    for seg in sorted(transcript.segments, key=lambda s: s.start):
        speaker = (seg.speaker or "").strip()
        if not speaker or seg.end <= seg.start:
            continue
        if turns and turns[-1].speaker == speaker and seg.start - turns[-1].end <= MERGE_GAP_S:
            turns[-1] = SpeakerSegment(start=turns[-1].start, end=seg.end, speaker=speaker)
            continue
        turns.append(SpeakerSegment(start=seg.start, end=seg.end, speaker=speaker))

    if not turns:
        return DiarizationResult(segments=[], method="unavailable")
    return DiarizationResult(segments=turns, method="diarization")


def diarize_with_dedicated_model(
    audio_path: Path,
    settings: Settings,
    *,
    client: OpenRouterClient | None = None,
) -> DiarizationResult:
    """Passada dedicada no modelo do papel de diarização (SPEC §9).

    Reusa ``transcribe_audio``, e não uma chamada solta com o arquivo inteiro:
    assim herda o chunking de ~10 min (SPEC §15), o paralelismo limitado e o
    escopo de label por bloco. O texto é descartado; só os speaker labels
    interessam.
    """
    from .transcribe import transcribe_audio

    try:
        transcript = transcribe_audio(
            audio_path, settings, client=client, model=settings.model_for_diarization()
        )
    except Exception:  # noqa: BLE001 - diarização é opcional; o fallback assume
        return DiarizationResult(segments=[], method="unavailable")
    return diarization_from_transcript(transcript)


def resolve_diarization(
    transcript: Transcript,
    audio_path: Path,
    settings: Settings,
    *,
    client: OpenRouterClient | None = None,
) -> DiarizationResult:
    """Melhor timeline de falantes disponível, da mais barata para a mais cara."""
    from_transcript = diarization_from_transcript(transcript)
    if from_transcript.segments:
        return from_transcript
    if uses_dedicated_pass(settings):
        return diarize_with_dedicated_model(audio_path, settings, client=client)
    return DiarizationResult(segments=[], method="unavailable")


def speaker_at(diarization: DiarizationResult, t: float) -> str | None:
    for seg in diarization.segments:
        if seg.start <= t < seg.end:
            return seg.speaker
    return None


def speaker_timeline(
    diarization: DiarizationResult | None,
    *,
    start: float,
    n_samples: int,
    dt: float,
) -> list[str | None]:
    """Quem está falando em cada amostra do face track (``None`` = silêncio).

    Uma varredura só, com ponteiro: o face track pergunta isso centenas de vezes
    por corte e um scan linear por amostra ficaria quadrático na transcrição.
    """
    if diarization is None or not diarization.segments:
        return [None] * max(0, n_samples)

    turns = sorted(diarization.segments, key=lambda s: s.start)
    timeline: list[str | None] = []
    cursor = 0
    for i in range(max(0, n_samples)):
        t = start + i * dt
        while cursor < len(turns) and turns[cursor].end <= t:
            cursor += 1
        turn = turns[cursor] if cursor < len(turns) else None
        timeline.append(turn.speaker if turn is not None and turn.start <= t else None)
    return timeline


def resolve_speaker_matching_method(
    diarization: DiarizationResult | None, *, used_for_crop: bool = True
) -> str:
    """Método a registrar em meta.json.speaker_matching.method (SPEC §14.6).

    ``used_for_crop=False`` cobre o caso em que existe timeline mas o
    ``vertical_facetrack`` não foi gerado: aí a diarização não guiou crop nenhum
    e dizer "diarization" seria propaganda, não informação.
    """
    if (
        used_for_crop
        and diarization is not None
        and diarization.method == "diarization"
        and diarization.segments
    ):
        return "diarization"
    return "activity_proxy"
