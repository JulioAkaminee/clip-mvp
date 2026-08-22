"""Configuração da OpenRouter feita pela interface (chave + modelo por papel).

O `.env` continua sendo o default do projeto (SPEC §4). Este módulo adiciona uma
segunda camada, gravada em disco pelo próprio usuário na UI, que **sobrepõe** o
`.env` quando preenchida:

    default do código  <  .env  <  arquivo de settings (UI)

O arquivo vive fora do repositório (por padrão em `~/.config/clip-mvp/`), com
permissão `0600`, para que a chave não caia num commit por acidente. A chave só
sai daqui mascarada (`mask_key`): nem a API nem a UI recebem o valor completo.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from .config import Settings

SCHEMA_VERSION = 1

#: Nome do arquivo dentro do diretório de configuração do usuário.
SETTINGS_FILENAME = "settings.json"


class SettingsValidationError(ValueError):
    """Entrada inválida vinda da UI. A mensagem é PT-BR e vai direto para a tela."""


@dataclass(frozen=True)
class ModelRole:
    """Um papel de IA do pipeline e o campo de `Settings` que ele controla."""

    key: str
    field: str
    label: str
    description: str
    #: Modalidade que o modelo precisa aceitar na entrada (`text`, `image`, `audio`).
    requires: tuple[str, ...]
    #: Papéis opcionais herdam de outro quando ficam vazios (diarização ← STT).
    inherits_from: str | None = None


#: Todos os papéis de IA configuráveis, na ordem em que a UI os mostra.
MODEL_ROLES: tuple[ModelRole, ...] = (
    ModelRole(
        key="stt",
        field="stt_model",
        label="STT / Whisper",
        description="Transcreve o áudio em PT-BR com timestamps por palavra.",
        requires=("audio",),
    ),
    ModelRole(
        key="candidates",
        field="candidate_model",
        label="Candidatos (texto)",
        description="Lê a transcrição e propõe os trechos com contexto fechado.",
        requires=("text",),
    ),
    ModelRole(
        key="score",
        field="score_model",
        label="Score (vision)",
        description="Pontua cada candidato com o texto da janela + 3 frames.",
        requires=("text", "image"),
    ),
    ModelRole(
        key="meta",
        field="meta_model",
        label="Meta / texto social",
        description="Escreve títulos, descrições e hashtags de YouTube e TikTok.",
        requires=("text",),
    ),
    ModelRole(
        key="diarization",
        field="diarization_model",
        label="Diarização (opcional)",
        description="Separa falantes para o face tracking. Vazio: usa o modelo de STT.",
        requires=("audio",),
        inherits_from="stt",
    ),
)

ROLE_BY_KEY: dict[str, ModelRole] = {role.key: role for role in MODEL_ROLES}

#: Ids da OpenRouter são `autor/modelo` com sufixo opcional (`:free`, `:beta`).
#: Qualquer id é aceito (o catálogo muda toda semana) — a regra só barra o que
#: não pode ser um slug: espaço, quebra de linha, caractere de controle.
_MODEL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+\-]*(?:/[A-Za-z0-9._:@+\-]+)*$")
MODEL_ID_MAX_LEN = 200

#: Chaves da OpenRouter são `sk-or-v1-<hex longo>`. O piso é curto de propósito:
#: barrar "colei errado" sem apostar num formato que a OpenRouter pode mudar.
API_KEY_MIN_LEN = 16
API_KEY_MAX_LEN = 400


@dataclass
class StoredSettings:
    """Conteúdo do arquivo de settings (o que a UI gravou)."""

    openrouter_api_key: str = ""
    models: dict[str, str] = field(default_factory=dict)
    updated_at: float | None = None

    def model_for(self, role_key: str) -> str:
        return (self.models.get(role_key) or "").strip()

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "openrouter_api_key": self.openrouter_api_key,
            "models": {key: value for key, value in self.models.items() if value},
            "updated_at": self.updated_at,
        }


def settings_file() -> Path:
    """Caminho do arquivo de settings da UI.

    `CLIP_SETTINGS_FILE` tem prioridade (útil em teste e para quem quer o arquivo
    junto do projeto); senão vale o diretório de config do usuário.
    """
    explicit = os.getenv("CLIP_SETTINGS_FILE")
    if explicit:
        return Path(explicit).expanduser()
    base = os.getenv("XDG_CONFIG_HOME")
    root = Path(base).expanduser() if base else Path.home() / ".config"
    return root / "clip-mvp" / SETTINGS_FILENAME


def load_stored(path: Path | None = None) -> StoredSettings:
    """Lê o arquivo de settings. Ausente ou corrompido: volta vazio.

    Um JSON quebrado não pode impedir o `clip serve` de subir — sem chave a UI
    já sabe pedir a configuração.
    """
    path = path or settings_file()
    try:
        raw = json.loads(Path(path).read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return StoredSettings()
    if not isinstance(raw, dict):
        return StoredSettings()

    key = raw.get("openrouter_api_key")
    models_raw = raw.get("models")
    models: dict[str, str] = {}
    if isinstance(models_raw, dict):
        for role in MODEL_ROLES:
            value = models_raw.get(role.key)
            if isinstance(value, str) and value.strip():
                models[role.key] = value.strip()
    updated_at = raw.get("updated_at")
    return StoredSettings(
        openrouter_api_key=key.strip() if isinstance(key, str) else "",
        models=models,
        updated_at=float(updated_at) if isinstance(updated_at, (int, float)) else None,
    )


def save_stored(stored: StoredSettings, path: Path | None = None) -> StoredSettings:
    """Grava o arquivo com permissão `0600` (dono lê/escreve, mais ninguém).

    A escrita é atômica: um `clip serve` lendo o arquivo enquanto a UI salva
    nunca pega um JSON pela metade.
    """
    path = Path(path or settings_file())
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass

    stored.updated_at = time.time()
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(stored.to_json(), ensure_ascii=False, indent=2), "utf-8")
    # chmod antes do rename: entre criar e proteger o arquivo não existe janela
    # em que a chave fique legível para outros usuários da máquina.
    tmp.chmod(0o600)
    tmp.replace(path)
    return stored


def apply_stored(settings: Settings, stored: StoredSettings | None = None) -> Settings:
    """Devolve uma copia de `settings` com a chave/modelos da UI por cima do `.env`."""
    stored = load_stored() if stored is None else stored
    changes: dict[str, Any] = {}
    if stored.openrouter_api_key:
        changes["openrouter_api_key"] = stored.openrouter_api_key
    for role in MODEL_ROLES:
        value = stored.model_for(role.key)
        if value:
            changes[role.field] = value
    return replace(settings, **changes) if changes else settings


def mask_key(value: str | None) -> str | None:
    """Chave em formato de identificação: `sk-or-…a1b2`, nunca o valor completo."""
    if not value:
        return None
    value = value.strip()
    if len(value) <= 8:
        return "•" * len(value)
    return f"{value[:6]}…{value[-4:]}"


def validate_api_key(value: str) -> str:
    """Valida a chave colada na UI (mensagens PT-BR, sem ecoar o valor)."""
    key = (value or "").strip()
    if not key:
        raise SettingsValidationError("Cole a chave da OpenRouter (ela começa com `sk-or-`).")
    if any(char.isspace() for char in key):
        raise SettingsValidationError(
            "A chave não pode conter espaços nem quebras de linha — copie apenas o valor."
        )
    if len(key) < API_KEY_MIN_LEN:
        raise SettingsValidationError(
            f"A chave parece incompleta (menos de {API_KEY_MIN_LEN} caracteres)."
        )
    if len(key) > API_KEY_MAX_LEN:
        raise SettingsValidationError(
            f"A chave passou de {API_KEY_MAX_LEN} caracteres — confira o que foi colado."
        )
    return key


def validate_model_id(value: str, *, role: ModelRole | None = None) -> str:
    """Valida um id de modelo da OpenRouter. Qualquer slug do catálogo passa."""
    model = (value or "").strip()
    where = f" de {role.label}" if role else ""
    if not model:
        raise SettingsValidationError(f"Informe o id do modelo{where}.")
    if len(model) > MODEL_ID_MAX_LEN:
        raise SettingsValidationError(
            f"O id do modelo{where} passou de {MODEL_ID_MAX_LEN} caracteres."
        )
    if not _MODEL_ID_RE.match(model):
        raise SettingsValidationError(
            f"Id de modelo{where} inválido: use o formato `autor/modelo` da OpenRouter "
            "(ex.: `google/gemini-2.5-flash`), sem espaços."
        )
    return model


def role_state(
    settings: Settings, env: Settings, stored: StoredSettings, role: ModelRole
) -> dict[str, Any]:
    """Estado de um papel para a API: valor em uso, origem e default do `.env`.

    `env` é a camada de ambiente sem a UI: é o valor que o botão "restaurar
    padrão" devolve.
    """
    ui_value = stored.model_for(role.key)
    env_value = getattr(env, role.field, "") or ""
    effective = getattr(settings, role.field, "") or ""
    inherited = ""
    if not effective and role.inherits_from:
        parent = ROLE_BY_KEY[role.inherits_from]
        inherited = getattr(settings, parent.field, "") or ""
    return {
        "role": role.key,
        "label": role.label,
        "description": role.description,
        "requires": list(role.requires),
        "optional": role.inherits_from is not None,
        "inherits_from": role.inherits_from,
        "value": effective,
        "env_default": env_value,
        "source": "ui" if ui_value else ("env" if effective else "inherited"),
        "effective": effective or inherited,
    }


def describe(
    settings: Settings,
    stored: StoredSettings | None = None,
    *,
    env: Settings | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    """Payload de `GET /api/settings`: nunca contém a chave em texto claro.

    `settings` é a configuração efetiva (`.env` + UI) e `env` a camada de
    ambiente pura, para que a tela mostre lado a lado "o que está valendo" e "o
    padrão do projeto".
    """
    from .config import env_settings

    stored = load_stored(path) if stored is None else stored
    env = env if env is not None else env_settings()
    key = settings.openrouter_api_key or ""
    return {
        "openrouter": {
            "configured": bool(key),
            "masked": mask_key(key),
            "source": "ui" if stored.openrouter_api_key else ("env" if key else None),
            "base_url": settings.openrouter_base_url,
        },
        "models": [role_state(settings, env, stored, role) for role in MODEL_ROLES],
        "settings_file": str(path or settings_file()),
        "updated_at": stored.updated_at,
    }
