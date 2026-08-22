import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Cada teste roda com `work/` e `out/` próprios."""
    monkeypatch.setenv("CLIP_MVP_HOME", str(tmp_path))
    monkeypatch.setenv("CLIP_MVP_DEMO", "1")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    from clip_mvp import config

    config.get_settings(refresh=True)
    yield tmp_path
    config._cached = None


@pytest.fixture
def transcript():
    from clip_mvp import demo

    return demo.build_transcript(900.0, seed="pytest")


def pytest_addoption(parser):
    parser.addoption(
        "--fixture-video",
        action="store",
        default=os.environ.get("CLIP_MVP_FIXTURE_VIDEO", ""),
        help="Vídeo local usado no teste de ponta a ponta (SPEC 14.8)",
    )


@pytest.fixture
def fixture_video(request) -> Path | None:
    raw = request.config.getoption("--fixture-video")
    if raw:
        path = Path(raw)
        return path if path.exists() else None
    default = ROOT / "tests" / "fixtures" / "demo_480s.mp4"
    return default if default.exists() else None
