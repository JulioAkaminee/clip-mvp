"""Roda o pipeline (mockado) sobre a fixture BR e valida as expectativas
mínimas de `tests/fixtures/expected.json` (SPEC §14.8): falha se regredir."""

from __future__ import annotations

import json
from pathlib import Path

from clip_mvp import pipeline as pipeline_mod
from clip_mvp.boundaries import crosses_word_midpoint
from clip_mvp.models import Transcript

from test_pipeline import FakeOpenRouterClient, _patch_download, _settings


def test_fixture_meets_minimum_expectations(
    tmp_path, monkeypatch, sample_video_path, whisper_verbose_json_raw, expected_fixture
):
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

    client = FakeOpenRouterClient(whisper_verbose_json_raw, candidates_payload, score_payload, meta_payload)

    summary = pipeline_mod.run_job("https://youtube.com/watch?v=fixture", settings, pipeline_mod.RunOptions(), client=client)

    assert summary.selected >= expected_fixture["min_candidates_context_complete"]

    job_dir = settings.work_dir / summary.job_id
    transcript = Transcript.model_validate(json.loads((job_dir / "transcript.json").read_text(encoding="utf-8")))
    words = transcript.all_words()

    has_vertical_le_90s = False
    for clip in summary.clips:
        meta = json.loads((Path(clip["out_dir"]) / "meta.json").read_text(encoding="utf-8"))
        v = meta["windows"].get("vertical_9x16")
        if v is not None:
            assert v["duration_s"] <= expected_fixture["max_vertical_9x16_duration_s"]
            if v["duration_s"] <= 90:
                has_vertical_le_90s = True
            if expected_fixture["no_mid_word_cuts"]:
                assert not crosses_word_midpoint(v["start"], v["end"], words)
        h = meta["windows"]["horizontal_16x9"]
        if expected_fixture["no_mid_word_cuts"]:
            assert not crosses_word_midpoint(h["start"], h["end"], words)

    if expected_fixture["requires_at_least_one_vertical_9x16_le_90s"]:
        assert has_vertical_le_90s
