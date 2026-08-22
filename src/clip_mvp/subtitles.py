"""Legendas: SRT a partir de timestamps do Whisper + safe area p/ burn-in (SPEC §10, §14.5)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .models import Segment, Word

MAX_CHARS_PER_CUE = 42
MAX_WORDS_PER_CUE = 8
MAX_CUE_DURATION_S = 4.0

# Safe area 9:16 (SPEC §14.5): evitar ~20% inferior (UI TikTok/Shorts) e
# margens laterais apertadas -> texto centralizado na zona segura central.
VERTICAL_BOTTOM_SAFE_FRACTION = 0.20
VERTICAL_SIDE_MARGIN_FRACTION = 0.08
VERTICAL_FONT_FRACTION = 0.045

# 16:9 pode usar posicionamento clássico de terço inferior, menos restritivo.
HORIZONTAL_BOTTOM_SAFE_FRACTION = 0.06
HORIZONTAL_SIDE_MARGIN_FRACTION = 0.04
HORIZONTAL_FONT_FRACTION = 0.05


@dataclass
class SrtCue:
    index: int
    start: float
    end: float
    text: str


def _words_in_window(words: list[Word], start: float, end: float) -> list[Word]:
    return [w for w in sorted(words, key=lambda w: w.start) if w.end > start and w.start < end]


def build_cues_from_words(
    words: list[Word],
    window_start: float,
    window_end: float,
    *,
    max_chars: int = MAX_CHARS_PER_CUE,
    max_words: int = MAX_WORDS_PER_CUE,
    max_duration_s: float = MAX_CUE_DURATION_S,
) -> list[SrtCue]:
    """Agrupa palavras (já cortadas para a janela do clip) em cues de legenda,
    com timestamps relativos ao início do clip (t=0)."""
    in_window = _words_in_window(words, window_start, window_end)

    cues: list[SrtCue] = []
    buf: list[Word] = []

    def flush():
        if not buf:
            return
        text = " ".join(w.text for w in buf).strip()
        if not text:
            buf.clear()
            return
        rel_start = max(0.0, buf[0].start - window_start)
        rel_end = max(rel_start + 0.01, buf[-1].end - window_start)
        cues.append(SrtCue(index=len(cues) + 1, start=rel_start, end=rel_end, text=text))
        buf.clear()

    for w in in_window:
        candidate_text = " ".join([*(x.text for x in buf), w.text])
        would_exceed_chars = len(candidate_text) > max_chars
        would_exceed_words = len(buf) + 1 > max_words
        would_exceed_duration = buf and (w.end - buf[0].start) > max_duration_s
        ends_sentence = buf and buf[-1].text.strip().endswith((".", "!", "?", "…"))

        if buf and (would_exceed_chars or would_exceed_words or would_exceed_duration or ends_sentence):
            flush()
        buf.append(w)
    flush()

    return cues


def build_cues_from_segments(segments: list[Segment], window_start: float, window_end: float) -> list[SrtCue]:
    """Fallback sem word timestamps: uma cue por segmento que intersecta a janela."""
    cues: list[SrtCue] = []
    for seg in sorted(segments, key=lambda s: s.start):
        if seg.end <= window_start or seg.start >= window_end:
            continue
        rel_start = max(0.0, seg.start - window_start)
        rel_end = max(rel_start + 0.01, seg.end - window_start)
        cues.append(SrtCue(index=len(cues) + 1, start=rel_start, end=rel_end, text=seg.text.strip()))
    return cues


def _srt_timestamp(seconds: float) -> str:
    seconds = max(0.0, seconds)
    ms_total = round(seconds * 1000)
    hours, rem = divmod(ms_total, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def cues_to_srt(cues: list[SrtCue]) -> str:
    blocks = []
    for cue in cues:
        blocks.append(
            f"{cue.index}\n{_srt_timestamp(cue.start)} --> {_srt_timestamp(cue.end)}\n{cue.text}\n"
        )
    return "\n".join(blocks)


def write_srt(cues: list[SrtCue], path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(cues_to_srt(cues), encoding="utf-8")
    return path


def _ass_timestamp(seconds: float) -> str:
    seconds = max(0.0, seconds)
    cs_total = round(seconds * 100)
    hours, rem = divmod(cs_total, 360_000)
    minutes, rem = divmod(rem, 6_000)
    secs, cs = divmod(rem, 100)
    return f"{hours:d}:{minutes:02d}:{secs:02d}.{cs:02d}"


def build_ass(
    cues: list[SrtCue],
    video_width: int,
    video_height: int,
    *,
    is_vertical: bool,
) -> str:
    """Gera um arquivo .ass com estilo respeitando a safe area (SPEC §14.5):
    9:16 evita a faixa inferior (~20%) usada pela UI do TikTok/Shorts e usa
    margens laterais confortáveis; 16:9 usa terço inferior clássico."""
    if is_vertical:
        margin_v = int(video_height * VERTICAL_BOTTOM_SAFE_FRACTION)
        margin_lr = int(video_width * VERTICAL_SIDE_MARGIN_FRACTION)
        fontsize = max(18, int(video_height * VERTICAL_FONT_FRACTION))
    else:
        margin_v = int(video_height * HORIZONTAL_BOTTOM_SAFE_FRACTION)
        margin_lr = int(video_width * HORIZONTAL_SIDE_MARGIN_FRACTION)
        fontsize = max(18, int(video_height * HORIZONTAL_FONT_FRACTION))

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {video_width}
PlayResY: {video_height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,{fontsize},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,{margin_lr},{margin_lr},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    for cue in cues:
        text = cue.text.replace("\n", "\\N")
        lines.append(
            f"Dialogue: 0,{_ass_timestamp(cue.start)},{_ass_timestamp(cue.end)},Default,,0,0,0,,{text}"
        )
    return header + "\n".join(lines) + "\n"


def write_ass(cues: list[SrtCue], path: Path, video_width: int, video_height: int, *, is_vertical: bool) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_ass(cues, video_width, video_height, is_vertical=is_vertical), encoding="utf-8")
    return path
