"""Configuração central do clip-mvp: carrega .env e expõe defaults da SPEC."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Carrega .env do diretório de trabalho atual (cwd) e, como fallback, da raiz do repo.
load_dotenv()

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass
class Settings:
    """Configuração resolvida a partir de variáveis de ambiente (.env)."""

    openrouter_api_key: str = field(default_factory=lambda: os.getenv("OPENROUTER_API_KEY", ""))
    openrouter_base_url: str = field(
        default_factory=lambda: os.getenv("OPENROUTER_BASE_URL", OPENROUTER_BASE_URL)
    )

    stt_model: str = field(default_factory=lambda: os.getenv("OPENROUTER_STT_MODEL", "openai/whisper-1"))
    candidate_model: str = field(
        default_factory=lambda: os.getenv("OPENROUTER_CANDIDATE_MODEL", "google/gemini-2.5-flash")
    )
    score_model: str = field(
        default_factory=lambda: os.getenv("OPENROUTER_SCORE_MODEL", "google/gemini-2.5-flash")
    )
    meta_model: str = field(
        default_factory=lambda: os.getenv("OPENROUTER_META_MODEL", os.getenv("OPENROUTER_CANDIDATE_MODEL", "google/gemini-2.5-flash"))
    )

    # Regras de fronteira / padding (SPEC §2.5, §14.1)
    pad_ms_min: int = field(default_factory=lambda: _env_int("CLIP_PAD_MS_MIN", 200))
    pad_ms_max: int = field(default_factory=lambda: _env_int("CLIP_PAD_MS_MAX", 400))

    # Duração máxima do vertical (SPEC §2)
    vertical_max_s: float = field(default_factory=lambda: _env_float("CLIP_VERTICAL_MAX_S", 90.0))

    # Score (SPEC §3, §8)
    min_score_default: float = field(default_factory=lambda: _env_float("CLIP_MIN_SCORE", 60.0))

    # Custos estimados (USD) para --dry-run / --budget (SPEC §14.4). Valores aproximados,
    # configuráveis via .env; usados apenas para estimativa, não são cobrança real.
    cost_stt_usd_per_min: float = field(default_factory=lambda: _env_float("CLIP_COST_STT_USD_PER_MIN", 0.006))
    cost_text_usd_per_candidate: float = field(
        default_factory=lambda: _env_float("CLIP_COST_TEXT_USD_PER_CANDIDATE", 0.001)
    )
    cost_vision_usd_per_frame: float = field(
        default_factory=lambda: _env_float("CLIP_COST_VISION_USD_PER_FRAME", 0.003)
    )
    frames_per_score: int = field(default_factory=lambda: _env_int("CLIP_FRAMES_PER_SCORE", 3))

    # Diretórios (SPEC §5)
    work_dir: Path = field(default_factory=lambda: Path(os.getenv("CLIP_WORK_DIR", "work")))
    out_dir: Path = field(default_factory=lambda: Path(os.getenv("CLIP_OUT_DIR", "out")))

    # Download (SPEC §6: 720p)
    download_height: int = field(default_factory=lambda: _env_int("CLIP_DOWNLOAD_HEIGHT", 720))

    # Feedback few-shot (SPEC §14.7)
    feedback_examples_n: int = field(default_factory=lambda: _env_int("CLIP_FEEDBACK_EXAMPLES_N", 6))

    def require_api_key(self) -> str:
        if not self.openrouter_api_key:
            raise RuntimeError(
                "OPENROUTER_API_KEY não configurada. Copie .env.example para .env e "
                "preencha sua chave da OpenRouter."
            )
        return self.openrouter_api_key


def get_settings() -> Settings:
    return Settings()
