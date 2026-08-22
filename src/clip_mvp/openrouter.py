"""Cliente OpenRouter (STT, texto e vision) — SPEC §4.

Toda chamada de IA do pipeline passa por aqui, usando o SDK da OpenAI com
`base_url` apontando para a OpenRouter (conforme SPEC §4). Isolado num só
módulo para facilitar mock em testes (nenhum outro módulo importa `openai`
diretamente).
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from tenacity import retry, stop_after_attempt, wait_exponential

from .config import OPENROUTER_BASE_URL, Settings

#: Timeout do catálogo/validação de chave. É uma chamada de UI: melhor falhar
#: rápido com mensagem do que deixar a tela girando.
CATALOG_TIMEOUT_S = 20.0


class OpenRouterError(RuntimeError):
    """Falha ao falar com a OpenRouter, com mensagem PT-BR pronta para a tela.

    A mensagem nunca inclui a chave: só o que a OpenRouter respondeu.
    """


class OpenRouterClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._client = None

    @property
    def client(self):
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(
                api_key=self.settings.require_api_key(),
                base_url=self.settings.openrouter_base_url,
            )
        return self._client

    @retry(wait=wait_exponential(multiplier=1, min=1, max=10), stop=stop_after_attempt(3))
    def transcribe(
        self, audio_path: Path, *, language: str = "pt", model: str | None = None
    ) -> dict[str, Any]:
        """Chama o endpoint de transcrição (Whisper) pedindo verbose_json com
        timestamps por palavra, quando o provider suportar (SPEC §14.1).

        `model` sobrepõe o papel de STT — a diarização usa isso para pedir um
        modelo com speaker labels sem trocar o STT do job (SPEC §9).
        """
        with open(audio_path, "rb") as f:
            resp = self.client.audio.transcriptions.create(
                model=model or self.settings.stt_model,
                file=f,
                language=language,
                response_format="verbose_json",
                timestamp_granularities=["word", "segment"],
            )
        if hasattr(resp, "model_dump"):
            return resp.model_dump()
        if isinstance(resp, dict):
            return resp
        return json.loads(resp.json()) if hasattr(resp, "json") else dict(resp)

    @retry(wait=wait_exponential(multiplier=1, min=1, max=10), stop=stop_after_attempt(3))
    def chat_json(
        self,
        *,
        model: str,
        system: str,
        user: str,
        images_b64: list[str] | None = None,
        temperature: float = 0.4,
    ) -> dict[str, Any]:
        """Chat completion pedindo JSON estruturado, opcionalmente com imagens
        (usado no scorer de vision, SPEC §8)."""
        content: list[dict[str, Any]] = [{"type": "text", "text": user}]
        for img in images_b64 or []:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{img}"},
                }
            )

        resp = self.client.chat.completions.create(
            model=model,
            temperature=temperature,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": content},
            ],
        )
        text = resp.choices[0].message.content
        return json.loads(text)


def image_to_b64(path: Path) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


# ---------------------------------------------------------------------------
# Catálogo de modelos e validação de chave (usados pela tela de Configurações)
# ---------------------------------------------------------------------------


def _get_json(path: str, api_key: str, *, base_url: str, timeout: float) -> dict[str, Any]:
    """`GET {base_url}{path}` autenticado, com erro traduzido para PT-BR."""
    import httpx

    url = f"{base_url.rstrip('/')}{path}"
    try:
        response = httpx.get(
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "HTTP-Referer": "https://github.com/JulioAkaminee/clip-mvp",
                "X-Title": "clip-mvp",
            },
            timeout=timeout,
        )
    except httpx.TimeoutException as exc:
        raise OpenRouterError(
            "A OpenRouter não respondeu no tempo esperado. Tente de novo."
        ) from exc
    except httpx.HTTPError as exc:
        raise OpenRouterError(
            "Não foi possível falar com a OpenRouter (rede indisponível?)."
        ) from exc

    if response.status_code in (401, 403):
        raise OpenRouterError(
            "A OpenRouter recusou a chave (401). Confira se ela foi copiada inteira "
            "e se ainda está ativa no painel da OpenRouter."
        )
    if response.status_code == 429:
        raise OpenRouterError("A OpenRouter respondeu 429 (limite de uso). Espere e tente de novo.")
    if response.status_code >= 400:
        raise OpenRouterError(
            f"A OpenRouter respondeu {response.status_code} ao consultar o catálogo de modelos."
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise OpenRouterError("Resposta inesperada da OpenRouter (não era JSON).") from exc
    return payload if isinstance(payload, dict) else {"data": payload}


def _price(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_model(raw: dict[str, Any]) -> dict[str, Any]:
    """Reduz um item de `/models` ao que a tela de Configurações mostra.

    O catálogo da OpenRouter é grande e muda toda semana; a UI só precisa do id,
    do nome, do contexto, do preço e de quais modalidades o modelo aceita — é o
    que permite avisar que o papel de score precisa enxergar imagem.
    """
    architecture = raw.get("architecture") or {}
    inputs = architecture.get("input_modalities")
    if not isinstance(inputs, list) or not inputs:
        # Modelos antigos do catálogo só têm `modality: "text+image->text"`.
        modality = str(architecture.get("modality") or raw.get("modality") or "text->text")
        inputs = [part for part in modality.split("->")[0].split("+") if part]
    modalities = sorted({str(item).strip().lower() for item in inputs if str(item).strip()})

    pricing = raw.get("pricing") or {}
    return {
        "id": str(raw.get("id") or "").strip(),
        "name": str(raw.get("name") or raw.get("id") or "").strip(),
        "context_length": raw.get("context_length") or architecture.get("context_length"),
        "input_modalities": modalities,
        "prompt_usd_per_mtok": (
            round(value * 1_000_000, 4) if (value := _price(pricing.get("prompt"))) is not None else None
        ),
        "completion_usd_per_mtok": (
            round(value * 1_000_000, 4)
            if (value := _price(pricing.get("completion"))) is not None
            else None
        ),
        "free": all(
            _price(pricing.get(key)) in (0.0, None) for key in ("prompt", "completion")
        ),
    }


def fetch_models(
    api_key: str, *, base_url: str = OPENROUTER_BASE_URL, timeout: float = CATALOG_TIMEOUT_S
) -> list[dict[str, Any]]:
    """Catálogo da OpenRouter (`GET /models`) normalizado e ordenado por id."""
    payload = _get_json("/models", api_key, base_url=base_url, timeout=timeout)
    data = payload.get("data")
    if not isinstance(data, list):
        raise OpenRouterError("A OpenRouter não devolveu a lista de modelos como esperado.")
    models = [normalize_model(item) for item in data if isinstance(item, dict)]
    return sorted((model for model in models if model["id"]), key=lambda model: model["id"])


def verify_key(
    api_key: str, *, base_url: str = OPENROUTER_BASE_URL, timeout: float = CATALOG_TIMEOUT_S
) -> dict[str, Any]:
    """Testa a chave em `GET /key` e devolve o que dá para mostrar sem vazar nada.

    `/key` é a rota mais honesta para "essa chave funciona?": ela exige
    autenticação de verdade (o catálogo responde até sem chave) e traz crédito e
    limite. Se o endpoint não existir num proxy compatível, cai no catálogo.
    """
    try:
        payload = _get_json("/key", api_key, base_url=base_url, timeout=timeout)
    except OpenRouterError:
        models = fetch_models(api_key, base_url=base_url, timeout=timeout)
        return {"ok": True, "label": None, "models_available": len(models)}

    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    return {
        "ok": True,
        "label": data.get("label"),
        "usage_usd": _price(data.get("usage")),
        "limit_usd": _price(data.get("limit")),
        "limit_remaining_usd": _price(data.get("limit_remaining")),
        "is_free_tier": bool(data.get("is_free_tier")) if "is_free_tier" in data else None,
    }
