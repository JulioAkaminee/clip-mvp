"""Configuração central do clip-mvp: carrega .env e expõe defaults da SPEC."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Carrega .env do diretório de trabalho atual (cwd) e, como fallback, da raiz do repo.
load_dotenv()

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

#: Modelo de texto/vision barato o suficiente para rodar o pipeline inteiro
#: (SPEC §4: "modelo texto barato/rápido" para candidatos, vision no score).
DEFAULT_TEXT_MODEL = "google/gemini-2.5-flash"
DEFAULT_STT_MODEL = "openai/whisper-1"

#: Papéis de IA → (variável de ambiente, default do código). O papel de
#: diarização nasce vazio: sem valor próprio ele reusa o modelo de STT (SPEC §9).
MODEL_ENV_DEFAULTS: dict[str, tuple[str, str]] = {
    "stt_model": ("OPENROUTER_STT_MODEL", DEFAULT_STT_MODEL),
    "candidate_model": ("OPENROUTER_CANDIDATE_MODEL", DEFAULT_TEXT_MODEL),
    "score_model": ("OPENROUTER_SCORE_MODEL", DEFAULT_TEXT_MODEL),
    "meta_model": ("OPENROUTER_META_MODEL", ""),
    "diarization_model": ("OPENROUTER_DIARIZATION_MODEL", ""),
}


def env_default_model(field_name: str) -> str:
    """Valor de `.env` (ou default do código) de um papel, ignorando a UI.

    É o que a interface mostra como "padrão do projeto" no botão de restaurar.
    """
    env_name, fallback = MODEL_ENV_DEFAULTS[field_name]
    value = (os.getenv(env_name) or "").strip()
    if value:
        return value
    if field_name == "meta_model":
        # Sem OPENROUTER_META_MODEL o texto social usa o mesmo modelo dos
        # candidatos: são as duas chamadas de texto puro do pipeline.
        return env_default_model("candidate_model")
    return fallback


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

    stt_model: str = field(default_factory=lambda: env_default_model("stt_model"))
    candidate_model: str = field(default_factory=lambda: env_default_model("candidate_model"))
    score_model: str = field(default_factory=lambda: env_default_model("score_model"))
    meta_model: str = field(default_factory=lambda: env_default_model("meta_model"))
    #: Vazio = diariza com o modelo de STT (SPEC §9).
    diarization_model: str = field(default_factory=lambda: env_default_model("diarization_model"))

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

    # Batimento do progresso: de quanto em quanto tempo reemitir o snapshot
    # enquanto o job roda, para o ETA andar dentro de estágios sem unidades
    # contáveis (um prompt, um ffmpeg). 0 desliga.
    progress_heartbeat_s: float = field(
        default_factory=lambda: _env_float("CLIP_PROGRESS_HEARTBEAT_S", 2.0)
    )

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
                "OPENROUTER_API_KEY não configurada. Configure a chave em "
                "Configurações na interface (clip serve) ou copie .env.example "
                "para .env e preencha sua chave da OpenRouter."
            )
        return self.openrouter_api_key

    def model_for_diarization(self) -> str:
        return self.diarization_model or self.stt_model


def env_settings() -> Settings:
    """Configuração só do ambiente (`.env`), sem o que a UI gravou."""
    return Settings()


def get_settings() -> Settings:
    """Configuração efetiva: `.env` com a chave/modelos da UI por cima.

    A interface e a CLI compartilham o mesmo arquivo de settings, então uma chave
    configurada na tela também vale para `clip "URL"` no terminal.
    """
    from .settings_store import apply_stored

    return apply_stored(Settings())
