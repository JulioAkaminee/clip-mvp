"""Roda o pipeline (mockado) sobre a fixture BR e valida as expectativas
mínimas de `tests/fixtures/expected.json` (SPEC §14.8): falha se regredir.

Este é o teste que a SPEC §14.8 pede para rodar sempre que os prompts de
candidatos/score mudarem. Ele não checa "o pipeline rodou" — isso
`test_pipeline.py` já faz. Ele checa as regras duras do produto no artefato
final, que é onde uma regressão de prompt aparece.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from clip_mvp import pipeline as pipeline_mod
from clip_mvp.boundaries import crosses_word_midpoint
from clip_mvp.models import Transcript

from test_pipeline import FakeOpenRouterClient, _patch_download, _settings

#: `00:00:01,250 --> 00:00:04,000`
SRT_TIMING = re.compile(
    r"(\d{2}):(\d{2}):(\d{2}),(\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2}),(\d{3})"
)


def _video_size(path: Path) -> tuple[int, int]:
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    stream = json.loads(out.stdout)["streams"][0]
    return stream["width"], stream["height"]


def _has_audio(path: Path) -> bool:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
         "stream=codec_type", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return bool(json.loads(out.stdout).get("streams"))


def _srt_bounds(srt_text: str) -> tuple[float, float] | None:
    """Primeiro início e último fim das cues, em segundos relativos ao corte."""
    def to_seconds(h: str, m: str, s: str, ms: str) -> float:
        return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0

    spans = [
        (to_seconds(*match.groups()[:4]), to_seconds(*match.groups()[4:]))
        for match in SRT_TIMING.finditer(srt_text)
    ]
    if not spans:
        return None
    return min(s for s, _ in spans), max(e for _, e in spans)


def _run_fixture_job(tmp_path, monkeypatch, sample_video_path, whisper_verbose_json_raw):
    _patch_download(monkeypatch, sample_video_path)
    settings = _settings(tmp_path)

    candidates_payload = {
        "candidates": [
            {
                "title": "Momento BR de teste",
                "text_excerpt": "Cê já tentou aquele treino novo?",
                "window_9x16": {"start": 0.0, "end": 9.8},
                "window_16x9": {"start": 0.0, "end": 9.8},
                "context_complete": True,
                "vertical_skip_reason": None,
                "llm_notes": "fixture",
            }
        ]
    }
    score_payload = {
        "breakdown": {"hook": 20, "emocao": 20, "citavel": 20, "arco": 20},
        "total": 80,
        "context_complete": True,
        "reason": "fixture",
    }
    meta_payload = {"youtube": {"shorts_title": "T"}, "tiktok": {"caption": "C"}}

    client = FakeOpenRouterClient(
        whisper_verbose_json_raw, candidates_payload, score_payload, meta_payload
    )
    summary = pipeline_mod.run_job(
        "https://youtube.com/watch?v=fixture", settings, pipeline_mod.RunOptions(), client=client
    )
    return summary, settings


def test_fixture_meets_minimum_expectations(
    tmp_path, monkeypatch, sample_video_path, whisper_verbose_json_raw, expected_fixture
):
    summary, settings = _run_fixture_job(
        tmp_path, monkeypatch, sample_video_path, whisper_verbose_json_raw
    )

    assert summary.selected >= expected_fixture["min_candidates_context_complete"]

    job_dir = settings.work_dir / summary.job_id
    transcript = Transcript.model_validate(
        json.loads((job_dir / "transcript.json").read_text(encoding="utf-8"))
    )
    words = transcript.all_words()

    has_vertical_le_90s = False
    for clip in summary.clips:
        out_dir = Path(clip["out_dir"])
        meta = json.loads((out_dir / "meta.json").read_text(encoding="utf-8"))

        # A expectativa se chama "context_complete" desde o começo mas nunca era
        # verificada: um corte truncado passaria o teste calado.
        if expected_fixture["requires_context_complete_in_meta"]:
            assert meta["context_complete"] is True, f"{out_dir.name} não fecha contexto"

        # SPEC §13: score e reason no meta.json E no nome da pasta.
        if expected_fixture["requires_score_in_folder_name"]:
            assert out_dir.name.startswith(f"{meta['score']}_")
            assert meta["reason"]

        h = meta["windows"]["horizontal_16x9"]
        v = meta["windows"].get("vertical_9x16")

        if v is not None:
            assert v["duration_s"] <= expected_fixture["max_vertical_9x16_duration_s"]
            if v["duration_s"] <= 90:
                has_vertical_le_90s = True
            if expected_fixture["no_mid_word_cuts"]:
                assert not crosses_word_midpoint(v["start"], v["end"], words)
            # O 9:16 é o mesmo momento do 16:9 (possivelmente encolhido), nunca
            # um trecho de fora dele (SPEC §2).
            if expected_fixture["vertical_window_inside_horizontal"]:
                assert v["start"] >= h["start"] - 1e-6
                assert v["end"] <= h["end"] + 1e-6
        else:
            assert meta["vertical_skipped"], "sem 9:16 o meta tem de dizer por quê"

        if expected_fixture["no_mid_word_cuts"]:
            assert not crosses_word_midpoint(h["start"], h["end"], words)

    if expected_fixture["requires_at_least_one_vertical_9x16_le_90s"]:
        assert has_vertical_le_90s


def test_fixture_exports_have_the_expected_shape(
    tmp_path, monkeypatch, sample_video_path, whisper_verbose_json_raw, expected_fixture
):
    """SPEC §7: cada corte sai em 9:16 (face + center) e 16:9, com áudio.

    Os testes de render exercitam as funções isoladas; aqui a checagem é no
    artefato que o pipeline entregou — é onde um export sem áudio (o mux do
    facetrack com loudnorm) ou com aspect errado apareceria.
    """
    summary, _ = _run_fixture_job(
        tmp_path, monkeypatch, sample_video_path, whisper_verbose_json_raw
    )
    sizes = expected_fixture["expected_format_sizes"]

    for clip in summary.clips:
        out_dir = Path(clip["out_dir"])
        present = [name for name in sizes if (out_dir / name).is_file()]
        assert present, f"{out_dir.name} não exportou nenhum formato"

        for name in present:
            path = out_dir / name
            assert _video_size(path) == tuple(sizes[name]), name
            if expected_fixture["requires_audio_track_in_every_export"]:
                assert _has_audio(path), f"{name} saiu sem trilha de áudio"


def test_fixture_captions_stay_inside_the_exported_window(
    tmp_path, monkeypatch, sample_video_path, whisper_verbose_json_raw, expected_fixture
):
    """SPEC §10: o SRT é o recorte da transcrição no intervalo do clip.

    Uma cue que começa antes de 0 ou termina depois do fim do corte é legenda de
    outra parte do vídeo aparecendo no Short.
    """
    if not expected_fixture["captions_must_stay_inside_the_window"]:
        return

    summary, _ = _run_fixture_job(
        tmp_path, monkeypatch, sample_video_path, whisper_verbose_json_raw
    )

    for clip in summary.clips:
        out_dir = Path(clip["out_dir"])
        meta = json.loads((out_dir / "meta.json").read_text(encoding="utf-8"))
        for name, window_key in (
            ("captions.srt", "horizontal_16x9"),
            ("captions_9x16.srt", "vertical_9x16"),
        ):
            path = out_dir / name
            window = meta["windows"].get(window_key)
            if not path.is_file() or window is None:
                continue
            bounds = _srt_bounds(path.read_text(encoding="utf-8"))
            assert bounds is not None, f"{name} saiu sem nenhuma cue"
            first, last = bounds
            assert first >= 0.0, f"{name} começa antes do corte"
            assert last <= window["duration_s"] + 0.05, f"{name} passa do fim do corte"
