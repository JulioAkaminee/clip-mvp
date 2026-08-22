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
class CueWord:
    text: str
    start: float
    end: float


@dataclass
class SrtCue:
    index: int
    start: float
    end: float
    text: str
    words: list[CueWord] | None = None


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
        cue_words = [
            CueWord(
                text=item.text,
                start=max(0.0, item.start - window_start),
                end=max(0.01, item.end - window_start),
            )
            for item in buf
            if item.text.strip()
        ]
        cues.append(
            SrtCue(index=len(cues) + 1, start=rel_start, end=rel_end, text=text, words=cue_words)
        )
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
        text = seg.text.strip()
        cues.append(
            SrtCue(
                index=len(cues) + 1,
                start=rel_start,
                end=rel_end,
                text=text,
                words=_estimate_words(text, rel_start, rel_end),
            )
        )
    return cues


def _estimate_words(text: str, start: float, end: float) -> list[CueWord]:
    tokens = [part for part in text.split() if part.strip()]
    if not tokens:
        return []
    span = max(0.05, end - start)
    step = span / len(tokens)
    return [
        CueWord(text=token, start=start + i * step, end=start + (i + 1) * step)
        for i, token in enumerate(tokens)
    ]


def cues_to_json(cues: list[SrtCue]) -> dict:
    return {
        "cues": [
            {
                "start": cue.start,
                "end": cue.end,
                "text": cue.text,
                "words": [
                    {"text": word.text, "start": word.start, "end": word.end}
                    for word in (cue.words or _estimate_words(cue.text, cue.start, cue.end))
                ],
            }
            for cue in cues
        ]
    }


def write_captions_json(cues: list[SrtCue], path: Path) -> Path:
    from .utils import write_json

    path = Path(path)
    write_json(path, cues_to_json(cues))
    return path


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


def hex_to_ass_color(hex_color: str, alpha: str = "00") -> str:
    """Converte formato web #RRGGBB em formato ASS &HAABBGGRR."""
    if not hex_color:
        return f"&H{alpha}FFFFFF"
    c = hex_color.strip().lstrip("#")
    if c.startswith("&H"):
        return c
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    if len(c) == 6:
        r, g, b = c[0:2], c[2:4], c[4:6]
        return f"&H{alpha}{b}{g}{r}".upper()
    return f"&H{alpha}FFFFFF"


def build_ass(
    cues: list[SrtCue],
    video_width: int,
    video_height: int,
    *,
    is_vertical: bool,
    style: str = "viral",
    position_v: float | None = None,
    font_size_scale: float = 1.0,
    primary_color: str | None = None,
    outline_color: str | None = None,
    is_uppercase: bool = False,
) -> str:
    """Gera um arquivo .ass com estilo customizável e safe area (SPEC §14.5).
    
    Suporta estilos pré-definidos (viral/Hormozi, minimal, cyber, gradient, punchy)
    e posicionamento vertical livre (0.10 a 0.90 de altura).
    """
    scale = max(0.5, min(2.5, font_size_scale or 1.0))
    if position_v is not None and 0.05 <= position_v <= 0.95:
        margin_v = int(video_height * position_v)
    elif is_vertical:
        margin_v = int(video_height * VERTICAL_BOTTOM_SAFE_FRACTION)
    else:
        margin_v = int(video_height * HORIZONTAL_BOTTOM_SAFE_FRACTION)

    if is_vertical:
        margin_lr = int(video_width * VERTICAL_SIDE_MARGIN_FRACTION)
        base_font = max(18, int(video_height * VERTICAL_FONT_FRACTION * scale))
    else:
        margin_lr = int(video_width * HORIZONTAL_SIDE_MARGIN_FRACTION)
        base_font = max(18, int(video_height * HORIZONTAL_FONT_FRACTION * scale))

    # Configuração do preset visual
    font_name = "Arial"
    p_color = hex_to_ass_color(primary_color or "#FFFF00") if primary_color else "&H0000FFFF"  # Amarelo viral padrão
    o_color = hex_to_ass_color(outline_color or "#000000") if outline_color else "&H00000000"  # Contorno preto
    b_color = "&H80000000"
    outline_w = 3.5
    shadow_w = 1.5
    border_style = 1
    bold = -1

    if style == "minimal":
        font_name = "Arial"
        p_color = hex_to_ass_color(primary_color or "#FFFFFF")
        o_color = "&H00000000"
        b_color = "&H99000000"
        border_style = 3  # Caixa sólida / background pill
        outline_w = 2.0
        shadow_w = 0
    elif style == "cyber":
        font_name = "Arial Black"
        p_color = hex_to_ass_color(primary_color or "#00FF66")  # Neon green
        o_color = hex_to_ass_color(outline_color or "#051A0A")
        outline_w = 4.0
        shadow_w = 2.5
    elif style == "gradient" or style == "pop":
        font_name = "Arial"
        p_color = hex_to_ass_color(primary_color or "#FF007F")  # Magenta vibrante
        o_color = hex_to_ass_color(outline_color or "#000000")
        outline_w = 3.5
        shadow_w = 2.0
    elif style == "punchy":
        font_name = "Impact"
        p_color = hex_to_ass_color(primary_color or "#FFFFFF")
        o_color = hex_to_ass_color(outline_color or "#990000")  # Vermelho escuro
        outline_w = 4.0
        shadow_w = 2.0
    else:  # viral / hormozi
        font_name = "Arial Black"
        p_color = hex_to_ass_color(primary_color or "#FFDE00")
        o_color = hex_to_ass_color(outline_color or "#000000")
        outline_w = 4.0
        shadow_w = 2.0

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {video_width}
PlayResY: {video_height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_name},{base_font},{p_color},&H000000FF,{o_color},{b_color},{bold},0,0,0,100,100,0,0,{border_style},{outline_w},{shadow_w},2,{margin_lr},{margin_lr},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    for cue in cues:
        raw_text = cue.text.upper() if is_uppercase else cue.text
        text = raw_text.replace("\n", "\\N")
        lines.append(
            f"Dialogue: 0,{_ass_timestamp(cue.start)},{_ass_timestamp(cue.end)},Default,,0,0,0,,{text}"
        )
    return header + "\n".join(lines) + "\n"


def write_ass(
    cues: list[SrtCue],
    path: Path,
    video_width: int,
    video_height: int,
    *,
    is_vertical: bool,
    style: str = "viral",
    position_v: float | None = None,
    font_size_scale: float = 1.0,
    primary_color: str | None = None,
    outline_color: str | None = None,
    is_uppercase: bool = False,
) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ass_content = build_ass(
        cues,
        video_width,
        video_height,
        is_vertical=is_vertical,
        style=style,
        position_v=position_v,
        font_size_scale=font_size_scale,
        primary_color=primary_color,
        outline_color=outline_color,
        is_uppercase=is_uppercase,
    )
    path.write_text(ass_content, encoding="utf-8")
    return path
