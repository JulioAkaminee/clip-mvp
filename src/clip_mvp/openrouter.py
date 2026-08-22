"""Cliente OpenRouter (STT + LLM texto + LLM vision).

Toda a IA do produto passa por aqui — nenhum modelo local pesado (SPEC 4).
"""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Any

import httpx

from .config import Settings

JSON_BLOCK = re.compile(r"```(?:json)?\s*(.+?)```", re.DOTALL)


class OpenRouterError(RuntimeError):
    pass


class OpenRouterClient:
    def __init__(self, settings: Settings, timeout: float = 300.0):
        if not settings.has_api_key:
            raise OpenRouterError(
                "OPENROUTER_API_KEY ausente. Preencha o .env ou rode em modo demo."
            )
        self.settings = settings
        self.timeout = timeout

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.settings.openrouter_api_key}",
            "HTTP-Referer": "https://github.com/JulioAkaminee/clip-mvp",
            "X-Title": "clip-mvp",
        }

    # --- STT -----------------------------------------------------------------
    def transcribe(self, audio: Path, model: str, language: str = "pt") -> dict:
        url = f"{self.settings.openrouter_base_url}/audio/transcriptions"
        data = {
            "model": model,
            "language": language,
            "response_format": "verbose_json",
            "timestamp_granularities[]": ["word", "segment"],
        }
        with httpx.Client(timeout=self.timeout) as client:
            with audio.open("rb") as fh:
                response = client.post(
                    url,
                    headers=self._headers,
                    data=data,
                    files={"file": (audio.name, fh, "audio/mpeg")},
                )
        if response.status_code >= 400:
            raise OpenRouterError(
                f"STT falhou ({response.status_code}): {response.text[:400]}"
            )
        return response.json()

    # --- Chat ----------------------------------------------------------------
    def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float = 0.4,
        max_tokens: int = 4000,
        json_mode: bool = True,
    ) -> str:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(
                f"{self.settings.openrouter_base_url}/chat/completions",
                headers={**self._headers, "Content-Type": "application/json"},
                json=payload,
            )
        if response.status_code >= 400:
            raise OpenRouterError(
                f"LLM falhou ({response.status_code}): {response.text[:400]}"
            )
        data = response.json()
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError) as exc:  # pragma: no cover
            raise OpenRouterError(f"resposta inesperada do LLM: {data}") from exc

    def chat_json(self, model: str, messages: list[dict[str, Any]], **kwargs) -> dict:
        raw = self.chat(model, messages, **kwargs)
        return parse_json(raw)


def parse_json(raw: str) -> dict:
    """Tolerante a ```json ... ``` e texto ao redor."""
    raw = (raw or "").strip()
    if not raw:
        raise OpenRouterError("LLM devolveu resposta vazia")
    for candidate in (raw, *(m.group(1) for m in JSON_BLOCK.finditer(raw))):
        try:
            parsed = json.loads(candidate.strip())
            if isinstance(parsed, dict):
                return parsed
            if isinstance(parsed, list):
                return {"items": parsed}
        except json.JSONDecodeError:
            continue
    start, end = raw.find("{"), raw.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            pass
    raise OpenRouterError(f"não consegui parsear JSON do LLM: {raw[:200]}")


def image_part(path: Path) -> dict:
    """Frame como data URL para o modelo de vision."""
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return {
        "type": "image_url",
        "image_url": {"url": f"data:image/jpeg;base64,{encoded}"},
    }
