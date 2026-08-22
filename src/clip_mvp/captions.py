"""Legendas: SRT (sidecar) e ASS (burn-in) com safe area (SPEC 10 e 14.5)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import SAFE_AREA_BOTTOM
from .transcript import SENTENCE_END, Transcript, Word


@dataclass
class Cue:
    start: float
    end: float
    text: str


def _wrap(words: list[str], max_chars: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) > max_chars and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def build_cues(
    transcript: Transcript,
    start: float,
    end: float,
    max_chars_per_line: int = 26,
    max_lines: int = 2,
    max_duration: float = 3.2,
) -> list[Cue]:
    """Agrupa palavras do intervalo em cues legíveis, relativas ao clip."""
    units = [u for u in transcript.units if u.end > start + 1e-6 and u.start < end - 1e-6]
    cues: list[Cue] = []
    buffer: list[Word] = []
    budget = max_chars_per_line * max_lines

    def flush() -> None:
        if not buffer:
            return
        text = " ".join(w.text.strip() for w in buffer if w.text.strip()).strip()
        if not text:
            buffer.clear()
            return
        cue_start = max(0.0, buffer[0].start - start)
        cue_end = max(cue_start + 0.4, min(end, buffer[-1].end) - start)
        cues.append(Cue(cue_start, cue_end, "\n".join(_wrap(text.split(), max_chars_per_line))))
        buffer.clear()

    for unit in units:
        buffer.append(unit)
        text_len = sum(len(w.text) + 1 for w in buffer)
        span = buffer[-1].end - buffer[0].start
        if text_len >= budget or span >= max_duration or SENTENCE_END.search(unit.text):
            flush()
    flush()
    return cues


def _srt_timestamp(seconds: float) -> str:
    seconds = max(0.0, seconds)
    hours, rem = divmod(int(seconds), 3600)
    minutes, secs = divmod(rem, 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    if millis == 1000:  # arredondamento
        millis = 999
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _ass_timestamp(seconds: float) -> str:
    seconds = max(0.0, seconds)
    hours, rem = divmod(int(seconds), 3600)
    minutes, secs = divmod(rem, 60)
    centis = int(round((seconds - int(seconds)) * 100))
    if centis == 100:
        centis = 99
    return f"{hours:d}:{minutes:02d}:{secs:02d}.{centis:02d}"


def render_srt(cues: list[Cue]) -> str:
    blocks = []
    for i, cue in enumerate(cues, start=1):
        blocks.append(
            f"{i}\n{_srt_timestamp(cue.start)} --> {_srt_timestamp(cue.end)}\n{cue.text}\n"
        )
    return "\n".join(blocks)


def safe_area_margin_v(height: int, bottom_fraction: float = SAFE_AREA_BOTTOM) -> int:
    """MarginV que mantém o bloco de texto acima da UI do TikTok/Shorts.

    Mais 6% de respiro acima dos 20% reservados, para legenda de 2 linhas.
    """
    return int(round(height * (bottom_fraction + 0.06)))


def render_ass(
    cues: list[Cue],
    width: int,
    height: int,
    vertical: bool,
) -> str:
    """ASS estilo TikTok no 9:16 (safe area) e lower third no 16:9."""
    if vertical:
        font_size = int(height * 0.042)
        margin_v = safe_area_margin_v(height)
        margin_h = int(width * 0.10)
        outline, shadow = 4, 1
    else:
        font_size = int(height * 0.05)
        margin_v = int(height * 0.07)
        margin_h = int(width * 0.08)
        outline, shadow = 3, 1

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Clip,DejaVu Sans,{font_size},&H00FFFFFF,&H000000FF,&H00101010,&H80000000,-1,0,0,0,100,100,0,0,1,{outline},{shadow},2,{margin_h},{margin_h},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [
        "Dialogue: 0,{start},{end},Clip,,0,0,0,,{text}".format(
            start=_ass_timestamp(cue.start),
            end=_ass_timestamp(cue.end),
            text=cue.text.replace("\n", r"\N"),
        )
        for cue in cues
    ]
    return header + "\n".join(lines) + "\n"


def write_clip_captions(
    out_dir: Path,
    transcript: Transcript,
    horizontal: tuple[float, float],
    vertical: tuple[float, float] | None,
) -> dict[str, Path]:
    """Arquivos de legenda do corte.

    * `captions.srt` — sidecar, no intervalo canônico (16:9);
    * `captions.ass` — estilo TikTok/Shorts com safe area, no intervalo 9:16;
    * `captions_16x9.ass` — lower third, usado só no burn-in do 16:9.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}

    h_cues = build_cues(transcript, horizontal[0], horizontal[1], max_chars_per_line=38)
    srt_path = out_dir / "captions.srt"
    srt_path.write_text(render_srt(h_cues), encoding="utf-8")
    paths["srt"] = srt_path

    ass_h_path = out_dir / "captions_16x9.ass"
    ass_h_path.write_text(render_ass(h_cues, 1920, 1080, vertical=False), encoding="utf-8")
    paths["ass_horizontal"] = ass_h_path

    if vertical is not None:
        v_cues = build_cues(transcript, vertical[0], vertical[1])
        ass_path = out_dir / "captions.ass"
        ass_path.write_text(render_ass(v_cues, 1080, 1920, vertical=True), encoding="utf-8")
        paths["ass_vertical"] = ass_path
    return paths
