"""Configuração central (env + defaults da SPEC)."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

try:  # python-dotenv é opcional em runtime
    from dotenv import load_dotenv
except Exception:  # pragma: no cover

    def load_dotenv(*_args, **_kwargs):  # type: ignore[misc]
        return False


VERSION = "0.1.0"

# --- Regras duras da SPEC (não são configuráveis pelo usuário) ---------------
VERTICAL_MAX_S = 90.0
"""9:16 nunca passa de 1:30 (SPEC 2)."""

PAD_MIN_S = 0.200
PAD_MAX_S = 0.400
"""Folga aplicada antes do start / depois do end (SPEC 14.1)."""

DEFAULT_MIN_SCORE = 60
SAFE_AREA_BOTTOM = 0.20
"""9:16: evitar os ~20% inferiores (UI TikTok/Shorts) — SPEC 14.5."""

ALL_FORMATS = ("vertical_facetrack", "vertical_center", "horizontal_16x9")
ALL_PLATFORMS = ("yt", "tiktok")
CAPTION_MODES = ("burn", "sidecar", "both")

# Faixa alvo de cortes por duração da fonte (SPEC 3)
TARGET_RANGES: tuple[tuple[float, int, int], ...] = (
    (10 * 60, 2, 4),
    (30 * 60, 3, 6),
    (90 * 60, 5, 10),
    (float("inf"), 8, 15),
)


def target_range(duration_s: float) -> tuple[int, int]:
    """Faixa (min, max) de cortes finais sugerida para a duração da fonte."""
    for limit, lo, hi in TARGET_RANGES:
        if duration_s < limit:
            return lo, hi
    return TARGET_RANGES[-1][1], TARGET_RANGES[-1][2]


def _root_dir() -> Path:
    env = os.environ.get("CLIP_MVP_HOME")
    if env:
        return Path(env).expanduser().resolve()
    # src/clip_mvp/config.py -> raiz do repo
    return Path(__file__).resolve().parents[2]


@dataclass
class Settings:
    root: Path = field(default_factory=_root_dir)
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    stt_model: str = "openai/whisper-1"
    candidate_model: str = "google/gemini-2.5-flash"
    score_model: str = "google/gemini-2.5-flash"
    meta_model: str = "google/gemini-2.5-flash"
    demo: bool = False
    """Modo demo: sem chamadas OpenRouter (transcrição/candidatos/score sintéticos)."""

    @property
    def work_dir(self) -> Path:
        return self.root / "work"

    @property
    def out_dir(self) -> Path:
        return self.root / "out"

    @property
    def feedback_path(self) -> Path:
        return self.work_dir / "feedback.jsonl"

    @property
    def has_api_key(self) -> bool:
        return bool(self.openrouter_api_key.strip())

    @property
    def ai_enabled(self) -> bool:
        """IA real só roda com chave e fora do modo demo."""
        return self.has_api_key and not self.demo

    def ensure_dirs(self) -> None:
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.out_dir.mkdir(parents=True, exist_ok=True)


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


_cached: Settings | None = None


def get_settings(refresh: bool = False) -> Settings:
    global _cached
    if _cached is not None and not refresh:
        return _cached
    root = _root_dir()
    load_dotenv(root / ".env", override=False)
    settings = Settings(
        root=root,
        openrouter_api_key=os.environ.get("OPENROUTER_API_KEY", ""),
        openrouter_base_url=os.environ.get(
            "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
        ),
        stt_model=os.environ.get("OPENROUTER_STT_MODEL", "openai/whisper-1"),
        candidate_model=os.environ.get(
            "OPENROUTER_CANDIDATE_MODEL", "google/gemini-2.5-flash"
        ),
        score_model=os.environ.get("OPENROUTER_SCORE_MODEL", "google/gemini-2.5-flash"),
        meta_model=os.environ.get(
            "OPENROUTER_META_MODEL",
            os.environ.get("OPENROUTER_CANDIDATE_MODEL", "google/gemini-2.5-flash"),
        ),
        demo=_env_flag("CLIP_MVP_DEMO"),
    )
    settings.ensure_dirs()
    _cached = settings
    return settings


def tool_status() -> dict[str, bool]:
    """Dependências locais disponíveis (usado no /api/health e na UI)."""
    try:
        import mediapipe  # noqa: F401

        mediapipe_ok = True
    except Exception:
        mediapipe_ok = False
    try:
        import yt_dlp  # noqa: F401

        ytdlp_ok = True
    except Exception:
        ytdlp_ok = bool(shutil.which("yt-dlp"))
    return {
        "ffmpeg": bool(shutil.which("ffmpeg")),
        "ffprobe": bool(shutil.which("ffprobe")),
        "yt_dlp": ytdlp_ok,
        "mediapipe": mediapipe_ok,
    }
