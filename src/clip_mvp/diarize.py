"""Timeline de falantes (SPEC 9 e 14.6).

Preferência: labels de speaker vindos do STT do OpenRouter. Sem isso, o face
track cai no proxy de atividade facial e o método fica registrado no
`meta.json` (`diarization` vs `activity_proxy`).
"""

from __future__ import annotations

from dataclasses import dataclass

from .transcript import Transcript


@dataclass
class SpeakerTurn:
    start: float
    end: float
    speaker: str


def speaker_timeline(transcript: Transcript, start: float, end: float) -> list[SpeakerTurn]:
    """Turnos de fala dentro da janela, mesclando segmentos do mesmo falante."""
    turns: list[SpeakerTurn] = []
    for seg in transcript.segments:
        if not seg.speaker or seg.end <= start or seg.start >= end:
            continue
        turn_start = max(seg.start, start)
        turn_end = min(seg.end, end)
        if turn_end - turn_start <= 0.05:
            continue
        if turns and turns[-1].speaker == seg.speaker and turn_start - turns[-1].end < 0.6:
            turns[-1] = SpeakerTurn(turns[-1].start, turn_end, seg.speaker)
        else:
            turns.append(SpeakerTurn(turn_start, turn_end, seg.speaker))
    return turns


def speaker_at(turns: list[SpeakerTurn], t: float) -> str | None:
    for turn in turns:
        if turn.start <= t <= turn.end:
            return turn.speaker
    return None


def speakers_in(turns: list[SpeakerTurn]) -> list[str]:
    seen: list[str] = []
    for turn in turns:
        if turn.speaker not in seen:
            seen.append(turn.speaker)
    return seen
