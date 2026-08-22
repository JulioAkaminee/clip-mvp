from __future__ import annotations

import json
from pathlib import Path

import pytest

from clip_mvp.models import Transcript

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture()
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture()
def sample_video_path() -> Path:
    return FIXTURES_DIR / "sample_video.mp4"


@pytest.fixture()
def transcript_pt_br() -> Transcript:
    data = json.loads((FIXTURES_DIR / "transcript_pt_br.json").read_text(encoding="utf-8"))
    return Transcript.model_validate(data)


@pytest.fixture()
def whisper_verbose_json_raw() -> dict:
    return json.loads((FIXTURES_DIR / "whisper_verbose_json_raw.json").read_text(encoding="utf-8"))


@pytest.fixture()
def expected_fixture() -> dict:
    return json.loads((FIXTURES_DIR / "expected.json").read_text(encoding="utf-8"))
