"""Legendas e safe area do 9:16 (SPEC 10 e 14.5)."""

import re

from clip_mvp.captions import build_cues, render_ass, render_srt, safe_area_margin_v
from clip_mvp.config import SAFE_AREA_BOTTOM


def test_cues_ficam_dentro_do_intervalo_do_clip(transcript):
    start, end = 120.0, 180.0
    cues = build_cues(transcript, start, end)
    assert cues
    assert all(cue.start >= 0 for cue in cues)
    assert all(cue.end <= (end - start) + 0.5 for cue in cues)
    assert all(cue.end > cue.start for cue in cues)


def test_srt_tem_timestamps_validos(transcript):
    srt = render_srt(build_cues(transcript, 60.0, 100.0))
    assert "-->" in srt
    for line in srt.splitlines():
        if "-->" in line:
            assert re.match(
                r"^\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3}$", line
            ), line


def test_safe_area_evita_os_20_por_cento_de_baixo():
    height = 1920
    margin = safe_area_margin_v(height)
    assert margin > height * SAFE_AREA_BOTTOM, "legenda entraria na UI do TikTok/Shorts"
    assert margin < height * 0.5, "legenda subiu demais e saiu da zona de leitura"


def test_ass_vertical_usa_margem_segura(transcript):
    ass = render_ass(build_cues(transcript, 30.0, 60.0), 1080, 1920, vertical=True)
    style = next(line for line in ass.splitlines() if line.startswith("Style: Clip"))
    margin_v = int(style.split(",")[-2])
    assert margin_v == safe_area_margin_v(1920)
    assert "PlayResY: 1920" in ass


def test_ass_horizontal_usa_lower_third(transcript):
    ass = render_ass(build_cues(transcript, 30.0, 60.0), 1920, 1080, vertical=False)
    style = next(line for line in ass.splitlines() if line.startswith("Style: Clip"))
    margin_v = int(style.split(",")[-2])
    assert margin_v < 1080 * SAFE_AREA_BOTTOM


def test_quebra_de_linha_respeita_limite(transcript):
    cues = build_cues(transcript, 10.0, 90.0, max_chars_per_line=26)
    for cue in cues:
        for line in cue.text.split("\n"):
            # Uma palavra sozinha pode passar do limite; o resto não.
            assert len(line) <= 26 or " " not in line
