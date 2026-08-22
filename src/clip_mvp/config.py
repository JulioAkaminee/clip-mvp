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
    # Piso do encolhimento do 9:16: contexto >90s só vira Short se a sub-janela
    # que cabe no teto ainda for um momento, não um fragmento (SPEC §2).
    vertical_min_shrunk_s: float = field(
        default_factory=lambda: _env_float("CLIP_VERTICAL_MIN_SHRUNK_S", 15.0)
    )

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

    # Penalidades determinísticas do score (SPEC §8). Contexto aberto tem teto
    # duro; cortes muito curtos raramente entregam arco completo, então também
    # levam um teto (0 desliga a regra).
    truncated_score_cap: float = field(
        default_factory=lambda: _env_float("CLIP_TRUNCATED_SCORE_CAP", 45.0)
    )
    min_duration_full_arc_s: float = field(
        default_factory=lambda: _env_float("CLIP_MIN_DURATION_FULL_ARC_S", 12.0)
    )
    short_clip_score_cap: float = field(
        default_factory=lambda: _env_float("CLIP_SHORT_CLIP_SCORE_CAP", 70.0)
    )
    # Piso relativo da seleção (SPEC §3.5): distância máxima entre o melhor corte
    # do job e o pior que ainda vale entregar. O limiar absoluto diz "é
    # publicável?"; este diz "presta ao lado do resto deste vídeo?". 0 desliga.
    score_relative_gap: float = field(
        default_factory=lambda: _env_float("CLIP_SCORE_RELATIVE_GAP", 22.0)
    )

    # Diretórios (SPEC §5)
    work_dir: Path = field(default_factory=lambda: Path(os.getenv("CLIP_WORK_DIR", "work")))
    out_dir: Path = field(default_factory=lambda: Path(os.getenv("CLIP_OUT_DIR", "out")))

    # Download (SPEC §6: 720p)
    download_height: int = field(default_factory=lambda: _env_int("CLIP_DOWNLOAD_HEIGHT", 720))

    # Feedback few-shot (SPEC §14.7)
    feedback_examples_n: int = field(default_factory=lambda: _env_int("CLIP_FEEDBACK_EXAMPLES_N", 6))

    # Paralelismo. O alvo é um MacBook i5 4-core 16GB: chamadas de rede
    # (STT/score/meta) paralelizam bem, mas ffmpeg e MediaPipe competem por CPU
    # e RAM — subir demais o render faz a máquina entrar em swap e ficar mais
    # lenta que rodando serial.
    network_workers: int = field(default_factory=lambda: _env_int("CLIP_NETWORK_WORKERS", 3))
    render_workers: int = field(
        default_factory=lambda: _env_int(
            "CLIP_RENDER_WORKERS", max(1, min(2, (os.cpu_count() or 4) // 2))
        )
    )

    def require_api_key(self) -> str:
        if not self.openrouter_api_key:
            raise RuntimeError(
                "OPENROUTER_API_KEY não configurada. Copie .env.example para .env e "
                "preencha sua chave da OpenRouter."
            )
        return self.openrouter_api_key


def get_settings() -> Settings:
    return Settings()
